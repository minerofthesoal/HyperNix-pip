"""smoke_alarm — training-step planner and time / memory monitor.

A *smoke alarm* watches a training run before and during execution.
Before: given a time budget plus hardware and model details, it
recommends a step count.  During: given an elapsed-time / completed-step
checkpoint it warns when the run is on track to overrun (or
under-utilize) the budget.

Four tiers, named in the smoke-detector idiom — from a 1970s ionization
detector that just trips on smoke through to a networked unit with
multiple sensors and history:

* :class:`RadsAlarm`       (radioactive / "Rads" alarm) — lightest.
                            Pure constants, no hardware introspection.
* :class:`GasAlarm`        — uses CPU and GPU presets to scale the
                            per-step time estimate by hardware.
* :class:`ModernAlarm`     — runs a brief warmup pass against a real
                            model to **measure** per-step time, then
                            extrapolates.
* :class:`AutoAlarm`       — picks the most detailed alarm whose
                            inputs are satisfied (warmup model? -> Modern;
                            CPU/GPU presets? -> Gas; else Rads).

All four expose the same surface:

    alarm.estimate_step_seconds()    -> float
    alarm.recommended_steps()        -> int
    alarm.budget()                   -> TrainingBudget
    alarm.check(elapsed_s, steps)    -> AlarmStatus
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import torch

from .freezer import (
    CPU_PRESETS,
    GPU_PRESETS,
    CPUPreset,
    GPUPreset,
    cpu_preset,
    gpu_preset,
    probe_vram,
)

#: Generic baseline: ~1 s per step for a 100 M-param model on a
#: mid-tier desktop GPU at fp16 with batch=1 and ctx=1024.  Used
#: by :class:`RadsAlarm` and as a fallback elsewhere.
_BASELINE_PARAMS = 100_000_000
_BASELINE_STEP_SECONDS = 1.0
_BASELINE_GPU_BANDWIDTH_GB_S = 700.0   # ~RTX 3070 / 4070 territory
_BASELINE_CPU_GFLOPS = 200.0           # 8-core modern desktop, fp32
_BASELINE_CONTEXT = 1024
_BASELINE_BATCH = 1


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TrainingBudget:
    """Plan returned by every alarm before training starts."""

    time_seconds: float
    estimated_step_seconds: float
    safety_margin: float
    recommended_steps: int
    notes: str = ""

    @property
    def time_hours(self) -> float:
        return self.time_seconds / 3600.0


@dataclass(frozen=True)
class AlarmStatus:
    """Result of a mid-run :meth:`Alarm.check` call."""

    on_pace: bool
    completed_steps: int
    expected_steps: int
    elapsed_seconds: float
    eta_seconds: float
    message: str


# ---------------------------------------------------------------------------
# Base alarm
# ---------------------------------------------------------------------------

@dataclass
class Alarm:
    """Base class — see the four concrete subclasses below."""

    # 0.52.6: ``time_budget_seconds`` now defaults to 600s (10 min) so
    # ``GasAlarm(cpu_preset="i7_7th_gen")`` and similar short-form
    # constructor calls don't raise ``missing 1 required positional
    # argument`` — picking a hardware preset is the more interesting
    # signal; the time budget is a knob most callers default anyway.
    time_budget_seconds: float = 600.0
    model_params: int = _BASELINE_PARAMS
    context_length: int = _BASELINE_CONTEXT
    batch_size: int = _BASELINE_BATCH
    available_vram_gb: float | None = None
    available_ram_gb: float | None = None
    available_storage_gb: float | None = None
    safety_margin: float = 0.10
    name: str = "Alarm"
    # ------------------------------------------------------------------
    # 0.52.5 + 0.52.6: forgiving kwargs accepted on every alarm.
    # Downstream scripts in the wild type ``cpu_preset="i7-7th-gen"``,
    # ``max_steps=1000``, ``log_every=10``, etc.  The base class accepts
    # all of them so users don't hit ``TypeError: unexpected keyword
    # argument`` on tiers that don't directly use the kwarg (e.g.
    # RadsAlarm ignores the hardware presets and the
    # logging-cadence knobs, but accepting them silently is friendlier
    # than crashing).
    # ------------------------------------------------------------------
    max_steps: int | None = None
    cpu_preset: Any = None  # str (preset name) | CPUPreset | None
    gpu_preset: Any = None  # str (preset name) | GPUPreset | None
    log_every: int | None = None
    save_every: int | None = None
    eval_every: int | None = None

    def __post_init__(self) -> None:
        # Subclasses override and can call ``object.__setattr__`` to set
        # ``self.name``.  The empty body here is required so the
        # dataclass-generated ``__init__`` actually invokes
        # ``__post_init__`` for subclass overrides.
        pass

    # Subclasses override.
    def estimate_step_seconds(self) -> float:
        return _BASELINE_STEP_SECONDS * (self.model_params / _BASELINE_PARAMS) \
            * (self.context_length / _BASELINE_CONTEXT) \
            * (self.batch_size / _BASELINE_BATCH)

    def recommended_steps(self) -> int:
        usable = self.time_budget_seconds * (1 - self.safety_margin)
        rec = max(1, int(usable / max(1e-6, self.estimate_step_seconds())))
        # 0.52.5: hard-cap at user-supplied max_steps when set.
        if self.max_steps is not None and self.max_steps > 0:
            rec = min(rec, int(self.max_steps))
        return rec

    def budget(self) -> TrainingBudget:
        sps = self.estimate_step_seconds()
        return TrainingBudget(
            time_seconds=self.time_budget_seconds,
            estimated_step_seconds=sps,
            safety_margin=self.safety_margin,
            recommended_steps=self.recommended_steps(),
            notes=self._notes(),
        )

    def _notes(self) -> str:
        return f"{self.name}: estimate={self.estimate_step_seconds():.3f}s/step"

    # ------------------------------------------------------------------
    # Storage check — caller-provided storage_gb is compared against a
    # per-step write estimate.  Returns a warning string or "" when
    # nothing's wrong.  Doesn't raise — alarms warn, callers act.
    # ------------------------------------------------------------------

    def storage_warning(self, save_every: int, snapshot_size_gb: float) -> str:
        if self.available_storage_gb is None or save_every <= 0:
            return ""
        n_saves = max(1, self.recommended_steps() // save_every)
        need = n_saves * snapshot_size_gb
        if need > self.available_storage_gb:
            return (
                f"[{self.name}] storage warning: {n_saves} snapshots × "
                f"{snapshot_size_gb:.2f} GB ≈ {need:.1f} GB needed but only "
                f"{self.available_storage_gb:.1f} GB available."
            )
        return ""

    # ------------------------------------------------------------------
    # Mid-run monitor.
    # ------------------------------------------------------------------

    def check(self, elapsed_seconds: float, completed_steps: int) -> AlarmStatus:
        rec = self.recommended_steps()
        sps = self.estimate_step_seconds()
        # Where should we be by now if pace is perfect?
        expected = max(1, int(elapsed_seconds / max(1e-6, sps)))
        on_pace = completed_steps >= expected * 0.9
        eta = max(0.0, (rec - completed_steps) * sps)
        msg = (
            f"[{self.name}] step {completed_steps}/{rec} (~{expected} expected by "
            f"{elapsed_seconds:.0f}s); ETA {eta:.0f}s; "
            f"{'on pace' if on_pace else 'BEHIND pace'}"
        )
        return AlarmStatus(
            on_pace=on_pace, completed_steps=completed_steps,
            expected_steps=expected, elapsed_seconds=elapsed_seconds,
            eta_seconds=eta, message=msg,
        )


# ---------------------------------------------------------------------------
# RadsAlarm — lightest tier
# ---------------------------------------------------------------------------

class RadsAlarm(Alarm):
    """Lightest alarm.  Uses a single per-step constant and scales it
    linearly by params, context, and batch.  Ignores hardware entirely.

    Use this when you literally just need a number — for unit tests,
    for documentation snippets, or for a one-shot training run where
    you'll restart anyway if the estimate is way off.
    """

    def __post_init__(self) -> None:
        # Dataclass-inherit defaults can't override the parent's `name`
        # field directly; set it here instead.
        object.__setattr__(self, "name", "RadsAlarm")


# ---------------------------------------------------------------------------
# Preset name resolution — shared by GasAlarm, AutoAlarm, and the
# public factory helpers.  The ``preset=`` kwarg is the intuitive
# single-string entry point ("give me the alarm for an i7-7700HQ" or
# "give me the alarm for an H100"); it's resolved against GPU_PRESETS
# first (GPU bandwidth is the dominant signal for training throughput)
# and CPU_PRESETS as a fallback.
# ---------------------------------------------------------------------------


def _resolve_preset(
    preset: str | None,
) -> tuple[CPUPreset | None, GPUPreset | None]:
    """Resolve a single ``preset=`` string to ``(cpu, gpu)``.

    GPU matches win over CPU matches.  Raises :class:`ValueError` with
    a useful list of valid names when the string doesn't match any
    preset.
    """
    if preset is None:
        return None, None
    g = gpu_preset(preset)
    if g is not None:
        return None, g
    c = cpu_preset(preset)
    if c is not None:
        return c, None
    raise ValueError(
        f"unknown preset {preset!r}; valid GPU presets: "
        f"{sorted(GPU_PRESETS)}; valid CPU presets: {sorted(CPU_PRESETS)}"
    )


# ---------------------------------------------------------------------------
# GasAlarm — mid tier
# ---------------------------------------------------------------------------

@dataclass
class GasAlarm(Alarm):
    """Mid tier.  Looks up CPU and GPU presets and scales the per-step
    estimate by their throughput vs. the generic baseline.

    Accepts three equivalent ways to name the hardware:

    * ``cpu=CPUPreset(...)``, ``gpu=GPUPreset(...)`` — explicit objects.
    * ``cpu_name=``, ``gpu_name=`` via :meth:`from_names` or the
      :func:`gas_alarm` factory.
    * ``preset="i7-7700hq"`` / ``preset="h100"`` — single-string
      shortcut, resolved against GPU first then CPU.
    """

    cpu: CPUPreset | None = None
    gpu: GPUPreset | None = None
    preset: str | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", "GasAlarm")
        if self.preset is not None:
            c, g = _resolve_preset(self.preset)
            if c is not None and self.cpu is None:
                self.cpu = c
            if g is not None and self.gpu is None:
                self.gpu = g
        # 0.52.5: resolve the forgiving cpu_preset / gpu_preset
        # kwargs (str preset name *or* a pre-built CPUPreset /
        # GPUPreset object) into self.cpu / self.gpu so downstream
        # scripts can write GasAlarm(cpu_preset="i7-7th-gen") without
        # tripping TypeError.
        if self.cpu is None and self.cpu_preset is not None:
            self.cpu = (
                cpu_preset(self.cpu_preset)
                if isinstance(self.cpu_preset, str)
                else self.cpu_preset
            )
        if self.gpu is None and self.gpu_preset is not None:
            self.gpu = (
                gpu_preset(self.gpu_preset)
                if isinstance(self.gpu_preset, str)
                else self.gpu_preset
            )

    @classmethod
    def from_names(
        cls,
        time_budget_seconds: float,
        *,
        cpu_name: str | None = None,
        gpu_name: str | None = None,
        preset: str | None = None,
        **kwargs: Any,
    ) -> GasAlarm:
        return cls(
            time_budget_seconds=time_budget_seconds,
            cpu=cpu_preset(cpu_name) if cpu_name else None,
            gpu=gpu_preset(gpu_name) if gpu_name else None,
            preset=preset,
            **kwargs,
        )

    def estimate_step_seconds(self) -> float:
        # Start from the generic baseline.
        base = super().estimate_step_seconds()
        # GPU bandwidth dominates training throughput.  More bandwidth -> faster.
        if self.gpu is not None:
            base *= _BASELINE_GPU_BANDWIDTH_GB_S / max(1.0, self.gpu.bandwidth_gb_s)
        elif self.cpu is not None:
            # Pure CPU training is much slower.  Use GFLOPS ratio plus a
            # 20× CPU-vs-GPU penalty.
            cpu_gflops = self.cpu.gflops_per_thread * self.cpu.recommended_threads
            base *= 20.0 * (_BASELINE_CPU_GFLOPS / max(1.0, cpu_gflops))
        # VRAM headroom can also force a smaller batch — we don't change
        # batch_size here but we *do* warn via storage_warning later.
        return max(0.001, base)

    def _notes(self) -> str:
        cpu = self.cpu.name if self.cpu else "(no cpu preset)"
        gpu = self.gpu.name if self.gpu else "(no gpu preset)"
        return f"{self.name}: cpu={cpu}, gpu={gpu}"


# ---------------------------------------------------------------------------
# ModernAlarm — measures real step time
# ---------------------------------------------------------------------------

@dataclass
class ModernAlarm(Alarm):
    """Most accurate alarm.  Runs ``warmup_steps`` real training steps
    against a caller-supplied closure, measures wall-clock time, and
    uses the median per-step time as the estimate."""

    warmup_steps: int = 5
    measured_step_seconds: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", "ModernAlarm")

    def warmup(self, step_fn: Callable[[], Any]) -> float:
        """Run ``step_fn()`` ``warmup_steps`` times, record per-step
        wall time, and store the median.  Returns the median."""
        times: list[float] = []
        for _ in range(max(1, self.warmup_steps)):
            t0 = time.perf_counter()
            step_fn()
            times.append(time.perf_counter() - t0)
        times.sort()
        self.measured_step_seconds = times[len(times) // 2]
        return self.measured_step_seconds

    def estimate_step_seconds(self) -> float:
        if self.measured_step_seconds is not None:
            return self.measured_step_seconds
        return super().estimate_step_seconds()

    def _notes(self) -> str:
        if self.measured_step_seconds is None:
            return f"{self.name}: not warmed up yet"
        return f"{self.name}: measured {self.measured_step_seconds:.3f}s/step"


# ---------------------------------------------------------------------------
# AutoAlarm — picks the most detailed alarm available
# ---------------------------------------------------------------------------

@dataclass
class AutoAlarm:
    """Convenience selector.  ``alarm()`` returns whichever concrete
    alarm best matches the inputs available:

    * a ``warmup_step_fn`` callable -> :class:`ModernAlarm` (after
      running the warmup),
    * a ``cpu_name`` or ``gpu_name`` -> :class:`GasAlarm`,
    * otherwise -> :class:`RadsAlarm`.
    """

    # 0.52.6: same default for AutoAlarm as the base Alarm.
    time_budget_seconds: float = 600.0
    model_params: int = _BASELINE_PARAMS
    context_length: int = _BASELINE_CONTEXT
    batch_size: int = _BASELINE_BATCH
    cpu_name: str | None = None
    gpu_name: str | None = None
    warmup_step_fn: Callable[[], Any] | None = None
    warmup_steps: int = 5
    available_vram_gb: float | None = None
    available_ram_gb: float | None = None
    available_storage_gb: float | None = None
    safety_margin: float = 0.10
    # 0.52.5 + 0.52.6: forgiving aliases — accept the same kwargs the
    # base Alarm now accepts, and treat ``cpu_preset`` as a synonym
    # for ``cpu_name`` (and ``gpu_preset`` for ``gpu_name``) when the
    # caller types either form.
    max_steps: int | None = None
    cpu_preset: Any = None
    gpu_preset: Any = None
    log_every: int | None = None
    save_every: int | None = None
    eval_every: int | None = None

    def __post_init__(self) -> None:
        # Treat cpu_preset / gpu_preset as synonyms for cpu_name /
        # gpu_name when only the alias was provided.
        if self.cpu_name is None and isinstance(self.cpu_preset, str):
            self.cpu_name = self.cpu_preset
        if self.gpu_name is None and isinstance(self.gpu_preset, str):
            self.gpu_name = self.gpu_preset

    def _common_kwargs(self) -> dict[str, Any]:
        return {
            "time_budget_seconds": self.time_budget_seconds,
            "model_params": self.model_params,
            "context_length": self.context_length,
            "batch_size": self.batch_size,
            "available_vram_gb": self.available_vram_gb,
            "available_ram_gb": self.available_ram_gb,
            "available_storage_gb": self.available_storage_gb,
            "safety_margin": self.safety_margin,
            # 0.52.5: forward the step cap.
            "max_steps": self.max_steps,
            # 0.52.6: forward the logging-cadence knobs so the picked
            # alarm carries them too (mostly for downstream scripts
            # that read ``alarm.log_every`` etc. directly).
            "log_every": self.log_every,
            "save_every": self.save_every,
            "eval_every": self.eval_every,
        }

    def pick(self) -> Alarm:
        if self.warmup_step_fn is not None:
            ma = ModernAlarm(warmup_steps=self.warmup_steps, **self._common_kwargs())
            ma.warmup(self.warmup_step_fn)
            return ma
        if self.cpu_name or self.gpu_name:
            return GasAlarm(
                cpu=cpu_preset(self.cpu_name) if self.cpu_name else None,
                gpu=gpu_preset(self.gpu_name) if self.gpu_name else None,
                **self._common_kwargs(),
            )
        return RadsAlarm(**self._common_kwargs())


# ---------------------------------------------------------------------------
# Hardware sniffing — best-effort, used by the convenience constructors.
# ---------------------------------------------------------------------------

def detect_gpu_preset() -> GPUPreset | None:
    """Best-effort match of the currently-installed CUDA device against
    :data:`hypernix.freezer.GPU_PRESETS` by substring of the device name."""
    if not torch.cuda.is_available():
        return None
    try:
        name = torch.cuda.get_device_name(0).lower()
    except (RuntimeError, AttributeError):
        return None
    for key, preset in GPU_PRESETS.items():
        canon = preset.name.lower()
        if key in name or canon in name or all(w in name for w in key.split("-")):
            return preset
    return None


def detect_cpu_preset() -> CPUPreset | None:
    """Best-effort match of /proc/cpuinfo's model name against
    :data:`hypernix.freezer.CPU_PRESETS`.  Returns None on Windows /
    macOS (no /proc/cpuinfo) or when no preset matches."""
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("model name"):
                    cpu_name = line.split(":", 1)[1].strip().lower()
                    break
            else:
                return None
    except (FileNotFoundError, OSError):
        return None
    for key, preset in CPU_PRESETS.items():
        if key in cpu_name or preset.name.lower() in cpu_name:
            return preset
    return None


# ---------------------------------------------------------------------------
# Factory shortcuts (mirrors freezer.old_freezer / new_freezer / …)
# ---------------------------------------------------------------------------

def rads_alarm(time_budget_seconds: float, **kw: Any) -> RadsAlarm:
    return RadsAlarm(time_budget_seconds=time_budget_seconds, **kw)


def gas_alarm(
    time_budget_seconds: float,
    *,
    cpu_name: str | None = None,
    gpu_name: str | None = None,
    preset: str | None = None,
    **kw: Any,
) -> GasAlarm:
    """Construct a :class:`GasAlarm`.

    ``cpu_name`` / ``gpu_name`` resolve against ``CPU_PRESETS`` /
    ``GPU_PRESETS`` respectively.  ``preset`` is a one-string alias
    that resolves against GPU first, then CPU — use it when you just
    want "the alarm for my card / chip" without caring which registry
    the name comes from.
    """
    return GasAlarm.from_names(
        time_budget_seconds,
        cpu_name=cpu_name, gpu_name=gpu_name, preset=preset, **kw,
    )


def modern_alarm(
    time_budget_seconds: float,
    step_fn: Callable[[], Any],
    *,
    warmup_steps: int = 5,
    **kw: Any,
) -> ModernAlarm:
    a = ModernAlarm(
        time_budget_seconds=time_budget_seconds,
        warmup_steps=warmup_steps, **kw,
    )
    a.warmup(step_fn)
    return a


def auto_alarm(
    time_budget_seconds: float,
    *,
    cpu_name: str | None = None,
    gpu_name: str | None = None,
    preset: str | None = None,
    warmup_step_fn: Callable[[], Any] | None = None,
    detect_hardware: bool = True,
    **kw: Any,
) -> Alarm:
    """Convenience entry point that returns a concrete alarm.

    When ``detect_hardware=True`` (the default) and no ``cpu_name`` /
    ``gpu_name`` / ``preset`` was supplied, :func:`detect_cpu_preset`
    and :func:`detect_gpu_preset` are consulted first.

    ``preset`` is the one-string shortcut — resolved against GPU
    presets first and CPU presets second.
    """
    if preset is not None:
        c, g = _resolve_preset(preset)
        if c is not None and cpu_name is None:
            for k, v in CPU_PRESETS.items():
                if v is c:
                    cpu_name = k
                    break
        if g is not None and gpu_name is None:
            for k, v in GPU_PRESETS.items():
                if v is g:
                    gpu_name = k
                    break
    if detect_hardware and gpu_name is None:
        det_gpu = detect_gpu_preset()
        if det_gpu is not None:
            # Reverse-look up the short key.
            for k, v in GPU_PRESETS.items():
                if v is det_gpu:
                    gpu_name = k
                    break
    if detect_hardware and cpu_name is None:
        det_cpu = detect_cpu_preset()
        if det_cpu is not None:
            for k, v in CPU_PRESETS.items():
                if v is det_cpu:
                    cpu_name = k
                    break
    if detect_hardware and kw.get("available_vram_gb") is None:
        b = probe_vram()
        if b.total > 0:
            kw["available_vram_gb"] = b.free_gb

    return AutoAlarm(
        time_budget_seconds=time_budget_seconds,
        cpu_name=cpu_name, gpu_name=gpu_name,
        warmup_step_fn=warmup_step_fn,
        **kw,
    ).pick()


# Backwards-compat aliases — the user requested both spellings.
rad_alarm = rads_alarm
radioactive_alarm = rads_alarm
