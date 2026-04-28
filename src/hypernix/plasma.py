"""plasma — quick GPU benchmark for sharper ETAs.

A short fixed-shape forward + backward + step is the most
informative thing you can do in two seconds to predict how a
real training run will pace itself.  ``plasma`` runs that
benchmark and returns a :class:`PlasmaResult` with:

* ``step_ms``                — median step time (float).
* ``tokens_per_sec``         — throughput at the benchmark
                                shape.
* ``calibration_factor``     — multiplier you apply to a
                                :mod:`hypernix.smoke_alarm`
                                baseline ETA to make it match
                                your actual hardware.

The benchmark itself is a deliberately small Llama-shape
``forward -> loss -> backward -> step`` loop sized to fit on a
laptop GPU (and to run on CPU in a couple of seconds).  Override
the dimensions via :class:`PlasmaConfig` for bigger / smaller
runs.

Quick use::

    from hypernix.plasma import quick_benchmark, calibrate_alarm
    from hypernix.smoke_alarm import GasAlarm

    result = quick_benchmark()
    print(result.summary())

    alarm = GasAlarm(cpu_preset="i7-7700hq")
    print("raw ETA:", alarm.estimate_step_seconds())
    calibrate_alarm(alarm, result)
    print("calibrated ETA:", alarm.estimate_step_seconds())

The calibration is simple multiplication — we don't try to
re-derive the alarm's params; we just scale the
``estimate_step_seconds`` it returns so further calls report a
realistic value.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Any

import torch
import torch.nn as nn


@dataclass(frozen=True)
class PlasmaConfig:
    """Shape of the throwaway model used by the benchmark."""

    hidden_size: int = 256
    num_layers: int = 2
    seq_length: int = 64
    batch_size: int = 4
    vocab_size: int = 1024
    warmup_steps: int = 2
    measure_steps: int = 6
    dtype: str = "float32"


@dataclass
class PlasmaResult:
    config: PlasmaConfig
    device: str
    dtype: str
    step_ms: float
    tokens_per_sec: float
    samples_ms: list[float] = field(default_factory=list)
    calibration_factor: float = 1.0
    notes: str = ""

    def summary(self) -> str:
        return (
            f"plasma[{self.device}/{self.dtype}] step={self.step_ms:.1f} ms  "
            f"throughput={self.tokens_per_sec:,.0f} tok/s  "
            f"calibration_factor={self.calibration_factor:.3f}"
        )


# ---------------------------------------------------------------------------
# Throwaway model — small enough to run on CPU, big enough to be
# representative of a real training step.
# ---------------------------------------------------------------------------

class _PlasmaBlock(nn.Module):
    def __init__(self, h: int) -> None:
        super().__init__()
        self.attn_q = nn.Linear(h, h, bias=False)
        self.attn_k = nn.Linear(h, h, bias=False)
        self.attn_v = nn.Linear(h, h, bias=False)
        self.attn_out = nn.Linear(h, h, bias=False)
        self.mlp_up = nn.Linear(h, 4 * h, bias=False)
        self.mlp_down = nn.Linear(4 * h, h, bias=False)
        self.norm1 = nn.LayerNorm(h)
        self.norm2 = nn.LayerNorm(h)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        n = self.norm1(x)
        q, k, v = self.attn_q(n), self.attn_k(n), self.attn_v(n)
        # Scaled dot-product attention (no causal mask — a benchmark,
        # not a real LM).
        scores = torch.matmul(q, k.transpose(-2, -1)) / (q.shape[-1] ** 0.5)
        attn = torch.softmax(scores, dim=-1)
        attended = torch.matmul(attn, v)
        x = x + self.attn_out(attended)
        n = self.norm2(x)
        x = x + self.mlp_down(torch.nn.functional.silu(self.mlp_up(n)))
        return x


class _PlasmaModel(nn.Module):
    def __init__(self, cfg: PlasmaConfig) -> None:
        super().__init__()
        self.embed = nn.Embedding(cfg.vocab_size, cfg.hidden_size)
        self.blocks = nn.ModuleList(
            [_PlasmaBlock(cfg.hidden_size) for _ in range(cfg.num_layers)],
        )
        self.head = nn.Linear(cfg.hidden_size, cfg.vocab_size, bias=False)

    def forward(self, ids: torch.Tensor) -> torch.Tensor:
        x = self.embed(ids)
        for blk in self.blocks:
            x = blk(x)
        return self.head(x)


# ---------------------------------------------------------------------------
# Benchmark loop
# ---------------------------------------------------------------------------

def _torch_dtype(name: str) -> torch.dtype:
    return {
        "float32": torch.float32,
        "fp32": torch.float32,
        "float16": torch.float16,
        "fp16": torch.float16,
        "bfloat16": torch.bfloat16,
        "bf16": torch.bfloat16,
    }.get(name, torch.float32)


def quick_benchmark(
    config: PlasmaConfig | None = None,
    *,
    device: str | torch.device | None = None,
    seed: int = 0,
) -> PlasmaResult:
    """Run the benchmark.  Returns a :class:`PlasmaResult`."""
    cfg = config or PlasmaConfig()
    dev = torch.device(
        device or ("cuda" if torch.cuda.is_available() else "cpu"),
    )
    dtype = _torch_dtype(cfg.dtype)
    torch.manual_seed(seed)

    # Casting fp16 model + fp16 cross-entropy is brittle — keep weights
    # in fp32 on CPU, allow autocast on CUDA.
    use_autocast = dev.type == "cuda" and dtype != torch.float32

    model = _PlasmaModel(cfg).to(dev)
    if not use_autocast:
        model = model.to(dtype)
    model.train()
    opt = torch.optim.AdamW(model.parameters(), lr=3e-4)
    ce = nn.CrossEntropyLoss()
    ids = torch.randint(
        0, cfg.vocab_size, (cfg.batch_size, cfg.seq_length),
        device=dev, dtype=torch.long,
    )
    targets = torch.randint(
        0, cfg.vocab_size, (cfg.batch_size, cfg.seq_length),
        device=dev, dtype=torch.long,
    )

    def _step() -> None:
        opt.zero_grad(set_to_none=True)
        if use_autocast:
            with torch.autocast(device_type="cuda", dtype=dtype):
                logits = model(ids)
                loss = ce(logits.reshape(-1, cfg.vocab_size), targets.reshape(-1))
        else:
            logits = model(ids)
            loss = ce(logits.reshape(-1, cfg.vocab_size), targets.reshape(-1))
        loss.backward()
        opt.step()

    # Warmup
    for _ in range(max(0, cfg.warmup_steps)):
        _step()
        if dev.type == "cuda":
            torch.cuda.synchronize()

    # Measure
    samples_ms: list[float] = []
    for _ in range(max(1, cfg.measure_steps)):
        t0 = time.perf_counter()
        _step()
        if dev.type == "cuda":
            torch.cuda.synchronize()
        samples_ms.append(1000.0 * (time.perf_counter() - t0))

    step_ms = statistics.median(samples_ms)
    tokens = cfg.batch_size * cfg.seq_length
    tps = tokens / (step_ms / 1000.0) if step_ms > 0 else 0.0

    # Calibration: 256-hidden / 2-layer / 64-seq / 4-batch on CPU
    # historically clocks ~50ms per step.  Treat that as 1.0; faster
    # → lower factor.
    BASELINE_MS = 50.0
    factor = step_ms / BASELINE_MS

    return PlasmaResult(
        config=cfg, device=str(dev), dtype=str(dtype).split(".")[-1],
        step_ms=step_ms, tokens_per_sec=tps,
        samples_ms=samples_ms, calibration_factor=factor,
        notes=f"warmup={cfg.warmup_steps} measure={cfg.measure_steps}",
    )


# ---------------------------------------------------------------------------
# Calibrate a smoke_alarm using the result
# ---------------------------------------------------------------------------

def calibrate_alarm(alarm: Any, result: PlasmaResult) -> Any:
    """Rebind ``alarm.estimate_step_seconds`` so its ETA reflects
    real measured throughput.  Returns the same alarm so callers
    can chain.

    Implementation note: we don't subclass — we wrap the bound
    method, since the smoke_alarm tiers are dataclasses and
    monkey-patching the instance is the least invasive option.

    Patch (0.61.1): re-calibrating the same alarm now *replaces*
    the previous wrapper instead of compounding factors.  The
    pristine bound method is squirrelled away on
    ``alarm._plasma_original`` the first time around; subsequent
    calls reset to that baseline before re-wrapping.
    """
    if not hasattr(alarm, "estimate_step_seconds"):
        raise TypeError("calibrate_alarm: alarm has no estimate_step_seconds")
    original = getattr(alarm, "_plasma_original", None)
    if original is None:
        original = alarm.estimate_step_seconds  # bound method
        alarm._plasma_original = original  # type: ignore[attr-defined]
    factor = max(0.001, result.calibration_factor)

    def calibrated() -> float:
        return float(original()) * factor

    alarm.estimate_step_seconds = calibrated  # type: ignore[assignment]
    return alarm


def reset_calibration(alarm: Any) -> Any:
    """Undo a previous :func:`calibrate_alarm` so
    ``alarm.estimate_step_seconds`` returns the pristine baseline
    again.  No-op on alarms that were never calibrated."""
    original = getattr(alarm, "_plasma_original", None)
    if original is not None:
        alarm.estimate_step_seconds = original  # type: ignore[assignment]
        delattr(alarm, "_plasma_original")
    return alarm


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def plasma(
    config: PlasmaConfig | None = None,
    *,
    device: str | torch.device | None = None,
    seed: int = 0,
) -> PlasmaResult:
    """Alias for :func:`quick_benchmark`."""
    return quick_benchmark(config=config, device=device, seed=seed)


__all__ = [
    "PlasmaConfig",
    "PlasmaResult",
    "calibrate_alarm",
    "plasma",
    "quick_benchmark",
    "reset_calibration",
]
