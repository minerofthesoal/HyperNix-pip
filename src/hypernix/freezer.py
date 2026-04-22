"""freezer — VRAM manager for training and inference.

Three variants sit behind the same interface:

* :class:`OldFreezer`   — tuned for 8–10 GB cards.  Conservative batch
                          and context defaults, bf16 / fp16 preferred,
                          aggressive cache-empty on every step.
* :class:`NewFreezer`   — tuned for 11 GB+ cards.  Larger batches, keeps
                          activations on-device, fp32 by default.
* :class:`FlashFreezer` — wraps any freezer and adds OOM-safety.  On a
                          ``torch.cuda.OutOfMemoryError`` it empties the
                          cache, waits for free VRAM to climb back to a
                          threshold, and retries.  Configurable backoff
                          and optional "slow" mode that halves the batch
                          size every retry so progress continues even on
                          a contested card.

Typical use::

    from hypernix import freezer

    fz = freezer.auto_freezer()            # picks Old or New by VRAM
    fz = freezer.flash_freezer(base=fz)    # add OOM-safety
    bs  = fz.suggest_batch_size(hint=8)
    fz.guard(lambda: model(batch))         # retries on OOM

Everything degrades cleanly on CPU-only systems: ``suggest_batch_size``
returns the hint unchanged, ``guard`` just calls the function, and the
waits are no-ops.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import torch

T = TypeVar("T")


# ---------------------------------------------------------------------------
# VRAM probing
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VRAMBudget:
    """Snapshot of device memory at one point in time.

    All values are in bytes.  ``free`` and ``total`` are 0 on CPU-only
    systems so callers can do ``if budget.total:`` as a quick gate.
    """
    device: str
    total: int = 0
    free: int = 0

    @property
    def total_gb(self) -> float:
        return self.total / (1024 ** 3)

    @property
    def free_gb(self) -> float:
        return self.free / (1024 ** 3)

    @property
    def used_gb(self) -> float:
        return (self.total - self.free) / (1024 ** 3)


def probe_vram(device_index: int = 0) -> VRAMBudget:
    """Return current VRAM state for the given CUDA device, or a zeroed
    budget on CPU-only systems."""
    if not torch.cuda.is_available():
        return VRAMBudget(device="cpu")
    try:
        free, total = torch.cuda.mem_get_info(device_index)
    except (RuntimeError, AttributeError):
        # Older torch or driver without mem_get_info — fall back to
        # properties.total_memory and leave free=0 so callers treat the
        # device as "don't know".
        props = torch.cuda.get_device_properties(device_index)
        return VRAMBudget(device=f"cuda:{device_index}", total=props.total_memory, free=0)
    return VRAMBudget(device=f"cuda:{device_index}", total=total, free=free)


# ---------------------------------------------------------------------------
# Compute capability (Pascal / Ampere / Hopper / …) detection
# ---------------------------------------------------------------------------

#: Compute capability for Pascal consumer cards (GTX 1060/1070/1080/Ti, Titan X/Xp).
PASCAL_CC: tuple[int, int] = (6, 1)

#: Compute capabilities that do NOT have native bf16 — Volta (7,0), Turing
#: (7,5), Pascal (6,x) and older. Ampere (8,0+) introduced bf16. bf16 on
#: these is either unsupported or emulated in software.
_NO_NATIVE_BF16 = frozenset({(6, 0), (6, 1), (6, 2), (7, 0), (7, 5)})


def compute_capability(device_index: int = 0) -> tuple[int, int] | None:
    """Return ``(major, minor)`` for a CUDA device, or ``None`` on CPU-only hosts."""
    if not torch.cuda.is_available():
        return None
    try:
        return torch.cuda.get_device_capability(device_index)
    except (RuntimeError, AttributeError):
        return None


def is_pascal(device_index: int = 0) -> bool:
    """True if the device is a Pascal chip (sm_60, sm_61, sm_62)."""
    cc = compute_capability(device_index)
    return cc is not None and cc[0] == 6


def pascal_safe_dtype(device_index: int = 0) -> torch.dtype:
    """Pick a dtype that trains stably on the detected device.

    * ``torch.bfloat16`` — Ampere (sm_80) and newer.
    * ``torch.float16``  — Pascal / Volta / Turing (sm_6x / 7x).
    * ``torch.float32``  — CPU-only hosts (PyTorch CPU fp16 matmul is
                           emulated and overflows quickly in training).

    bf16 on Pascal is either unsupported or falls back to a slow software
    path; fp16 has native tensor-core-free fast-math on Pascal (sm_61).
    """
    cc = compute_capability(device_index)
    if cc is None:
        # No CUDA device — fp16 on CPU is unstable for training.
        return torch.float32
    if cc in _NO_NATIVE_BF16 or cc < (8, 0):
        return torch.float16
    if not torch.cuda.is_bf16_supported():
        return torch.float16
    return torch.bfloat16


def pascal_mode_hints(device_index: int = 0) -> dict[str, object]:
    """Return a dict of recommended settings for Pascal (sm_61) GPUs.

    Nothing here is *required* — it's a cheat sheet for callers building
    their own training loop.  Keys:

    ``dtype``            fp16 (not bf16 — Pascal has no native bf16).
    ``use_sdpa``         False; the PyTorch 2 fused SDPA kernels assume
                         Ampere+ tensor cores.
    ``use_compile``      False; ``torch.compile`` breaks often on sm_61
                         due to Triton kernel assumptions.
    ``tf32``             False; Pascal has no TF32 support.
    ``matmul_precision`` "highest" — the TF32 knob is inert anyway.
    ``install_hint``     One-line pip command for the CUDA 11.8 wheel,
                         which is the last official PyTorch line still
                         compiled for sm_61.
    """
    return {
        "dtype": torch.float16,
        "use_sdpa": False,
        "use_compile": False,
        "tf32": False,
        "matmul_precision": "highest",
        "install_hint": (
            "pip install --index-url "
            "https://download.pytorch.org/whl/cu118 torch"
        ),
    }


# ---------------------------------------------------------------------------
# Base freezer
# ---------------------------------------------------------------------------

class Freezer:
    """Base VRAM manager.  Concrete subclasses set the tuning knobs."""

    #: Preferred torch dtype for forward/backward.
    preferred_dtype: torch.dtype = torch.float32
    #: Base batch size for a training step.
    base_batch_size: int = 2
    #: Base context length.
    base_context_length: int = 1024
    #: If True, call ``torch.cuda.empty_cache`` after every training step.
    empty_cache_each_step: bool = False
    #: Human-readable label used in logs.
    name: str = "Freezer"

    def budget(self) -> VRAMBudget:
        return probe_vram()

    def suggest_batch_size(self, hint: int | None = None) -> int:
        """Return a batch size appropriate for this freezer.

        If ``hint`` is given it's capped at ``self.base_batch_size`` for
        conservative freezers and returned unchanged otherwise.
        """
        if hint is None:
            return self.base_batch_size
        return min(hint, self.base_batch_size) if self._caps_hint else hint

    _caps_hint: bool = False  # Old caps; New doesn't.

    def suggest_context_length(self, hint: int | None = None) -> int:
        if hint is None:
            return self.base_context_length
        return min(hint, self.base_context_length) if self._caps_hint else hint

    def guard(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Call ``fn(*args, **kwargs)``.  Base implementation is a plain call;
        :class:`FlashFreezer` overrides this with OOM-safe retry."""
        return fn(*args, **kwargs)

    def __repr__(self) -> str:
        b = self.budget()
        return (
            f"<{self.name} device={b.device} total={b.total_gb:.1f}GB "
            f"free={b.free_gb:.1f}GB bs={self.base_batch_size} "
            f"ctx={self.base_context_length}>"
        )


# ---------------------------------------------------------------------------
# OldFreezer: 8–10 GB cards
# ---------------------------------------------------------------------------

class OldFreezer(Freezer):
    """For 8–10 GB GPUs (GTX 1080, RTX 2060/2070, RTX 3060-8GB, …).

    Picks dtype from :func:`pascal_safe_dtype`, so on a GTX 1080 (sm_61)
    you get native fp16 rather than emulated bf16.
    """

    preferred_dtype = pascal_safe_dtype()
    base_batch_size = 1
    base_context_length = 512
    empty_cache_each_step = True
    name = "OldFreezer"
    _caps_hint = True


# ---------------------------------------------------------------------------
# NewFreezer: 11 GB+
# ---------------------------------------------------------------------------

class NewFreezer(Freezer):
    """For 11 GB+ GPUs (RTX 2080 Ti, RTX 3080 12GB, 3090, 4090, H100, …)."""

    preferred_dtype = torch.float32
    base_batch_size = 8
    base_context_length = 2048
    empty_cache_each_step = False
    name = "NewFreezer"
    _caps_hint = False  # hint wins on big cards


# ---------------------------------------------------------------------------
# FlashFreezer: wraps a base freezer with OOM-safe retry
# ---------------------------------------------------------------------------

class FlashFreezer(Freezer):
    """Adaptive wrapper that slows or pauses to avoid OOM.

    On every ``guard(fn)`` call it runs ``fn``.  If a
    ``torch.cuda.OutOfMemoryError`` fires:

    1. empty the allocator cache,
    2. wait until ``probe_vram().free_gb`` climbs back above
       ``min_free_gb`` (or a fixed backoff timeout, whichever happens
       first),
    3. retry — up to ``max_retries`` times.

    If ``slow`` is True, each retry halves the effective batch size via
    the ``current_batch_size`` attribute, which your training loop should
    consult in place of a hard-coded batch size.  Progress still happens;
    it's just slower.
    """

    name = "FlashFreezer"

    def __init__(
        self,
        base: Freezer | None = None,
        *,
        max_retries: int = 5,
        backoff_s: float = 2.0,
        min_free_gb: float = 0.5,
        slow: bool = True,
    ) -> None:
        self.base = base or auto_freezer()
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        self.min_free_gb = min_free_gb
        self.slow = slow
        # Mirror the base's tuning so suggest_* work transparently.
        self.preferred_dtype = self.base.preferred_dtype
        self.base_batch_size = self.base.base_batch_size
        self.base_context_length = self.base.base_context_length
        self.empty_cache_each_step = self.base.empty_cache_each_step
        self._caps_hint = self.base._caps_hint
        self.current_batch_size = self.base_batch_size

    def wait_for(self, min_free_gb: float | None = None, timeout_s: float | None = None) -> bool:
        """Block until ``probe_vram().free_gb >= min_free_gb`` or timeout.

        Returns True if the threshold was reached, False on timeout.
        CPU-only systems return True immediately.
        """
        need = self.min_free_gb if min_free_gb is None else min_free_gb
        if not torch.cuda.is_available():
            return True
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        while True:
            if probe_vram().free_gb >= need:
                return True
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(min(self.backoff_s, 1.0))

    def guard(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run ``fn``; on OOM empty the cache, wait, and retry."""
        last_exc: BaseException | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return fn(*args, **kwargs)
            except torch.cuda.OutOfMemoryError as exc:
                last_exc = exc
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                if self.slow and self.current_batch_size > 1:
                    self.current_batch_size = max(1, self.current_batch_size // 2)
                sleep_for = self.backoff_s * (2 ** attempt)
                time.sleep(min(sleep_for, 60.0))
                self.wait_for(self.min_free_gb, timeout_s=sleep_for)
        assert last_exc is not None
        raise last_exc


# ---------------------------------------------------------------------------
# Auto-picker
# ---------------------------------------------------------------------------

def auto_freezer(threshold_gb: float = 11.0) -> Freezer:
    """Return :class:`NewFreezer` if total VRAM ≥ ``threshold_gb``, else
    :class:`OldFreezer`.  On a CPU-only host returns :class:`OldFreezer`
    (its small defaults won't hurt; they just produce tiny batches)."""
    b = probe_vram()
    if b.total_gb >= threshold_gb:
        return NewFreezer()
    return OldFreezer()


def old_freezer() -> OldFreezer:
    return OldFreezer()


def new_freezer() -> NewFreezer:
    return NewFreezer()


def flash_freezer(**kwargs: Any) -> FlashFreezer:
    return FlashFreezer(**kwargs)


# ---------------------------------------------------------------------------
# CPU presets
# ---------------------------------------------------------------------------
# Per-CPU tuning hints used by the smoke alarms and by callers that
# want sane BLAS / OpenMP defaults for a known chip.  Throughput numbers
# are deliberately conservative — they're rough heuristics for
# step-time estimation, not benchmark results.

@dataclass(frozen=True)
class CPUPreset:
    name: str
    cores: int
    threads: int
    base_clock_ghz: float
    avx_levels: tuple[str, ...]
    recommended_threads: int
    #: Approximate fp32 GFLOPS per thread for the kernels hypernix
    #: cares about (matmul-heavy AdamW training).  Multiply by
    #: ``recommended_threads`` for a whole-CPU figure.
    gflops_per_thread: float
    notes: str = ""


def _cpu(name, cores, threads, ghz, avx, threads_rec, gflops, notes=""):
    return CPUPreset(
        name=name, cores=cores, threads=threads, base_clock_ghz=ghz,
        avx_levels=tuple(avx), recommended_threads=threads_rec,
        gflops_per_thread=gflops, notes=notes,
    )


#: Lookup table — short name -> :class:`CPUPreset`.  Names are
#: lowercased and ``-`` / ``_`` are equivalent at lookup time.
CPU_PRESETS: dict[str, CPUPreset] = {
    # ---- Intel 7th gen (Kaby Lake) ----
    "i7-7660u": _cpu("Intel Core i7-7660U", 2, 4, 2.5, ["AVX", "AVX2"], 2,
                     14.0, "15W ULV ultrabook (e.g. 13\" MBP, XPS 13)"),
    "i7-7700hq": _cpu("Intel Core i7-7700HQ", 4, 8, 2.8, ["AVX", "AVX2"], 4,
                      18.0, "45W mobile gaming/workstation"),
    "i7-7700k": _cpu("Intel Core i7-7700K", 4, 8, 4.2, ["AVX", "AVX2"], 4,
                     24.0, "91W desktop"),
    # ---- 11th gen ----
    "i7-11700k": _cpu("Intel Core i7-11700K", 8, 16, 3.6, ["AVX2", "AVX-512"], 8,
                      30.0, "Rocket Lake desktop, AVX-512"),
    "i7-11800h": _cpu("Intel Core i7-11800H", 8, 16, 2.3, ["AVX2"], 8,
                      24.0, "Tiger Lake-H mobile"),
    # ---- 12th gen (Alder Lake hybrid: P + E cores) ----
    "i7-12700k": _cpu("Intel Core i7-12700K", 12, 20, 3.6, ["AVX2"], 8,
                      30.0, "8 P-cores + 4 E-cores"),
    "i7-12700h": _cpu("Intel Core i7-12700H", 14, 20, 2.3, ["AVX2"], 10,
                      26.0, "6 P + 8 E mobile"),
    # ---- 13th gen ----
    "i7-13700k": _cpu("Intel Core i7-13700K", 16, 24, 3.4, ["AVX2"], 12,
                      32.0, "8 P + 8 E desktop"),
    "i7-13700h": _cpu("Intel Core i7-13700H", 14, 20, 2.4, ["AVX2"], 10,
                      28.0, "6 P + 8 E mobile"),
    # ---- 14th gen (Raptor Lake-R) ----
    "i7-14700k": _cpu("Intel Core i7-14700K", 20, 28, 3.4, ["AVX2"], 14,
                      34.0, "8 P + 12 E desktop"),
    "i7-14700hx": _cpu("Intel Core i7-14700HX", 20, 28, 2.1, ["AVX2"], 14,
                       30.0, "8 P + 12 E mobile-HX"),
    # ---- Core Ultra Series 1 (Meteor Lake, last-gen) ----
    "core-ultra-7-155h": _cpu("Intel Core Ultra 7 155H", 16, 22, 1.4,
                              ["AVX2", "AVX-VNNI"], 12, 28.0,
                              "Meteor Lake, 6P + 8E + 2LP-E + NPU"),
    "core-ultra-7-165h": _cpu("Intel Core Ultra 7 165H", 16, 22, 1.4,
                              ["AVX2", "AVX-VNNI"], 12, 30.0,
                              "Meteor Lake, refresh of 155H"),
    "core-ultra-7-258v": _cpu("Intel Core Ultra 7 258V", 8, 8, 2.2,
                              ["AVX2", "AVX-VNNI"], 6, 24.0,
                              "Lunar Lake, 4P + 4LP-E"),
    # ---- Core Ultra Series 2 (Arrow Lake, newest gen) ----
    "core-ultra-7-265k": _cpu("Intel Core Ultra 7 265K", 20, 20, 3.9,
                              ["AVX2", "AVX-VNNI", "AVX10"], 14, 36.0,
                              "Arrow Lake desktop, no SMT"),
    "core-ultra-9-285k": _cpu("Intel Core Ultra 9 285K", 24, 24, 3.7,
                              ["AVX2", "AVX-VNNI", "AVX10"], 16, 38.0,
                              "Arrow Lake top SKU, no SMT"),
}


def _cpu_key(name: str) -> str:
    return name.lower().replace("_", "-").replace(" ", "-")


def cpu_preset(name: str) -> CPUPreset | None:
    """Look up a CPU preset by short name (case- and dash-insensitive)."""
    return CPU_PRESETS.get(_cpu_key(name))


# ---------------------------------------------------------------------------
# GPU presets
# ---------------------------------------------------------------------------
# Per-GPU tuning hints used by the smoke alarms and by callers that
# want a known-good starting point without probing torch.cuda.

@dataclass(frozen=True)
class GPUPreset:
    name: str
    vram_gb: float
    compute_capability: tuple[int, int]
    preferred_dtype: torch.dtype
    #: Approximate memory bandwidth in GB/s — the dominant signal for
    #: training throughput on transformer workloads.
    bandwidth_gb_s: float
    #: "Old" or "New" — which freezer class fits this card.  Anything
    #: with < 11 GB VRAM lands on Old; the Pascal/Volta/Turing fp16-only
    #: cards stay on Old even when they have 12 GB.
    freezer_class: str
    notes: str = ""


def _gpu(name, vram, cc, dtype, bw, fz_class, notes=""):
    return GPUPreset(
        name=name, vram_gb=vram, compute_capability=cc, preferred_dtype=dtype,
        bandwidth_gb_s=bw, freezer_class=fz_class, notes=notes,
    )


GPU_PRESETS: dict[str, GPUPreset] = {
    # ---- Hopper (sm_90) data-center ----
    "h100": _gpu("NVIDIA H100 80GB", 80.0, (9, 0), torch.bfloat16, 3350.0, "New",
                 "PCIe / SXM5 80GB"),
    "h100-94": _gpu("NVIDIA H100 NVL 94GB", 94.0, (9, 0), torch.bfloat16, 3900.0, "New",
                    "NVL variant, 94GB HBM3"),
    "h200": _gpu("NVIDIA H200 141GB", 141.0, (9, 0), torch.bfloat16, 4800.0, "New",
                 "HBM3e, 141GB"),
    # ---- Ampere workstation (sm_86) ----
    "rtx-a4500": _gpu("NVIDIA RTX A4500", 20.0, (8, 6), torch.bfloat16, 640.0, "New",
                      "Ampere workstation"),
    "rtx-a5000": _gpu("NVIDIA RTX A5000", 24.0, (8, 6), torch.bfloat16, 768.0, "New", ""),
    "rtx-a5500": _gpu("NVIDIA RTX A5500", 24.0, (8, 6), torch.bfloat16, 768.0, "New", ""),
    "rtx-a6000": _gpu("NVIDIA RTX A6000", 48.0, (8, 6), torch.bfloat16, 768.0, "New",
                      "Ampere workstation flagship"),
    # ---- RTX PRO (Ada Lovelace, sm_89) ----
    "rtx-pro-4000-ada": _gpu("NVIDIA RTX PRO 4000 Ada", 20.0, (8, 9),
                             torch.bfloat16, 360.0, "New", ""),
    "rtx-pro-5000-ada": _gpu("NVIDIA RTX PRO 5000 Ada", 32.0, (8, 9),
                             torch.bfloat16, 576.0, "New", ""),
    "rtx-pro-6000-ada": _gpu("NVIDIA RTX PRO 6000 Ada", 48.0, (8, 9),
                             torch.bfloat16, 960.0, "New",
                             "Ada workstation flagship"),
    # ---- RTX PRO Blackwell (sm_120) ----
    "rtx-pro-6000-blackwell": _gpu("NVIDIA RTX PRO 6000 Blackwell", 96.0, (12, 0),
                                   torch.bfloat16, 1792.0, "New",
                                   "Blackwell workstation, 96GB"),
    # ---- Ada Lovelace consumer (sm_89) ----
    "rtx-4070-ti-super": _gpu("NVIDIA GeForce RTX 4070 Ti Super", 16.0, (8, 9),
                              torch.bfloat16, 672.0, "New",
                              "16GB GDDR6X"),
    "rtx-4080-super": _gpu("NVIDIA GeForce RTX 4080 Super", 16.0, (8, 9),
                           torch.bfloat16, 736.0, "New", ""),
    # ---- Turing consumer (sm_75 — no native bf16) ----
    "gtx-1660-ti": _gpu("NVIDIA GeForce GTX 1660 Ti", 6.0, (7, 5),
                        torch.float16, 288.0, "Old",
                        "Turing without RT cores; 6GB caps batch hard"),
    "rtx-2080": _gpu("NVIDIA GeForce RTX 2080", 8.0, (7, 5),
                     torch.float16, 448.0, "Old", ""),
    "rtx-2080-super": _gpu("NVIDIA GeForce RTX 2080 Super", 8.0, (7, 5),
                           torch.float16, 496.0, "Old", ""),
    "rtx-2080-ti": _gpu("NVIDIA GeForce RTX 2080 Ti", 11.0, (7, 5),
                        torch.float16, 616.0, "New",
                        "11GB lands on the New side of the 11GB threshold"),
    # ---- Ampere consumer (sm_86) ----
    "rtx-3080-ti": _gpu("NVIDIA GeForce RTX 3080 Ti", 12.0, (8, 6),
                        torch.bfloat16, 912.0, "New",
                        "12GB GDDR6X; bf16 native"),
    # ---- Pascal (kept for the GTX 1080 playbook) ----
    "gtx-1080": _gpu("NVIDIA GeForce GTX 1080", 8.0, (6, 1),
                     torch.float16, 320.0, "Old",
                     "Pascal sm_61 — see wiki/Pascal.md"),
    "gtx-1080-ti": _gpu("NVIDIA GeForce GTX 1080 Ti", 11.0, (6, 1),
                        torch.float16, 484.0, "New",
                        "Pascal sm_61, 11GB"),
}


def _gpu_key(name: str) -> str:
    return name.lower().replace("_", "-").replace(" ", "-")


def gpu_preset(name: str) -> GPUPreset | None:
    """Look up a GPU preset by short name (case- and dash-insensitive)."""
    return GPU_PRESETS.get(_gpu_key(name))
