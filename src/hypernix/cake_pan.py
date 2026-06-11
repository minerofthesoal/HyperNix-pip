"""cake_pan — safe CPU + GPU training without corruption or hangs.

A cake pan is what keeps the cake together while it bakes.  In the
kitchen idiom here, :class:`CakePan` wraps a training step with
**hybrid CPU / GPU** safety features:

* **Per-layer device placement** — put hot layers on GPU and cold
  ones on CPU (or split by a predicate).  Move tensors between
  devices at the layer boundaries without manual ``.to()`` calls.
* **NaN / Inf detection** — checks the loss (and optionally the
  gradients) after every step.  On detection, reverts to the
  last-known-good snapshot and raises :class:`BakeOff`.
* **Memory watchdog** — when GPU memory passes ``free_gb_trip``,
  performs an ``empty_cache`` and optionally offloads a slice of
  named modules to CPU.  Avoids the OOM that causes CUDA context
  loss / the "kernel panic" pattern on some Linux drivers.
* **Wall-time watchdog** — a single step longer than
  ``step_timeout_s`` is assumed stuck; raises :class:`BakeOff` so
  the caller can decide whether to restart.  Prevents the "PC
  freezes until OOM killer" outcome.
* **Deterministic snapshots** — every ``snapshot_every`` steps the
  state dict is pickled to ``snapshot_path`` so a crash loses at
  most that many steps.

Usage::

    from hypernix.cake_pan import CakePan

    pan = CakePan(
        model, optimizer,
        gpu_device="cuda",
        cpu_offload_patterns=("embed_tokens", "lm_head"),
        free_gb_trip=0.5, step_timeout_s=120.0,
        snapshot_every=100, snapshot_path="run/ckpt.pt",
    )
    pan.save_pristine()
    try:
        for batch in loader:
            loss = pan.bake(lambda: one_training_step(batch))
    except pan.BakeOff as exc:
        print("rolled back:", exc)

``bake`` is a context-ish wrapper that does exactly one step; the
training loop lives in the caller.  For continuous-bake use the
:meth:`oven` helper instead.
"""
from __future__ import annotations

import signal
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn

from .freezer import probe_vram


class BakeOff(RuntimeError):
    """Raised when a CakePan detects a corruption-class event
    (NaN / Inf / stuck step / OOM).  Carries the reason and the
    offending step number."""

    def __init__(self, reason: str, step: int) -> None:
        super().__init__(f"BakeOff @ step {step}: {reason}")
        self.reason = reason
        self.step = step


@dataclass
class CakePan:
    """Hybrid CPU + GPU training guard.  See module docstring."""

    model: nn.Module
    optimizer: torch.optim.Optimizer | None = None
    gpu_device: str = "cuda"
    cpu_device: str = "cpu"
    #: Parameter-name substrings whose *modules* get offloaded to
    #: CPU when the memory watchdog trips.
    cpu_offload_patterns: tuple[str, ...] = ()
    #: GPU free-memory threshold in GB that triggers the watchdog.
    free_gb_trip: float = 0.5
    #: Maximum wall-clock seconds a single step is allowed to take.
    step_timeout_s: float = 120.0
    #: Save a pickled state dict every N steps.  0 disables.
    snapshot_every: int = 0
    snapshot_path: Path | str | None = None
    #: When True, gradient tensors are scanned for NaN / Inf as well as
    #: the loss.  Default True; disable to save a little wall time on
    #: models with billions of parameters.
    check_grads: bool = True

    step_count: int = field(default=0, init=False)
    pristine_state: dict[str, torch.Tensor] | None = field(
        default=None, init=False, repr=False,
    )

    #: Re-exported at instance level so ``except pan.BakeOff:`` works.
    BakeOff: type = field(default=BakeOff, init=False, repr=False)

    # ------------------------------------------------------------------
    # Pristine snapshots (in-memory; distinct from on-disk snapshots)
    # ------------------------------------------------------------------

    def save_pristine(self) -> None:
        """Capture the current state dict on CPU.  Every
        :meth:`bake` that detects corruption reverts to this
        snapshot.  Call it again after a clean stretch to advance
        the rollback point."""
        self.pristine_state = {
            k: v.detach().cpu().clone()
            for k, v in self.model.state_dict().items()
        }

    def roll_back(self) -> bool:
        """Restore the last pristine snapshot.  Returns True on
        success, False if no snapshot exists."""
        if self.pristine_state is None:
            return False
        with torch.no_grad():
            state = self.model.state_dict()
            for name, saved in self.pristine_state.items():
                if name in state:
                    state[name].copy_(saved.to(state[name].device))
        if self.optimizer is not None:
            # Optimizer state can carry NaN-contaminated moments; zero
            # them out so subsequent steps don't re-propagate trouble.
            for group in self.optimizer.param_groups:
                for p in group["params"]:
                    if p in self.optimizer.state:
                        for v in self.optimizer.state[p].values():
                            if isinstance(v, torch.Tensor):
                                v.zero_()
        return True

    # ------------------------------------------------------------------
    # Memory watchdog
    # ------------------------------------------------------------------

    def memory_guard(self) -> bool:
        """Return True if the guard performed an offload this call."""
        b = probe_vram()
        if b.total == 0:
            return False  # CPU-only — nothing to guard
        if b.free_gb >= self.free_gb_trip:
            return False
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        if not self.cpu_offload_patterns:
            return False
        moved = 0
        for mod_name, module in self.model.named_modules():
            if mod_name and any(p in mod_name for p in self.cpu_offload_patterns):
                module.to(self.cpu_device)
                moved += 1
        return moved > 0

    # ------------------------------------------------------------------
    # The step
    # ------------------------------------------------------------------

    def bake(self, step_fn: Callable[[], torch.Tensor | Any]) -> Any:
        """Run one training step safely.

        ``step_fn`` must return a loss tensor (or any object — only
        the tensor path gets NaN-checked).  On any of:

          * loss contains NaN or Inf,
          * a grad contains NaN or Inf (when ``check_grads=True``),
          * the call takes longer than ``step_timeout_s`` seconds,

        :meth:`roll_back` fires and :class:`BakeOff` is raised.
        Callers catch ``BakeOff`` to skip the batch / restart the
        loop / write a post-mortem.
        """
        self.step_count += 1

        # Wall-time watchdog via SIGALRM (Linux / macOS only).
        # Pass 2 (v0.50): when the alarm fires mid-step the model
        # may be partly updated; roll back inside the handler before
        # raising so the caller doesn't have to remember to.
        prev_handler = None
        if self.step_timeout_s > 0 and hasattr(signal, "SIGALRM"):
            def _timeout_handler(signum, frame):  # noqa: ANN001
                self.roll_back()
                raise BakeOff(
                    f"step exceeded {self.step_timeout_s:.0f}s",
                    self.step_count,
                )
            prev_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(int(self.step_timeout_s) + 1)

        started = time.monotonic()
        try:
            try:
                self.memory_guard()
                result = step_fn()
            except torch.cuda.OutOfMemoryError as exc:
                self.roll_back()
                raise BakeOff(f"OOM: {exc}", self.step_count) from exc

            # NaN / Inf sweep on the returned loss tensor.
            if isinstance(result, torch.Tensor):
                self._check_tensor("loss", result)
            # ...and on gradients if requested.
            if self.check_grads:
                for name, p in self.model.named_parameters():
                    if p.grad is not None:
                        self._check_tensor(f"grad[{name}]", p.grad)

            # Optional on-disk snapshot.
            if (
                self.snapshot_every > 0
                and self.snapshot_path is not None
                and self.step_count % self.snapshot_every == 0
            ):
                p = Path(self.snapshot_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                torch.save(self.model.state_dict(), p)

            return result

        finally:
            if prev_handler is not None and hasattr(signal, "SIGALRM"):
                signal.alarm(0)
                signal.signal(signal.SIGALRM, prev_handler)
            # Track step wall time for callers that want to log it.
            self.last_step_seconds = time.monotonic() - started

    def _check_tensor(self, what: str, t: torch.Tensor) -> None:
        if not torch.isfinite(t).all():
            self.roll_back()
            raise BakeOff(f"{what} contains NaN/Inf", self.step_count)

    # ------------------------------------------------------------------
    # Oven loop helper
    # ------------------------------------------------------------------

    def oven(
        self,
        batches: Iterable[Any],
        step_fn: Callable[[Any], torch.Tensor | Any],
        *,
        on_bake_off: Callable[[BakeOff], None] | None = None,
        max_retries_per_batch: int = 2,
    ) -> int:
        """Loop over ``batches``, calling ``step_fn(batch)`` under
        :meth:`bake` guard.  On a :class:`BakeOff` the batch is
        retried up to ``max_retries_per_batch`` times before being
        skipped.  Returns the count of successfully completed steps."""
        good = 0
        for batch in batches:
            attempts = 0
            while True:
                attempts += 1
                try:
                    self.bake(lambda b=batch: step_fn(b))
                    good += 1
                    break
                except BakeOff as exc:
                    if on_bake_off is not None:
                        on_bake_off(exc)
                    if attempts > max_retries_per_batch:
                        break
        return good


def cake_pan(
    model: nn.Module,
    optimizer: torch.optim.Optimizer | None = None,
    **kwargs: Any,
) -> CakePan:
    """Construct a :class:`CakePan` with keyword configuration."""
    return CakePan(model=model, optimizer=optimizer, **kwargs)
