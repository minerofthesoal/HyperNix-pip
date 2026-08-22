"""hypernix.pressure_cooker_v6 — Pressure Cooker V6: Single-State Trust Momentum (SSTM).

Where V5 / V5S are **memory-first** (quantized momentum, factored curvature,
uint8 age counters — every trick in the book to shrink optimizer state, at
the cost of several small Python-level ops per parameter per step), V6 is
**speed-first**. It intentionally throws away most of the V5 machinery —
no oscillation tracking, no curvature estimate, no gradient-age freezing, no
quantize/dequantize round trip — and keeps exactly one thing: a single
momentum buffer, updated with fused multi-tensor ops instead of a
per-parameter Python loop.

What actually makes V6 faster than AdamW (and than V5) is not a smarter
update rule — it's a smaller *op count* and far fewer host↔device
synchronization points:

* AdamW tracks two buffers (`exp_avg`, `exp_avg_sq`) and does a bias-corrected
  sqrt + division per element. V6 tracks **one** buffer and does a single
  fused multiply-add.
* V5's `_orcp_step` calls Python `float()` on 3-4 device tensors *per
  parameter, per step* (cosine similarity, oscillation score, trust ratio),
  each one a CPU↔GPU synchronization barrier — with hundreds of parameter
  tensors in a real model, that's hundreds of stalls every step. V6 batches
  its one optional per-tensor scalar (the trust ratio) into a **single**
  `.tolist()` call across the whole parameter group — one sync per step,
  not one (or four) per tensor.
* The momentum update, weight decay, and (when available) the trust-ratio
  norms all run through `torch._foreach_*` multi-tensor ops, which dispatch
  to the same fused multi-tensor-apply CUDA kernels PyTorch's own
  `foreach=True`/`fused=True` optimizers use — not a hand-rolled substitute,
  the real thing.

This trades away V5's adaptive-per-parameter learning rate (no second
moment, no curvature estimate) for raw throughput. It is closer in lineage
to LARS/LAMB-style layerwise trust-ratio scaling on top of plain momentum
than to AdamW — that's a real tradeoff, not hidden: V6 will typically need
more learning-rate tuning than AdamW for a new model/dataset, since it has
no per-element adaptive denominator smoothing out gradient-scale
differences across a tensor. It optimizes for wall-clock step time and a
smaller (not tiny — one buffer instead of two, not a quantized microscopic
one) memory footprint.

Update rule (per parameter group, batched across all tensors in the group)
----------------------------------------------------------------------
1. Decoupled weight decay:      p *= (1 - lr * wd)                    [foreach]
2. Momentum EMA:                m = beta*m + (1-beta)*g               [foreach]
3. (optional) Nesterov lookahead: u = g + beta*m   else   u = m       [foreach]
4. Bias correction folded into the learning rate (no extra tensor op):
   eff_lr = lr / (1 - beta**global_step)
5. (optional) Trust ratio, computed once for the whole group:
   trust = clamp(||p|| / ||u||, trust_clip)                    [foreach norm]
6. Parameter update:            p -= eff_lr * trust * u        [per-tensor add_]

No second moment. No bias-correction-per-element division. No quantization.

Memory footprint (optimizer *state* only, relative to AdamW's two fp32
buffers per parameter — see ``scripts/measure_optimizer_memory.py`` for
exact, measured-not-estimated byte counts, not an estimate):

* AdamW              2 buffers/param (exp_avg + exp_avg_sq), fp32
* PressureCookerV6    1 buffer/param (momentum), fp32 — "a little less" RAM
                      than AdamW, not V5/V5S's aggressive quantized/factored
                      savings; V6 is optimizing for speed, not minimum RAM.

No Pascal-specific ``Agedcookerv6`` tier exists (unlike V3/V4/V5's
``Aged*``/``ULTRAaged*`` classes) because V6 never calls torch's
``fused=True`` AdamW kernel (the thing that actually requires CUDA
sm_70+) — ``torch._foreach_*`` ops run fine on Pascal, so there's nothing
to work around.

Beyond the core update rule, V6 carries the same real-training features
``hypernix.pressure_cooker.InductionCooker`` has (grad accumulation,
``GradScaler`` integration) rather than being a minimal update-rule demo
that assumes a toy training loop:

* ``grad_accum_steps``: only every Nth :meth:`~PressureCookerV6.step`
  call actually applies an update; matches
  ``InductionCooker``'s contract exactly.
* ``grad_scaler``: fp16 mixed-precision support — ``unscale_(self)`` then
  skip the update cleanly on a non-finite batch instead of corrupting
  momentum state, same as ``InductionCooker``, but the non-finite check
  itself is batched into a single ``torch._foreach_norm`` + one host sync
  across the *whole step*, rather than ``InductionCooker``'s per-parameter
  ``.all()`` sync — V6 stays consistent with its own "batch every host
  sync" design even in this safety path.
* ``skip_on_nonfinite``: the same batched check, opt-in, for plain
  (non-scaler) training. Off by default so the default configuration's
  op count — and the measured numbers cited in the wiki — are exactly
  what's documented, not inflated by an always-on safety check most
  users in a stable training run will never trigger.

See ``PressureCookerV6V.warmup_graph``'s docstring for an important,
concrete caveat about how these three features interact with CUDA graph
capture (short version: capture bakes in whichever branch ran during
warmup, permanently — don't combine dynamic accumulation/inf-skipping
with graph replay without understanding that first).

v0.71.4-4 — initial release of the V6 architecture (unreleased at time of writing; see wiki/Changelog.md).
"""
from __future__ import annotations

import warnings
from collections.abc import Iterable
from typing import Any

import torch

from hypernix.optimizers.optimizer_framework import OptimizerBase, ScheduleConfig
from hypernix.optimizers.pressure_cooker_v3 import _flatten_optimizer_params

__all__ = [
    "PressureCookerV6",
]

_HAS_FOREACH = hasattr(torch, "_foreach_mul_") and hasattr(torch, "_foreach_add_")
_HAS_FOREACH_NORM = hasattr(torch, "_foreach_norm")


class PressureCookerV6(OptimizerBase):
    """Pressure Cooker V6 — Single-State Trust Momentum (SSTM).

    A speed-first optimizer: one momentum buffer, fused multi-tensor
    (``torch._foreach_*``) updates, and at most one host↔device
    synchronization per step (for the optional trust ratio) instead of
    several per parameter tensor. See the module docstring for the full
    design rationale and the honest tradeoffs versus AdamW and V5/V5S.

    Args:
        params: Iterable of parameters or param-group dicts.
        schedule: Optional :class:`ScheduleConfig`; built from ``lr`` if omitted.
        lr: Peak learning rate.
        momentum_beta: EMA decay for the single momentum buffer.
        weight_decay: Decoupled (AdamW-style) weight decay coefficient.
        nesterov: If True, use Nesterov lookahead (``g + beta*m``) instead
            of plain momentum as the update direction.
        trust_ratio: If True, apply a LARS/LAMB-style per-tensor trust
            ratio (``clamp(||p|| / ||update||, trust_clip)``) on top of the
            momentum update. This is the only source of per-tensor (not
            per-element) adaptivity in V6 — disable it for the absolute
            minimum op count.
        trust_clip: ``(min, max)`` clamp applied to the trust ratio.
        eps: Numerical stability term (denominator floors, bias-correction floor).
        grad_clip: Optional global gradient-norm clip threshold (see
            :meth:`OptimizerBase.gradient_clip`).
        foreach: Use ``torch._foreach_*`` fused multi-tensor ops when
            available. Falls back to a plain per-tensor Python loop
            (still no per-*element* Python-level work) if the installed
            torch build lacks them.
        grad_scaler: Optional ``torch.cuda.amp.GradScaler`` (or
            ``torch.amp.GradScaler``) for fp16 mixed-precision training.
            When set, every :meth:`step` call runs
            ``grad_scaler.unscale_(self)`` and skips the update cleanly
            (without touching momentum state) if any gradient came back
            non-finite, then calls ``grad_scaler.update()`` either way —
            same contract as :class:`hypernix.pressure_cooker.InductionCooker`.
            The non-finite check itself is batched across the whole step
            with a single ``torch._foreach_norm`` + one host sync, not a
            per-parameter one.
        grad_accum_steps: Only every Nth :meth:`step` call actually
            updates parameters; the intervening calls are no-ops (your
            training loop still calls ``loss.backward()`` every
            micro-batch as usual — this only gates *when the optimizer
            applies the accumulated gradient*, it does not itself average
            gradients across micro-batches).
        skip_on_nonfinite: If True (and no ``grad_scaler`` is set), run
            the same batched non-finite check on plain (non-scaler)
            training and skip the update on a bad batch instead of
            corrupting momentum state. Off by default to keep the
            default configuration's op count and measured performance
            exactly as documented — turn it on for extra robustness on
            unstable runs, or leave it off if you'd rather let a bad
            batch surface as a visible NaN loss immediately. Always
            active when ``grad_scaler`` is set, regardless of this flag,
            since skipping on non-finite is not optional for correctness
            when gradients are (un)scaled.
    """

    def __init__(
        self,
        params: Iterable[torch.nn.Parameter] | Iterable[dict],
        *,
        schedule: ScheduleConfig | None = None,
        lr: float = 3e-4,
        momentum_beta: float = 0.9,
        weight_decay: float = 0.01,
        nesterov: bool = False,
        trust_ratio: bool = True,
        trust_clip: tuple[float, float] = (0.05, 5.0),
        eps: float = 1e-8,
        grad_clip: float | None = 1.0,
        foreach: bool = True,
        grad_scaler: Any = None,
        grad_accum_steps: int = 1,
        skip_on_nonfinite: bool = False,
        **kwargs: Any,
    ) -> None:
        if grad_accum_steps < 1:
            raise ValueError("grad_accum_steps must be >= 1")
        materialized_params = _flatten_optimizer_params(params)
        defaults = {"weight_decay": weight_decay}
        super().__init__(
            params=materialized_params,
            defaults=defaults,
            schedule=schedule or ScheduleConfig(lr=lr),
            grad_clip=grad_clip,
            **kwargs,
        )
        self.lr = lr
        self.momentum_beta = momentum_beta
        self.weight_decay = weight_decay
        self.nesterov = nesterov
        self.trust_ratio = trust_ratio
        self.trust_clip = trust_clip
        self.eps = eps
        self.foreach = foreach and _HAS_FOREACH
        self.grad_scaler = grad_scaler
        self.grad_accum_steps = grad_accum_steps
        self.skip_on_nonfinite = skip_on_nonfinite
        self._accum_counter = 0
        self._skipped_steps = 0
        if foreach and not _HAS_FOREACH:
            warnings.warn(
                "torch._foreach_mul_/_foreach_add_ are unavailable on this "
                f"torch build (torch {torch.__version__}); PressureCookerV6 "
                "will fall back to a plain per-tensor loop. It stays "
                "correct, just not fused.",
                stacklevel=2,
            )
        if trust_ratio and self.foreach and not _HAS_FOREACH_NORM:
            warnings.warn(
                "torch._foreach_norm is unavailable on this torch build "
                f"(torch {torch.__version__}); the trust-ratio norms will "
                "be computed with a plain per-tensor loop instead of a "
                "fused one.",
                stacklevel=2,
            )

    # -- state -------------------------------------------------------------

    def _init_state(self, state: dict[str, Any], p: torch.Tensor) -> None:
        state["momentum"] = torch.zeros_like(p, memory_format=torch.preserve_format)

    # -- mixed-precision / stability helpers --------------------------------

    def _grads_finite(self) -> bool:
        """Batched non-finite check across every gradient in this step.

        One ``torch._foreach_norm`` (or a plain-loop fallback) plus a
        single host sync for the *entire* optimizer, not one ``.all()``
        sync per parameter tensor -- keeps the same "batch the syncs"
        design the rest of this module follows.
        """
        grads = [
            p.grad
            for group in self.param_groups
            for p in group["params"]
            if p.grad is not None
        ]
        if not grads:
            return True
        if self.foreach and _HAS_FOREACH_NORM:
            norms = torch.stack(list(torch._foreach_norm(grads)))
            return bool(torch.isfinite(norms).all())
        return all(bool(torch.isfinite(g).all()) for g in grads)

    # -- core step -----------------------------------------------------------

    def _apply_update(self) -> None:
        """Hook point: applies the actual parameter update. Overridden by
        :class:`~hypernix.pressure_cooker_v6v.PressureCookerV6V` to route
        through a compiled step instead of duplicating everything else in
        :meth:`step` (grad accumulation, GradScaler handling, grad clip)."""
        self._sstm_step()

    @torch.no_grad()
    def _sstm_step(self) -> None:
        for group in self.param_groups:
            lr = group["lr"]
            wd = group["weight_decay"]

            params: list[torch.Tensor] = []
            grads: list[torch.Tensor] = []
            moms: list[torch.Tensor] = []
            for p in group["params"]:
                if p.grad is None:
                    continue
                state = self.state[p]
                if "momentum" not in state:
                    self._init_state(state, p)
                params.append(p)
                grads.append(p.grad)
                moms.append(state["momentum"])

            if not params:
                continue

            use_foreach = self.foreach and len({p.device for p in params}) == 1 \
                and len({p.dtype for p in params}) == 1

            if wd != 0.0:
                if use_foreach:
                    torch._foreach_mul_(params, 1.0 - lr * wd)
                else:
                    for p in params:
                        p.mul_(1.0 - lr * wd)

            if use_foreach:
                torch._foreach_mul_(moms, self.momentum_beta)
                torch._foreach_add_(moms, grads, alpha=1.0 - self.momentum_beta)
            else:
                for m, g in zip(moms, grads, strict=True):
                    m.mul_(self.momentum_beta).add_(g, alpha=1.0 - self.momentum_beta)

            if self.nesterov:
                if use_foreach:
                    update_src = list(
                        torch._foreach_add(grads, torch._foreach_mul(moms, self.momentum_beta))
                    )
                else:
                    update_src = [
                        g + self.momentum_beta * m for g, m in zip(grads, moms, strict=True)
                    ]
            else:
                update_src = moms

            # Bias correction folded into the effective LR instead of an
            # extra elementwise rescale of the momentum buffer.
            bias_correction = 1.0 - self.momentum_beta ** (self._global_step + 1)
            eff_lr = lr / max(bias_correction, self.eps)

            if self.trust_ratio:
                if use_foreach and _HAS_FOREACH_NORM:
                    p_norms = torch.stack(list(torch._foreach_norm(params)))
                    u_norms = torch.stack(list(torch._foreach_norm(update_src)))
                else:
                    p_norms = torch.stack([p.norm(2) for p in params])
                    u_norms = torch.stack([u.norm(2) for u in update_src])
                trust = (p_norms / u_norms.clamp(min=self.eps)).clamp(
                    self.trust_clip[0], self.trust_clip[1]
                )
                # One sync for the *entire* group, not one per tensor.
                trust_list = trust.tolist()
            else:
                trust_list = [1.0] * len(params)

            for p, u, t in zip(params, update_src, trust_list, strict=True):
                p.add_(u, alpha=-eff_lr * t)

    @torch.no_grad()
    def step(self, closure=None):
        loss = None
        if closure is not None:
            with torch.enable_grad():
                loss = closure()

        self._apply_lr_schedule()

        # Gradient accumulation: only the Nth call actually updates.
        self._accum_counter += 1
        if self._accum_counter < self.grad_accum_steps:
            return loss
        self._accum_counter = 0

        # Mixed-precision safety: unscale, then skip the update cleanly
        # (no momentum/param mutation) on a non-finite batch instead of
        # corrupting optimizer state. Always checked when a GradScaler is
        # attached; optionally checked otherwise via skip_on_nonfinite.
        if self.grad_scaler is not None:
            self.grad_scaler.unscale_(self)
        if self.grad_scaler is not None or self.skip_on_nonfinite:
            if not self._grads_finite():
                if self.grad_scaler is not None:
                    self.grad_scaler.update()
                self._skipped_steps += 1
                return loss

        if self._grad_clip is not None:
            self.gradient_clip()

        self._apply_update()

        if self.grad_scaler is not None:
            self.grad_scaler.update()
        self._global_step += 1
        return loss

    def describe(self) -> dict[str, Any]:
        base = super().describe()
        base["kind"] = type(self).__name__
        base["momentum_beta"] = self.momentum_beta
        base["nesterov"] = self.nesterov
        base["trust_ratio"] = self.trust_ratio
        base["trust_clip"] = self.trust_clip
        base["foreach"] = self.foreach
        base["grad_accum_steps"] = self.grad_accum_steps
        base["grad_scaler"] = self.grad_scaler is not None
        base["skip_on_nonfinite"] = self.skip_on_nonfinite
        base["skipped_steps"] = self._skipped_steps
        return base
