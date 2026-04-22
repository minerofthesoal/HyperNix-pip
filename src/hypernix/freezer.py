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
