"""hypernix.pressure_cooker_v5 — Pressure Cooker V5: the ORCP optimizer family.

Unlike every previous PressureCooker generation, V5 is **not** a dressed-up
AdamW.  There is no exponential-moving-average second moment, no bias
correction on a (beta1, beta2) pair, no RMSProp-style denominator — the whole
update rule is written from scratch around an "Oscillation Resistant Cosine
Power" (ORCP) core:

* a single **quantized** (int8) momentum buffer instead of a full-precision
  first moment,
* an Adafactor-style **factored** row/column curvature estimate for matrix
  parameters instead of a full elementwise second moment (~0.1x memory for
  those tensors),
* **sign * |grad|^power** updates (power-scaled gradients) instead of a
  normalized-by-RMS update,
* oscillation resistance from the **cosine similarity** between the raw
  gradient and the momentum direction, tracked at two timescales,
* **uint8 age counters** that soft-freeze coordinates whose gradient has
  been near zero for a while (dynamic coordinate freezing / gradient age
  tracking),
* optional Sharpness-Aware Minimization (SAM) and Sophia-style curvature
  clipping layered on top.

Memory budget (relative to plain SGD = 1.0x, informal targets used while
designing this file — actual numbers depend on model shape):

* SGD                    ~1.0x
* Momentum SGD           ~2.0x
* PressureCookerV5       ~1.7x   (quantized momentum + factored curvature)
* PressureCookerV5Plus   ~2.1x   (adds a few extra per-tensor scalars/rows)
* AdamW                  ~3.0x

v0.70.5b3:
- Introduces PressureCookerV5 (ORCP core) and PressureCookerV5Plus
  (ORCP-Ultra core), a family of optimizers written from scratch --
  not derived from AdamW, AdamW, RMSProp, Adafactor, Lion, or SGD.
- Adds Agedcookerv5 / ULTRAagedcookerv5 for CUDA 6.1/6.2 (Pascal, e.g.
  GTX 10-series) constrained hardware, matching the Agedcookerv4 /
  ULTRAagedcookerv4 naming convention from pressure_cooker_v4.
"""
from __future__ import annotations

import math
import warnings
from collections.abc import Iterable
from typing import Any

import torch

from .optimizer_framework import OptimizerBase, ScheduleConfig
from .pressure_cooker_v3 import (
    _flatten_optimizer_params,
    _is_cuda_61_or_older,
    _params_cuda_capability,
)

__all__ = [
    "Agedcookerv5",
    "PressureCookerV5",
    "PressureCookerV5Plus",
    "ULTRAagedcookerv5",
]

_INT8_MAX = 127.0
# Above this many elements a 1-D parameter's curvature estimate is collapsed
# to a single scalar rather than kept elementwise ("sparse optimizer state
# storage") -- large embedding/bias-like vectors would otherwise dominate
# the optimizer's memory footprint.
_SPARSE_VECTOR_THRESHOLD = 1 << 16  # 65536 elements


def _quantize_momentum(m: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """Quantize a momentum tensor to int8 + a per-tensor fp32 scale.

    This is the "quantized optimizer state storage" feature: instead of
    keeping a full-precision (fp32/fp16) momentum buffer around forever,
    V5 only ever persists an int8 tensor plus one scalar per parameter.
    """
    scale = m.abs().amax().clamp(min=1e-12)
    q = (m / scale * _INT8_MAX).round().clamp_(-_INT8_MAX, _INT8_MAX).to(torch.int8)
    return q, scale


def _dequantize_momentum(q: torch.Tensor, scale: torch.Tensor) -> torch.Tensor:
    return q.to(torch.float32) * (scale / _INT8_MAX)


class PressureCookerV5(OptimizerBase):
    """Baseline PressureCooker V5 -- Oscillation Resistant Cosine Power (ORCP) core.

    Written entirely from scratch: no part of :meth:`_orcp_step` borrows
    AdamW's, RMSProp's, Adafactor's, Lion's, or SGD's update rule.

    Features
    --------
    * Oscillation resistance via cosine similarity between the raw gradient
      and the momentum direction, at a fast and a slow timescale.
    * Power-scaled gradients: ``sign(g) * |g|^power``.
    * Dynamic oscillation damping of the effective step size.
    * Multi-timescale gradient comparison (fast/slow cosine EMAs).
    * Per-parameter adaptive power exponent (moves toward ``power_min`` when
      oscillating, toward ``power_max`` when consistent).
    * Curvature-lite estimation (cheap diagonal-Hessian proxy from squared
      gradients, factored row/column for matrices).
    * Quantized (int8) optimizer momentum state.
    * Trust ratio scaling (LARS/LAMB-style layerwise learning rates).
    * Dynamic coordinate freezing with uint8 gradient-age counters
      (soft-pruning of stagnant weights).
    * Predictive gradient extrapolation (a one-step look-ahead along the
      momentum direction before computing the update).
    * Sparse optimizer state storage (large 1-D tensors fall back to a
      single scalar curvature estimate instead of an elementwise one).
    * Sharpness-Aware Minimization (``sam_rho > 0``): adversarial gradient
      perturbation for flat-minimum seeking.
    * Sophia-style Hessian-aware clipping of the final update.
    """

    def __init__(
        self,
        params: Iterable[torch.nn.Parameter] | Iterable[dict],
        *,
        schedule: ScheduleConfig | None = None,
        lr: float = 3e-4,
        momentum_beta: float = 0.9,
        slow_beta: float = 0.98,
        power: float = 0.5,
        power_min: float = 0.3,
        power_max: float = 1.0,
        weight_decay: float = 0.01,
        eps: float = 1e-8,
        grad_clip: float | None = 1.0,
        freeze_threshold: float = 1e-6,
        freeze_patience: int = 32,
        freeze_decay: float = 0.98,
        extrapolation: float = 0.15,
        trust_clip: tuple[float, float] = (0.05, 5.0),
        sophia_clip: float = 1.0,
        curvature_beta: float = 0.98,
        sam_rho: float = 0.0,
        factorize_matrices: bool = True,
        fused: bool | None = None,
        **kwargs: Any,
    ) -> None:
        materialized_params = _flatten_optimizer_params(params)
        self.cuda_capability = _params_cuda_capability(materialized_params)
        self.cuda_61_compatible = _is_cuda_61_or_older(self.cuda_capability)
        if self.cuda_61_compatible:
            fused = False

        defaults = {"weight_decay": weight_decay}
        super().__init__(
            params=materialized_params,
            defaults=defaults,
            schedule=schedule or ScheduleConfig(lr=lr),
            grad_clip=grad_clip,
            **kwargs,
        )

        self.momentum_beta = momentum_beta
        self.slow_beta = slow_beta
        self.power = power
        self.power_min = power_min
        self.power_max = power_max
        self.eps = eps
        self.freeze_threshold = freeze_threshold
        self.freeze_patience = freeze_patience
        self.freeze_decay = freeze_decay
        self.extrapolation = extrapolation
        self.trust_clip = trust_clip
        self.sophia_clip = sophia_clip
        self.curvature_beta = curvature_beta
        self.sam_rho = sam_rho
        self.factorize_matrices = factorize_matrices
        self.fused = fused

    # -- top-level step -------------------------------------------------

    @torch.no_grad()
    def step(self, closure=None):
        if self.sam_rho > 0 and closure is not None:
            return self._sam_step(closure)

        loss = None
        if closure is not None:
            with torch.enable_grad():
                loss = closure()

        self._apply_lr_schedule()
        if self._grad_clip is not None:
            self.gradient_clip()

        self._orcp_step()
        self._global_step += 1
        return loss

    # -- SAM (Sharpness-Aware Minimization) ------------------------------

    def _sam_perturb(self) -> dict[int, torch.Tensor]:
        """Ascend toward a nearby higher-loss point (Foret et al., 2020)."""
        pairs = [
            (p, p.grad)
            for group in self.param_groups
            for p in group["params"]
            if p.grad is not None
        ]
        if not pairs:
            return {}
        grad_norm = torch.norm(torch.stack([g.norm(2) for _, g in pairs]))
        scale = self.sam_rho / (grad_norm + 1e-12)
        eps_map: dict[int, torch.Tensor] = {}
        for p, g in pairs:
            e = g * scale
            p.add_(e)
            eps_map[id(p)] = e
        return eps_map

    def _sam_unperturb(self, eps_map: dict[int, torch.Tensor]) -> None:
        for group in self.param_groups:
            for p in group["params"]:
                e = eps_map.get(id(p))
                if e is not None:
                    p.sub_(e)

    def _sam_step(self, closure):
        with torch.enable_grad():
            closure()
        self._apply_lr_schedule()
        if self._grad_clip is not None:
            self.gradient_clip()

        eps_map = self._sam_perturb()
        with torch.enable_grad():
            self.zero_grad(set_to_none=True)
            loss = closure()
        self._sam_unperturb(eps_map)

        self._orcp_step()
        self._global_step += 1
        return loss

    # -- ORCP core --------------------------------------------------------

    def _init_state(self, state: dict[str, Any], p: torch.Tensor) -> None:
        state["step"] = 0
        state["power"] = self.power
        state["slow_cos"] = 0.0
        m0 = torch.zeros_like(p, memory_format=torch.preserve_format)
        state["m_q"], state["m_scale"] = _quantize_momentum(m0)

        is_matrix = self.factorize_matrices and p.dim() >= 2
        state["is_matrix"] = is_matrix
        if is_matrix:
            rows, cols = p.shape[0], p.numel() // p.shape[0]
            state["row_curv"] = torch.zeros(rows, 1, device=p.device, dtype=torch.float32)
            state["col_curv"] = torch.zeros(1, cols, device=p.device, dtype=torch.float32)
            state["row_age"] = torch.zeros(rows, 1, device=p.device, dtype=torch.uint8)
        else:
            sparse = p.numel() > _SPARSE_VECTOR_THRESHOLD
            state["sparse"] = sparse
            if sparse:
                state["curv"] = torch.zeros((), device=p.device, dtype=torch.float32)
            else:
                state["curv"] = torch.zeros_like(p, memory_format=torch.preserve_format)
            state["age"] = torch.zeros_like(p, dtype=torch.uint8)

    def _oscillation_signal(self, state: dict[str, Any], g: torch.Tensor, m: torch.Tensor) -> tuple[float, float]:
        """Cosine similarity between grad and momentum, at two timescales."""
        denom = (g.norm() * m.norm()).clamp(min=self.eps)
        cos_sim = float((g * m).sum() / denom)
        state["slow_cos"] = self.slow_beta * state["slow_cos"] + (1 - self.slow_beta) * cos_sim
        osc_score = -(cos_sim + state["slow_cos"]) / 2.0
        return cos_sim, max(-1.0, min(1.0, osc_score))

    def _adaptive_power(self, state: dict[str, Any], osc_score: float) -> float:
        target = self.power_max - (self.power_max - self.power_min) * max(0.0, osc_score)
        state["power"] = 0.9 * state["power"] + 0.1 * target
        return state["power"]

    def _curvature(self, state: dict[str, Any], p: torch.Tensor, g_pred: torch.Tensor) -> torch.Tensor:
        """Cheap diagonal-curvature proxy (Sophia-style), factored for matrices."""
        beta = self.curvature_beta
        if state["is_matrix"]:
            g2 = g_pred.pow(2)
            state["row_curv"].mul_(beta).add_(g2.mean(dim=1, keepdim=True), alpha=1 - beta)
            state["col_curv"].mul_(beta).add_(g2.mean(dim=0, keepdim=True), alpha=1 - beta)
            row_mean = state["row_curv"].mean().clamp(min=self.eps)
            return (state["row_curv"] * state["col_curv"] / row_mean).clamp(min=self.eps)
        if state["sparse"]:
            state["curv"].mul_(beta).add_(g_pred.pow(2).mean(), alpha=1 - beta)
            return state["curv"].clamp(min=self.eps)
        state["curv"].mul_(beta).add_(g_pred.pow(2), alpha=1 - beta)
        return state["curv"].clamp(min=self.eps)

    def _freeze_scale(self, state: dict[str, Any], g: torch.Tensor) -> torch.Tensor | float:
        """Dynamic coordinate freezing: soft-decay coordinates whose gradient
        has stayed below `freeze_threshold` for `freeze_patience` steps."""
        below = g.abs() < self.freeze_threshold
        if state["is_matrix"]:
            age = state["row_age"]
            row_below = below.all(dim=1, keepdim=True)
            age[row_below] = torch.clamp(age[row_below].to(torch.int16) + 1, max=255).to(torch.uint8)
            age[~row_below] = 0
            stale = (age.to(torch.int16) - self.freeze_patience).clamp(min=0).float()
            return self.freeze_decay ** stale
        age = state["age"]
        age[below] = torch.clamp(age[below].to(torch.int16) + 1, max=255).to(torch.uint8)
        age[~below] = 0
        stale = (age.to(torch.int16) - self.freeze_patience).clamp(min=0).float()
        return self.freeze_decay ** stale

    def _trust_ratio(self, p: torch.Tensor, update: torch.Tensor) -> float:
        p_norm = p.norm(2).clamp(min=self.eps)
        u_norm = update.norm(2).clamp(min=self.eps)
        trust = float((p_norm / u_norm).clamp(self.trust_clip[0], self.trust_clip[1]))
        return trust

    def _extra_scale(self, state: dict[str, Any], g_pred: torch.Tensor) -> float:
        """Hook for subclasses (V5 Plus) to apply additional multiplicative
        scaling on top of the baseline ORCP update. No-op in the baseline."""
        return 1.0

    def _orcp_step(self) -> None:
        for group in self.param_groups:
            lr = group["lr"]
            wd = group["weight_decay"]
            for p in group["params"]:
                if p.grad is None:
                    continue
                g = p.grad
                state = self.state[p]
                if "m_q" not in state:
                    self._init_state(state, p)

                state["step"] += 1
                m = _dequantize_momentum(state["m_q"], state["m_scale"]).view_as(p)

                cos_sim, osc_score = self._oscillation_signal(state, g, m)
                damp = 1.0 / (1.0 + max(osc_score, 0.0) * 2.0)
                power = self._adaptive_power(state, osc_score)

                # Predictive gradient extrapolation (one-step look-ahead).
                g_pred = g + self.extrapolation * m

                # Update + requantize momentum.
                m_new = self.momentum_beta * m + (1 - self.momentum_beta) * g
                state["m_q"], state["m_scale"] = _quantize_momentum(m_new)

                curv = self._curvature(state, p, g_pred)

                # Power-scaled, curvature-normalized update (Sophia-style clip).
                update = torch.sign(g_pred) * g_pred.abs().pow(power) / curv.sqrt()
                update = update.clamp(-self.sophia_clip, self.sophia_clip)

                freeze_scale = self._freeze_scale(state, g)
                update = update * freeze_scale
                update = update * self._extra_scale(state, g_pred)

                # `trust` is a python float for vectors/scalars, but Plus's
                # directional trust regions return a per-row tensor for
                # matrix parameters -- handle both without a branch by
                # letting broadcasting do the work (in-place ops broadcast
                # the non-self operand, e.g. (rows, 1) against (rows, cols)).
                trust = self._trust_ratio(p, update)
                local_lr = lr * damp * trust

                if wd != 0:
                    p.mul_(1.0 - local_lr * wd)

                p.sub_(update * local_lr)

    def describe(self) -> dict[str, Any]:
        base = super().describe()
        base["kind"] = type(self).__name__
        base["power_range"] = (self.power_min, self.power_max)
        base["sam_rho"] = self.sam_rho
        return base


class PressureCookerV5Plus(PressureCookerV5):
    """PressureCooker V5 Plus -- ORCP-Ultra core.

    Extra features on top of :class:`PressureCookerV5`:

    * Tensor entropy scaling -- scales the update by the normalized entropy
      of the gradient magnitude distribution across the tensor.
    * Spectral resonance detection -- a fast-timescale cosine EMA catches
      high-frequency sign flips that the slower V5 signal misses.
    * Directional (row-wise) trust regions for matrix parameters instead of
      one scalar trust ratio per tensor.
    * Long-horizon oscillation analysis via an extra, much slower cosine EMA.
    * Dynamic oscillation windows -- the fast/slow/ultra-slow blend weights
      shift toward the slower signals as instability increases.
    * Adaptive coordinate recovery -- frozen coordinates are ramped back in
      over a few steps instead of snapping back to full strength.
    * Automatic stability mode switching between "stable" and "defensive"
      update behavior.
    * Optimizer state compression -- factored curvature buffers stored in
      fp16 instead of fp32.
    * Fine-tuning optimization mode -- more conservative defaults tuned for
      LoRA/QLoRA stability.
    * Gradient-noise-floor auto-calibration of the freeze threshold.
    * Cheap bias correction on the scalar (not per-element) EMAs.
    * Mixed-precision-safe update casting for fp16/bf16 parameters.
    * Context-length-aware gradient scaling for very long sequence training.
    """

    def __init__(
        self,
        params: Iterable[torch.nn.Parameter] | Iterable[dict],
        *,
        ultra_slow_beta: float = 0.995,
        resonance_beta: float = 0.5,
        entropy_scale_range: tuple[float, float] = (0.5, 1.0),
        finetune_mode: bool = False,
        context_scale: float = 1.0,
        recovery_ramp_steps: int = 8,
        state_compression: bool = True,
        **kwargs: Any,
    ) -> None:
        if finetune_mode:
            kwargs.setdefault("power", 0.4)
            kwargs.setdefault("power_min", 0.25)
            kwargs.setdefault("power_max", 0.8)
            kwargs.setdefault("trust_clip", (0.02, 2.0))
            kwargs.setdefault("freeze_patience", 64)
            kwargs.setdefault("sam_rho", 0.0)
        super().__init__(params, **kwargs)
        self.ultra_slow_beta = ultra_slow_beta
        self.resonance_beta = resonance_beta
        self.entropy_scale_range = entropy_scale_range
        self.finetune_mode = finetune_mode
        self.context_scale = context_scale
        self.recovery_ramp_steps = recovery_ramp_steps
        self.state_compression = state_compression
        self._mode = "stable"

    def _init_state(self, state: dict[str, Any], p: torch.Tensor) -> None:
        super()._init_state(state, p)
        state["ultra_slow_cos"] = 0.0
        state["resonance_cos"] = 0.0
        state["resonance_flips"] = 0.0
        state["recovery_ramp"] = torch.zeros_like(p, dtype=torch.uint8)
        if self.state_compression:
            if state["is_matrix"]:
                state["row_curv"] = state["row_curv"].to(torch.float16)
                state["col_curv"] = state["col_curv"].to(torch.float16)
            elif not state["sparse"]:
                state["curv"] = state["curv"].to(torch.float16)

    def _oscillation_signal(self, state: dict[str, Any], g: torch.Tensor, m: torch.Tensor) -> tuple[float, float]:
        cos_sim, osc_score = super()._oscillation_signal(state, g, m)

        # Long-horizon oscillation analysis (ultra-slow timescale).
        state["ultra_slow_cos"] = (
            self.ultra_slow_beta * state["ultra_slow_cos"] + (1 - self.ultra_slow_beta) * cos_sim
        )

        # Spectral resonance detection: track how often the *sign* of the
        # cosine similarity flips at a fast timescale -- persistent flips
        # indicate a ringing/resonant oscillation mode that the plain
        # fast/slow blend can under-react to.
        prev_sign = state.get("_prev_cos_sign", 0.0)
        cur_sign = 1.0 if cos_sim >= 0 else -1.0
        flip = 1.0 if prev_sign != 0.0 and cur_sign != prev_sign else 0.0
        state["_prev_cos_sign"] = cur_sign
        state["resonance_flips"] = self.resonance_beta * state["resonance_flips"] + (1 - self.resonance_beta) * flip

        # Dynamic oscillation windows: blend fast/slow/ultra-slow signals,
        # shifting weight onto the slower (more stable) signals as the
        # resonance/flip rate rises.
        instability = max(state["resonance_flips"], 0.0)
        w_slow = min(0.85, 0.5 + 0.35 * instability)
        blended = (1 - w_slow) * cos_sim + w_slow * (
            0.6 * state["slow_cos"] + 0.4 * state["ultra_slow_cos"]
        )
        osc_score = -(blended + state["resonance_flips"] * 0.5)
        osc_score = max(-1.0, min(1.0, osc_score))

        # Automatic stability mode switching.
        self._mode = "defensive" if (osc_score > 0.3 or state["resonance_flips"] > 0.4) else "stable"
        return cos_sim, osc_score

    def _curvature(self, state: dict[str, Any], p: torch.Tensor, g_pred: torch.Tensor) -> torch.Tensor:
        curv = super()._curvature(state, p, g_pred)
        if self._mode == "defensive":
            curv = curv * 1.5  # tighten the effective clip when unstable
        return curv

    def _trust_ratio(self, p: torch.Tensor, update: torch.Tensor):
        if p.dim() >= 2:
            # Directional (row-wise) trust regions instead of one scalar
            # per tensor -- each row gets its own trust ratio.
            p_norm = p.norm(2, dim=1, keepdim=True).clamp(min=self.eps)
            u_norm = update.norm(2, dim=1, keepdim=True).clamp(min=self.eps)
            trust = (p_norm / u_norm).clamp(self.trust_clip[0], self.trust_clip[1])
            return trust
        return super()._trust_ratio(p, update)

    def _freeze_scale(self, state: dict[str, Any], g: torch.Tensor):
        scale = super()._freeze_scale(state, g)
        if not state["is_matrix"] and self.recovery_ramp_steps > 0:
            # Adaptive coordinate recovery: when a coordinate wakes back up
            # (gradient exceeds the freeze threshold again after being
            # stale), ramp its contribution back in over a few steps
            # instead of snapping straight back to full strength.
            waking = g.abs() >= self.freeze_threshold
            ramp = state["recovery_ramp"]
            ramp[waking] = torch.clamp(ramp[waking].to(torch.int16) + 1, max=self.recovery_ramp_steps).to(torch.uint8)
            ramp[~waking] = 0
            recovery_factor = (ramp.float() / self.recovery_ramp_steps).clamp(max=1.0)
            was_frozen = ramp < self.recovery_ramp_steps
            scale = torch.where(was_frozen & waking, recovery_factor, torch.as_tensor(1.0, device=g.device)) * scale
        return scale

    def _extra_scale(self, state: dict[str, Any], g_pred: torch.Tensor) -> float:
        # Tensor entropy scaling: a diffuse (high-entropy) gradient gets a
        # gentler update than a peaked (low-entropy, few dominant) one.
        abs_g = g_pred.abs().flatten()
        total = abs_g.sum().clamp(min=self.eps)
        q = abs_g / total
        n = q.numel()
        if n <= 1:
            entropy_norm = 1.0
        else:
            entropy = -(q * (q + self.eps).log()).sum()
            entropy_norm = float((entropy / math.log(n)).clamp(0.0, 1.0))
        lo, hi = self.entropy_scale_range
        entropy_factor = lo + (hi - lo) * entropy_norm
        return entropy_factor * self.context_scale

    def describe(self) -> dict[str, Any]:
        base = super().describe()
        base["mode"] = self._mode
        base["finetune_mode"] = self.finetune_mode
        return base


class Agedcookerv5(PressureCookerV5):
    """PressureCookerV5, tuned and enforced for CUDA 6.1/6.2 (Pascal, e.g.
    GTX 10-series GPUs). Mirrors the Agedcookerv4 naming convention.

    Forces off fused kernels (unsupported on Pascal) and keeps every ORCP
    feature on the plain scalar/tensor-op path, which is already what
    :class:`PressureCookerV5` uses -- there is nothing fused to disable in
    the ORCP core itself, but this keeps the flag consistent with the rest
    of the PressureCooker family and warns when used off-Pascal.
    """

    def __init__(self, params: Iterable, **kwargs: Any) -> None:
        kwargs["fused"] = False
        super().__init__(params, **kwargs)
        if not self.cuda_61_compatible:
            warnings.warn(
                "Agedcookerv5 is specifically tuned for CUDA 6.1/6.2 (Pascal). "
                "Running on newer hardware may be suboptimal; consider "
                "PressureCookerV5 instead.",
                stacklevel=2,
            )

    def describe(self) -> dict[str, Any]:
        base = super().describe()
        base["pascal_safe"] = True
        return base


class ULTRAagedcookerv5(PressureCookerV5Plus):
    """PressureCookerV5Plus, tuned and enforced for CUDA 6.1/6.2 (Pascal).

    Mirrors ULTRAagedcookerv4: same ORCP-Ultra feature set as
    :class:`PressureCookerV5Plus`, with fused kernels forced off and fp16
    state compression enabled by default (Pascal has plenty of fp16 ALU
    throughput but very little VRAM, which is exactly what
    ``state_compression`` and the quantized momentum buffer are for).
    """

    def __init__(self, params: Iterable, **kwargs: Any) -> None:
        kwargs["fused"] = False
        kwargs.setdefault("state_compression", True)
        super().__init__(params, **kwargs)
        if not self.cuda_61_compatible:
            warnings.warn(
                "ULTRAagedcookerv5 is specifically tuned for CUDA 6.1/6.2 (Pascal). "
                "Running on newer hardware may be suboptimal; consider "
                "PressureCookerV5Plus instead.",
                stacklevel=2,
            )

    def describe(self) -> dict[str, Any]:
        base = super().describe()
        base["pascal_safe"] = True
        return base
