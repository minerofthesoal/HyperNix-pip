"""vram — VRAM optimizations that are additive, opt-in, and measurable.

:mod:`hypernix.system.freezer` answers "how big a batch fits?". This
module answers the next question: "how do I make more of it fit without
changing what the model learns?"

Five techniques, each independently useful and each with an honest
statement of what it costs:

======================  =================================  ==================
Technique               Frees                              Costs
======================  =================================  ==================
:func:`configure_allocator`   fragmentation, often 5-20% of    nothing
                              reserved-but-unusable VRAM
:func:`checkpoint_blocks`     most activation memory           ~30% more compute
:func:`fuse_optimizer_into_backward`  one full copy of the     no grad clipping,
                              gradients                        no accumulation
:func:`offload_optimizer_state`  optimizer state, for the      a host round-trip
                              duration of a block              per entry/exit
:func:`measure_peak`          nothing — it tells you           nothing
                              whether the others worked
======================  =================================  ==================

Nothing here is applied for you. Each function is explicit, reversible,
and refuses rather than silently degrading: an option that cannot take
effect says so instead of returning success. That matters more here than
usual, because every one of these is invisible when it silently fails —
you get the same loss curve and the same OOM, and no way to tell which.

Importing this module does **not** import ``torch``. That is deliberate
rather than convenient: :func:`configure_allocator` has to run before the
CUDA allocator initializes to have any effect at all, so it must be
callable from a launcher that has not yet imported torch.

Typical use::

    from hypernix.system import vram

    vram.configure_allocator()             # before torch touches CUDA

    ...

    handle = vram.checkpoint_blocks(model)  # ~30% slower, much smaller
    with vram.measure_peak() as peak:
        train(...)
    print(peak.report())
    handle.disable()                        # back to where you started
"""
from __future__ import annotations

import os
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "AllocatorReport",
    "CheckpointHandle",
    "FusedOptimizerHandle",
    "PeakMemory",
    "Recommendation",
    "configure_allocator",
    "checkpoint_blocks",
    "fuse_optimizer_into_backward",
    "offload_optimizer_state",
    "measure_peak",
    "recommend",
    "release_cache",
]

#: The environment variable the CUDA caching allocator reads at init.
ALLOC_CONF_VAR = "PYTORCH_CUDA_ALLOC_CONF"

#: ``expandable_segments`` landed in torch 2.1. Below that the option is
#: ignored, which is the silent failure this module exists to avoid.
_EXPANDABLE_MIN_TORCH = (2, 1)

#: ``Tensor.register_post_accumulate_grad_hook``, likewise.
_POST_ACCUM_MIN_TORCH = (2, 1)


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------

def _torch_version() -> tuple[int, int] | None:
    """``(major, minor)``, or None when torch is not importable.

    Parsed from the leading numeric components, since a released torch
    version can be ``2.4.1+cu121`` and a nightly can be ``2.6.0.dev2025…``.
    """
    try:
        import torch
    except Exception:
        return None
    parts = str(torch.__version__).split("+")[0].split(".")
    try:
        return (int(parts[0]), int(parts[1]))
    except (IndexError, ValueError):  # pragma: no cover - unparseable
        return None


def _parse_alloc_conf(raw: str) -> dict[str, str]:
    """``"a:1,b:2"`` → ``{"a": "1", "b": "2"}``.

    Malformed fragments are dropped rather than raising: this parses an
    environment variable a user may have set by hand, and refusing to
    start over a stray comma would be worse than ignoring it.
    """
    out: dict[str, str] = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        key, _, value = chunk.partition(":")
        key, value = key.strip(), value.strip()
        if key and value:
            out[key] = value
    return out


def _format_alloc_conf(conf: dict[str, str]) -> str:
    return ",".join(f"{k}:{v}" for k, v in conf.items())


def _human(n_bytes: float) -> str:
    """Bytes as the unit a person would have used."""
    step = 1024.0
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n_bytes) < step or unit == "TiB":
            return f"{n_bytes:.2f} {unit}" if unit != "B" else f"{n_bytes:.0f} B"
        n_bytes /= step
    return f"{n_bytes:.2f} TiB"  # pragma: no cover - unreachable


# ---------------------------------------------------------------------------
# 1. Allocator configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AllocatorReport:
    """What :func:`configure_allocator` actually managed to do.

    ``applied`` is the only field worth branching on. The rest exist so a
    caller can log *why* — an allocator setting that did not take effect
    is invisible at runtime, and "it made no difference" is a much harder
    thing to debug than "it was refused, here is the reason".
    """

    applied: bool
    value: str
    previous: str
    reason: str = ""

    def report(self) -> str:
        if self.applied:
            return f"{ALLOC_CONF_VAR}={self.value}"
        return f"{ALLOC_CONF_VAR} unchanged ({self.reason})"


def configure_allocator(
    *,
    expandable_segments: bool = True,
    garbage_collection_threshold: float | None = None,
    max_split_size_mb: int | None = None,
    override_existing: bool = False,
) -> AllocatorReport:
    """Tune the CUDA caching allocator to fragment less.

    The default allocator carves VRAM into fixed-size segments and cannot
    hand a large request memory that is spread across several small free
    ones. On a long run with varying sequence lengths that shows up as an
    OOM while ``nvidia-smi`` still reports gigabytes free — the memory is
    reserved and unusable, not in use. ``expandable_segments:True`` lets a
    segment grow instead, which is why it is the default here.

    Args:
        expandable_segments: Enable ``expandable_segments:True``. Requires
            torch >= 2.1; below that the allocator ignores the key, so it
            is refused rather than set.
        garbage_collection_threshold: Fraction (0, 1) of the allocator's
            capacity above which it reclaims cached blocks before
            allocating. ``0.8`` is a reasonable value for a card shared
            with a display.
        max_split_size_mb: Refuse to split blocks larger than this. Helps
            a workload with a few large, stable allocations; hurts one
            with many small ones. No default, because which of those you
            have is not something this function can know.
        override_existing: Replace keys the caller already set in the
            environment. Off by default: an explicit
            ``PYTORCH_CUDA_ALLOC_CONF`` is a decision someone made, and
            silently overwriting it is how a deliberate tuning gets lost.

    Returns:
        An :class:`AllocatorReport`. ``applied`` is False when the
        setting could not take effect — most often because CUDA is
        already initialized, at which point this call is too late and
        saying so is the only useful thing left to do.
    """
    previous = os.environ.get(ALLOC_CONF_VAR, "")
    conf = _parse_alloc_conf(previous)
    requested: dict[str, str] = {}

    if expandable_segments:
        version = _torch_version()
        if version is not None and version < _EXPANDABLE_MIN_TORCH:
            return AllocatorReport(
                applied=False,
                value=previous,
                previous=previous,
                reason=(
                    f"expandable_segments needs torch >= "
                    f"{_EXPANDABLE_MIN_TORCH[0]}.{_EXPANDABLE_MIN_TORCH[1]}, "
                    f"found {version[0]}.{version[1]}"
                ),
            )
        requested["expandable_segments"] = "True"

    if garbage_collection_threshold is not None:
        if not 0.0 < garbage_collection_threshold < 1.0:
            raise ValueError(
                "garbage_collection_threshold is a fraction of capacity and "
                f"must be in (0, 1); got {garbage_collection_threshold!r}"
            )
        requested["garbage_collection_threshold"] = str(garbage_collection_threshold)

    if max_split_size_mb is not None:
        if max_split_size_mb <= 0:
            raise ValueError(
                f"max_split_size_mb must be positive; got {max_split_size_mb!r}"
            )
        requested["max_split_size_mb"] = str(int(max_split_size_mb))

    if not requested:
        return AllocatorReport(
            applied=False, value=previous, previous=previous,
            reason="nothing to set",
        )

    # Already initialized? The allocator read this variable at init and
    # will not read it again. Setting it now would look like success and
    # change nothing, which is exactly the failure this reports instead.
    try:
        import torch

        if torch.cuda.is_available() and torch.cuda.is_initialized():
            return AllocatorReport(
                applied=False, value=previous, previous=previous,
                reason=(
                    "CUDA is already initialized — the allocator read "
                    f"{ALLOC_CONF_VAR} at init and will not read it again. "
                    "Call this before the first CUDA allocation."
                ),
            )
    except Exception:
        # No torch yet is the *best* case for this call, not an error.
        pass

    skipped = []
    for key, value in requested.items():
        if key in conf and not override_existing:
            skipped.append(key)
            continue
        conf[key] = value

    if skipped and len(skipped) == len(requested):
        return AllocatorReport(
            applied=False, value=previous, previous=previous,
            reason=(
                f"already set by the caller: {', '.join(sorted(skipped))} "
                "(pass override_existing=True to replace)"
            ),
        )

    value = _format_alloc_conf(conf)
    os.environ[ALLOC_CONF_VAR] = value
    reason = (
        f"kept caller's {', '.join(sorted(skipped))}" if skipped else ""
    )
    return AllocatorReport(
        applied=True, value=value, previous=previous, reason=reason,
    )


# ---------------------------------------------------------------------------
# 2. Activation checkpointing
# ---------------------------------------------------------------------------

@dataclass
class CheckpointHandle:
    """What :func:`checkpoint_blocks` did, and how to undo it.

    Reversibility is the point. Checkpointing is a compute/memory trade
    and the right side of it changes between phases — you want it during
    training and not during a mid-run eval — so a one-way switch would
    make callers rebuild the model to turn it off.
    """

    wrapped: int = 0
    total_blocks: int = 0
    strategy: str = ""
    _undo: list[Any] = field(default_factory=list, repr=False)
    _disabled: bool = field(default=False, repr=False)

    @property
    def active(self) -> bool:
        return self.wrapped > 0 and not self._disabled

    def disable(self) -> int:
        """Restore the original forwards. Returns how many were restored."""
        if self._disabled:
            return 0
        restored = 0
        for module, original in self._undo:
            if original is None:
                # An HF model we turned on through its own API.
                if hasattr(module, "gradient_checkpointing_disable"):
                    module.gradient_checkpointing_disable()
                    restored += 1
            else:
                module.forward = original
                restored += 1
        self._disabled = True
        return restored

    def report(self) -> str:
        if not self.wrapped:
            return "activation checkpointing: not applied"
        state = "active" if self.active else "disabled"
        return (
            f"activation checkpointing ({self.strategy}): "
            f"{self.wrapped}/{self.total_blocks} blocks, {state}"
        )


def _find_block_list(model: Any) -> tuple[list[Any], str]:
    """The repeated transformer blocks, and where they were found.

    Looks for the longest ``nn.ModuleList`` of structurally identical
    children. That is what a transformer's layer stack is, in every
    architecture this package supports, without hard-coding an attribute
    name per architecture — ``.layers``, ``.h``, ``.blocks``, ``.block``
    and ``.decoder.layers`` are all the same shape underneath.
    """
    import torch.nn as nn

    best: list[Any] = []
    best_path = ""
    for path, module in model.named_modules():
        if not isinstance(module, nn.ModuleList) or len(module) < 2:
            continue
        kinds = {type(child) for child in module}
        if len(kinds) != 1:
            continue
        if len(module) > len(best):
            best = list(module)
            best_path = path or "<root>"
    return best, best_path


def checkpoint_blocks(
    model: Any,
    *,
    every: int = 1,
    prefer_native: bool = True,
) -> CheckpointHandle:
    """Recompute activations in the backward pass instead of storing them.

    Activations, not parameters, are what a long-context training run
    actually runs out of: they scale with batch x sequence x layers, and
    the parameters do not scale with any of those. Checkpointing keeps
    only each block's input and recomputes the rest during backward,
    which trades roughly 30% more compute for most of that memory.

    Args:
        model: The module to modify, in place.
        every: Checkpoint every Nth block. ``1`` (default) checkpoints
            all of them for the largest saving; ``2`` checkpoints half,
            for roughly half the saving at roughly half the extra
            compute. Selective checkpointing is the useful middle when
            you are close to fitting rather than far from it.
        prefer_native: Use the model's own ``gradient_checkpointing_enable``
            when it has one (transformers models do). Its implementation
            knows about that architecture's cache and attention-mask
            handling; ours does not. Turn this off only to force the
            generic path — and note it ignores ``every``, since the
            native API has no equivalent.

    Returns:
        A :class:`CheckpointHandle`. ``wrapped == 0`` means no repeated
        block stack was found — for a model that is not a stack of
        identical layers there is nothing here to checkpoint, and that is
        reported rather than raised.

    Note:
        While the generic path is active each block carries a closure as
        its ``forward``, so pickling the *whole model object*
        (``torch.save(model)``) will fail. Saving a ``state_dict`` — what
        :func:`hypernix.training.train.save_snapshot` and every other
        saver in this package do — is unaffected, and
        :meth:`CheckpointHandle.disable` restores picklability if you
        need the other form.
    """
    if every < 1:
        raise ValueError(f"every must be >= 1; got {every!r}")

    import torch
    import torch.utils.checkpoint as tcp

    handle = CheckpointHandle()

    if prefer_native and hasattr(model, "gradient_checkpointing_enable"):
        try:
            model.gradient_checkpointing_enable(
                gradient_checkpointing_kwargs={"use_reentrant": False}
            )
        except TypeError:
            # Older transformers: no kwargs parameter.
            model.gradient_checkpointing_enable()
        blocks, _ = _find_block_list(model)
        handle.wrapped = len(blocks) or 1
        handle.total_blocks = len(blocks) or 1
        handle.strategy = "native"
        handle._undo.append((model, None))
        return handle

    blocks, path = _find_block_list(model)
    handle.total_blocks = len(blocks)
    if not blocks:
        handle.strategy = "none found"
        return handle

    for index, block in enumerate(blocks):
        if index % every:
            continue
        original = block.forward

        def wrapped(*args: Any, _original=original, **kwargs: Any) -> Any:
            # Checkpointing outside a grad-enabled training pass is pure
            # overhead: there is no backward to recompute for, so it
            # would run the block twice and save nothing.
            if not torch.is_grad_enabled():
                return _original(*args, **kwargs)
            # use_reentrant=False is not a preference. The reentrant
            # implementation silently produces no gradients when none of
            # the block's *inputs* require grad — which is the normal
            # case for the first block, whose input is token embeddings.
            return tcp.checkpoint(
                _original, *args, use_reentrant=False, **kwargs
            )

        block.forward = wrapped
        handle._undo.append((block, original))
        handle.wrapped += 1

    handle.strategy = f"generic @ {path}, every {every}"
    return handle


# ---------------------------------------------------------------------------
# 3. Optimizer-in-backward
# ---------------------------------------------------------------------------

@dataclass
class FusedOptimizerHandle:
    """Per-parameter optimizers driven by the backward pass itself.

    Presents ``step`` and ``zero_grad`` so an existing training loop does
    not have to change shape, but both are no-ops: the work already
    happened, parameter by parameter, as each gradient finished
    accumulating. Calling them is correct and free.
    """

    optimizers: dict[Any, Any] = field(default_factory=dict, repr=False)
    _hooks: list[Any] = field(default_factory=list, repr=False)
    _removed: bool = field(default=False, repr=False)

    @property
    def parameter_count(self) -> int:
        return len(self.optimizers)

    def step(self, *_args: Any, **_kwargs: Any) -> None:
        """No-op. Every parameter was stepped during backward."""

    def zero_grad(self, *_args: Any, **_kwargs: Any) -> None:
        """No-op. Every gradient was released during backward."""

    def remove(self) -> int:
        """Detach the hooks. Returns how many were removed."""
        if self._removed:
            return 0
        for hook in self._hooks:
            hook.remove()
        self._removed = True
        return len(self._hooks)

    def state_dict(self) -> dict[str, Any]:
        """Per-parameter optimizer state, keyed by parameter order.

        Named by position rather than by parameter identity because
        tensors are not stable keys across a save and load — the
        ordering of ``model.parameters()`` is.
        """
        return {
            "fused_optimizer_in_backward": True,
            "states": [opt.state_dict() for opt in self.optimizers.values()],
        }


def fuse_optimizer_into_backward(
    model: Any,
    optimizer_factory: Any,
    *,
    grad_clip: float | None = None,
    accumulation_steps: int = 1,
    scaler: Any = None,
) -> FusedOptimizerHandle:
    """Apply and free each gradient the moment it is ready.

    An ordinary loop holds every gradient at once between ``backward``
    and ``step`` — a second full copy of the model, in gradient dtype, at
    exactly the moment activations peak. Attaching the step to each
    parameter's post-accumulation hook means a gradient exists only
    between the instant it is finished and the instant it is applied.

    Args:
        model: The module whose parameters to hook.
        optimizer_factory: Called as ``optimizer_factory([param])`` for
            each trainable parameter, returning an optimizer over just
            that one. ``lambda p: torch.optim.AdamW(p, lr=3e-4)`` is the
            usual form.
        grad_clip: Must be None. Accepted so the caller passes what their
            loop does and gets a refusal, rather than omitting it and
            getting silently unclipped training.
        accumulation_steps: Must be 1, for the same reason.
        scaler: Must be None, for the same reason.

    Raises:
        ValueError: If grad clipping, accumulation, or a ``GradScaler``
            is in use. All three need every gradient present at once —
            a global norm cannot be computed from one gradient, and
            unscaling has to happen before any step. None of the three
            can be made to work here, and each would produce a
            plausible-looking loss curve for a model that trained
            differently than the caller asked for.
        RuntimeError: If torch is older than 2.1, which has no
            ``register_post_accumulate_grad_hook``.
    """
    if grad_clip:
        raise ValueError(
            "Gradient clipping needs every gradient present at once to "
            "compute a global norm, and this frees each one as it is "
            "produced. Use checkpoint_blocks() instead, or drop the clip "
            "deliberately — but do not expect both."
        )
    if accumulation_steps != 1:
        raise ValueError(
            f"accumulation_steps={accumulation_steps}: accumulation needs "
            "gradients to survive across micro-batches, and this frees them "
            "at the end of each backward. The two are alternatives — both "
            "buy memory, and accumulation is the one that keeps clipping."
        )
    if scaler is not None:
        raise ValueError(
            "A GradScaler must unscale every gradient before any step, so "
            "it cannot be combined with stepping during backward. bf16 "
            "autocast needs no scaler and works here."
        )

    version = _torch_version()
    if version is None:
        raise RuntimeError("fuse_optimizer_into_backward requires torch")
    if version < _POST_ACCUM_MIN_TORCH:
        raise RuntimeError(
            "register_post_accumulate_grad_hook needs torch >= "
            f"{_POST_ACCUM_MIN_TORCH[0]}.{_POST_ACCUM_MIN_TORCH[1]}, found "
            f"{version[0]}.{version[1]}"
        )

    handle = FusedOptimizerHandle()
    for param in model.parameters():
        if not param.requires_grad:
            continue
        optimizer = optimizer_factory([param])
        handle.optimizers[param] = optimizer

        def hook(p: Any, _opt=optimizer) -> None:
            _opt.step()
            _opt.zero_grad(set_to_none=True)

        handle._hooks.append(param.register_post_accumulate_grad_hook(hook))

    if not handle.optimizers:
        warnings.warn(
            "fuse_optimizer_into_backward found no parameters with "
            "requires_grad=True — nothing was hooked, and this call saved "
            "no memory.",
            UserWarning,
            stacklevel=2,
        )
    return handle


# ---------------------------------------------------------------------------
# 4. Optimizer-state offload
# ---------------------------------------------------------------------------

@contextmanager
def offload_optimizer_state(
    optimizer: Any, *, pin_memory: bool = True
) -> Iterator[int]:
    """Park optimizer state on the host for the duration of a block.

    Adam-family state is two tensors per parameter — for a model in fp32
    that is twice the parameter memory, sitting idle through any pass
    that is not a training step. Around a mid-run eval or a generation
    sample, moving it out is most of a model's worth of VRAM back, for
    the cost of two host transfers.

    This is a context manager and not a mode on purpose: state that lives
    on the host during the step would move across the bus every step,
    which is a different and much worse trade than doing it twice.

    Yields:
        The number of bytes moved off the device. Zero when the state was
        never on one, which is the CPU-only case and not an error.

    ::

        with vram.offload_optimizer_state(opt):
            metrics = evaluate(model, val_loader)
    """
    import torch

    moved: list[tuple[dict[str, Any], str, Any]] = []
    total = 0
    for state in optimizer.state.values():
        if not isinstance(state, dict):
            continue
        for key, value in list(state.items()):
            if not isinstance(value, torch.Tensor) or value.device.type == "cpu":
                continue
            host = value.detach().to("cpu", copy=True)
            if pin_memory:
                try:
                    host = host.pin_memory()
                except RuntimeError:
                    # Pinning can fail under memory pressure or in a
                    # container with a low locked-memory limit. Slower is
                    # the correct answer here; failing is not.
                    pass
            moved.append((state, key, value.device))
            total += value.numel() * value.element_size()
            state[key] = host

    if moved and torch.cuda.is_available():
        torch.cuda.empty_cache()

    try:
        yield total
    finally:
        # In a finally so an exception inside the block does not leave the
        # optimizer split across two devices, which would fail on the next
        # step with an error naming neither this call nor that exception.
        for state, key, device in moved:
            state[key] = state[key].to(device, non_blocking=True)


def release_cache() -> int:
    """Return cached-but-unused blocks to the driver.

    Returns the bytes reserved by the caching allocator before the call
    minus after, which is 0 on CPU. Worth doing after a phase change —
    after a large eval batch, before a save — and not worth doing every
    step, where it only makes the allocator re-acquire what it just gave
    back.
    """
    try:
        import torch
    except Exception:
        return 0
    if not torch.cuda.is_available():
        return 0
    before = torch.cuda.memory_reserved()
    torch.cuda.empty_cache()
    return max(0, before - torch.cuda.memory_reserved())


# ---------------------------------------------------------------------------
# 5. Measurement
# ---------------------------------------------------------------------------

@dataclass
class PeakMemory:
    """Peak device memory across a block, in bytes.

    ``allocated`` is what the tensors needed; ``reserved`` is what the
    allocator held from the driver. The gap between them is
    fragmentation, which is the number :func:`configure_allocator` is
    trying to move — so a run where ``reserved`` falls and ``allocated``
    does not is the allocator change working, not noise.
    """

    allocated: int = 0
    reserved: int = 0
    start_allocated: int = 0
    available: bool = False

    def report(self) -> str:
        if not self.available:
            return "peak memory: unavailable (no CUDA device)"
        overhead = self.reserved - self.allocated
        return (
            f"peak allocated {_human(self.allocated)}, "
            f"reserved {_human(self.reserved)} "
            f"(+{_human(overhead)} allocator overhead)"
        )


@contextmanager
def measure_peak(device: Any = None) -> Iterator[PeakMemory]:
    """Record peak device memory over a block.

    Resets torch's peak counters on entry, so nested or repeated
    measurements are of the block and not of everything since process
    start. The :class:`PeakMemory` is filled in on exit — reading it
    inside the block gives zeros, because the peak is not known yet.

    ::

        with vram.measure_peak() as peak:
            train_one_epoch(...)
        print(peak.report())
    """
    result = PeakMemory()
    try:
        import torch
    except Exception:
        yield result
        return

    if not torch.cuda.is_available():
        yield result
        return

    result.available = True
    result.start_allocated = torch.cuda.memory_allocated(device)
    torch.cuda.reset_peak_memory_stats(device)
    try:
        yield result
    finally:
        result.allocated = torch.cuda.max_memory_allocated(device)
        result.reserved = torch.cuda.max_memory_reserved(device)


# ---------------------------------------------------------------------------
# 6. Recommendation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Recommendation:
    """One suggested technique, with what it is expected to buy.

    ``saves_bytes`` is an estimate derived from the numbers passed in —
    parameter count, dtype width, the shape of the batch — not a
    measured result and not a benchmark. :func:`measure_peak` is how you
    find out what actually happened.
    """

    technique: str
    saves_bytes: int
    cost: str
    call: str

    def report(self) -> str:
        return (
            f"{self.technique}: ~{_human(self.saves_bytes)} "
            f"({self.cost}) → {self.call}"
        )


def recommend(
    *,
    parameters: int,
    layers: int = 0,
    batch_size: int = 1,
    context_length: int = 0,
    hidden_size: int = 0,
    param_bytes: int = 4,
    grad_clip: bool = True,
    accumulation_steps: int = 1,
) -> list[Recommendation]:
    """Order the techniques by what they are worth for *this* model.

    Every estimate is arithmetic on the arguments, and each one names its
    own assumption in ``cost``. A technique that cannot be used given the
    caller's loop — clipping rules out the fused optimizer — is left out
    rather than listed with a caveat nobody reads.

    Args:
        parameters: Trainable parameter count.
        layers: Number of transformer blocks. Zero means "unknown", and
            the activation estimate is skipped rather than guessed.
        batch_size: Micro-batch size, not the effective batch.
        context_length: Sequence length in tokens.
        hidden_size: Model width.
        param_bytes: Bytes per parameter — 4 for fp32, 2 for bf16/fp16.
        grad_clip: Whether the loop clips gradients.
        accumulation_steps: Micro-batches per optimizer step.

    Returns:
        Recommendations, largest estimated saving first.
    """
    if parameters < 0:
        raise ValueError(f"parameters cannot be negative; got {parameters!r}")

    out: list[Recommendation] = []

    if layers and context_length and hidden_size and batch_size:
        # Activations are dominated by the per-layer residual-stream
        # tensors kept for backward. The multiplier is the conventional
        # rough count of saved tensors per block; checkpointing keeps one
        # of them per block instead of all of them.
        per_layer = batch_size * context_length * hidden_size * param_bytes
        activations = per_layer * layers * 8
        out.append(
            Recommendation(
                technique="activation checkpointing",
                saves_bytes=int(activations * 0.85),
                cost="~30% more compute",
                call="vram.checkpoint_blocks(model)",
            )
        )

    if not grad_clip and accumulation_steps == 1:
        out.append(
            Recommendation(
                technique="optimizer-in-backward",
                saves_bytes=parameters * param_bytes,
                cost="no clipping, no accumulation",
                call="vram.fuse_optimizer_into_backward(model, factory)",
            )
        )

    # Adam keeps two state tensors per parameter, in fp32 regardless of
    # the parameter dtype.
    out.append(
        Recommendation(
            technique="optimizer-state offload (around eval)",
            saves_bytes=parameters * 4 * 2,
            cost="two host transfers per block",
            call="with vram.offload_optimizer_state(opt): ...",
        )
    )

    # Fragmentation is a fraction of what is reserved, not of the model,
    # so this is deliberately the vaguest estimate here — and the
    # cheapest, which is why it is worth doing regardless of its rank.
    out.append(
        Recommendation(
            technique="expandable allocator segments",
            saves_bytes=int(parameters * param_bytes * 0.1),
            cost="nothing",
            call="vram.configure_allocator()",
        )
    )

    return sorted(out, key=lambda r: r.saves_bytes, reverse=True)
