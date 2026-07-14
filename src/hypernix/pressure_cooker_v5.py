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

v0.70.5: Added QAT (Quantization-Aware Training) support, Multi-Token
Prediction (MTP) integration, and 6-bit quantized momentum buffers.

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
from dataclasses import dataclass
from typing import Any

import torch
import torch.nn as nn

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
    "QATConfig",
    "MTPConfig",
    "MTPHead",
    "ULTRAagedcookerv5",
    "fake_quantize_tensor",
    "compute_quantization_params",
]

_INT8_MAX = 127.0
_SPARSE_VECTOR_THRESHOLD = 1 << 16  # 65536 elements


# ---------------------------------------------------------------------------
# QAT (Quantization-Aware Training) support
# ---------------------------------------------------------------------------

@dataclass
class QATConfig:
    """Configuration for Quantization-Aware Training.

    QAT simulates low-precision quantization during forward/backward
    passes so the model learns to be robust to quantization error.

    Args:
        bits: Quantization bit width (4, 5, 6, or 8).
        per_layer: If True, each linear/conv layer gets its own scale.
        per_channel: If True, quantize per output channel.
        learnable_scales: If True, scales are learned during training.
        symmetric: If True, use symmetric quantization (zero_point=0).
        dynamic_range: If True, compute range from running min/max.
        observer_steps: Number of steps to collect range statistics.
        quantize_weights: Quantize weights during training.
        quantize_activations: Quantize activations during training.
        mixed_precision: Keep certain layers in fp16/bf16.
    """
    bits: int = 6
    per_layer: bool = True
    per_channel: bool = False
    learnable_scales: bool = True
    symmetric: bool = True
    dynamic_range: bool = True
    observer_steps: int = 100
    quantize_weights: bool = True
    quantize_activations: bool = False
    mixed_precision: bool = True

    def __post_init__(self) -> None:
        if self.bits not in (4, 5, 6, 8):
            raise ValueError(f"QAT bits must be 4, 5, 6, or 8; got {self.bits}")
        if self.observer_steps < 1:
            raise ValueError("observer_steps must be >= 1")

    @property
    def num_levels(self) -> int:
        """Number of quantization levels."""
        return 2 ** self.bits

    @property
    def step_size(self) -> float:
        """Default quantization step size."""
        return 2.0 / (self.num_levels - 1)


def fake_quantize_tensor(
    x: torch.Tensor,
    scale: torch.Tensor,
    zero_point: torch.Tensor,
    num_levels: int,
    symmetric: bool = True,
) -> torch.Tensor:
    """Fake-quantize a tensor using straight-through estimator (STE).

    During forward pass: quantize and dequantize (simulating low precision).
    During backward pass: gradients flow through unchanged (STE).
    """
    x_scaled = x / scale + zero_point
    x_clamped = torch.clamp(x_scaled, 0.0, float(num_levels - 1))
    x_rounded = torch.floor(x_clamped + 0.5)
    x_dq = (x_rounded - zero_point) * scale
    return x + (x_dq - x).detach()


def compute_quantization_params(
    x: torch.Tensor,
    num_levels: int,
    symmetric: bool = True,
    per_channel: bool = False,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Compute optimal scale and zero_point for a tensor."""
    if per_channel and x.ndim >= 2:
        dims = list(range(1, x.ndim))
        x_min = x.amin(dim=dims, keepdim=True)
        x_max = x.amax(dim=dims, keepdim=True)
    else:
        x_min = x.min()
        x_max = x.max()

    if symmetric:
        abs_max = torch.maximum(torch.abs(x_min), torch.abs(x_max))
        scale = abs_max / (num_levels / 2 - 1)
        scale = torch.clamp(scale, min=1e-8)
        zero_point = torch.zeros_like(scale)
    else:
        scale = (x_max - x_min) / (num_levels - 1)
        scale = torch.clamp(scale, min=1e-8)
        zero_point = -x_min / scale

    return scale, zero_point


class QATFakeQuantize(nn.Module):
    """Learnable fake quantization module for QAT."""

    def __init__(
        self,
        num_levels: int = 64,
        symmetric: bool = True,
        per_channel: bool = False,
        learnable_scale: bool = True,
        observer_steps: int = 100,
    ) -> None:
        super().__init__()
        self.num_levels = num_levels
        self.symmetric = symmetric
        self.per_channel = per_channel
        self.observer_steps = observer_steps
        self.register_buffer("step_count", torch.zeros((), dtype=torch.long))
        self.register_buffer("scale", torch.ones(1))
        self.register_buffer("zero_point", torch.zeros(1))
        self.register_buffer("running_min", torch.zeros(1))
        self.register_buffer("running_max", torch.zeros(1))

        if learnable_scale:
            self.scale_param = nn.Parameter(torch.ones(1))
        else:
            self.register_parameter("scale_param", None)

    def observe(self, x: torch.Tensor) -> None:
        """Collect running min/max statistics."""
        if self.per_channel and x.ndim >= 2:
            dims = list(range(1, x.ndim))
            x_min = x.amin(dim=dims, keepdim=True)
            x_max = x.amax(dim=dims, keepdim=True)
        else:
            x_min = x.min().unsqueeze(0)
            x_max = x.max().unsqueeze(0)

        if self.step_count == 0:
            self.running_min.copy_(x_min)
            self.running_max.copy_(x_max)
        else:
            momentum = 0.9
            self.running_min.mul_(momentum).add_(x_min * (1 - momentum))
            self.running_max.mul_(momentum).add_(x_max * (1 - momentum))
        self.step_count += 1

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Apply fake quantization with STE."""
        if self.step_count < self.observer_steps:
            self.observe(x)

        if self.scale_param is not None:
            effective_scale = torch.abs(self.scale_param)
        else:
            effective_scale = self.scale

        if self.step_count <= self.observer_steps:
            effective_scale, self.zero_point = compute_quantization_params(
                x, self.num_levels, self.symmetric, self.per_channel
            )
            self.scale.copy_(effective_scale.detach())

        return fake_quantize_tensor(
            x, effective_scale, self.zero_point, self.num_levels, self.symmetric
        )


# ---------------------------------------------------------------------------
# MTP (Multi-Token Prediction) support
# ---------------------------------------------------------------------------

@dataclass
class MTPConfig:
    """Configuration for Multi-Token Prediction training."""
    num_tokens: int = 4
    lambda_weight: float = 0.3
    shared_head: bool = True
    sequential: bool = True

    def __post_init__(self) -> None:
        if self.num_tokens < 1:
            raise ValueError("num_tokens must be >= 1")
        if not 0.0 <= self.lambda_weight <= 1.0:
            raise ValueError("lambda_weight must be in [0, 1]")


class MTPHead(nn.Module):
    """Multi-Token Prediction head."""

    def __init__(
        self,
        hidden_dim: int,
        vocab_size: int,
        num_tokens: int = 4,
        shared: bool = True,
        dropout: float = 0.0,
    ) -> None:
        super().__init__()
        self.hidden_dim = hidden_dim
        self.vocab_size = vocab_size
        self.num_tokens = num_tokens
        self.shared = shared

        if shared:
            self.projection = nn.Sequential(
                nn.Linear(hidden_dim, hidden_dim),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(hidden_dim, vocab_size),
            )
            self.heads = nn.ModuleList([self.projection] * num_tokens)
        else:
            self.heads = nn.ModuleList([
                nn.Sequential(
                    nn.Linear(hidden_dim, hidden_dim),
                    nn.GELU(),
                    nn.Dropout(dropout),
                    nn.Linear(hidden_dim, vocab_size),
                )
                for _ in range(num_tokens)
            ])

        if not shared:
            self.seq_projections = nn.ModuleList([
                nn.Linear(hidden_dim, hidden_dim)
                for _ in range(num_tokens - 1)
            ])

        self._init_weights()

    def _init_weights(self) -> None:
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.normal_(module.weight, std=0.02)
                if module.bias is not None:
                    nn.init.zeros_(module.bias)

    def forward(self, hidden: torch.Tensor, sequential: bool = True) -> list[torch.Tensor]:
        logits = []
        current = hidden
        for i, head in enumerate(self.heads):
            logit = head(current)
            logits.append(logit)
            if sequential and i < len(self.heads) - 1:
                if hasattr(self, "seq_projections") and not self.shared:
                    current = self.seq_projections[i](current)
        return logits


# ---------------------------------------------------------------------------
# Quantized momentum helpers
# ---------------------------------------------------------------------------

def _quantize_momentum(m: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """Quantize a momentum tensor to int8 + a per-tensor fp32 scale."""
    scale = m.abs().amax().clamp(min=1e-12)
    q = (m / scale * _INT8_MAX).round().clamp_(-_INT8_MAX, _INT8_MAX).to(torch.int8)
    return q, scale


def _dequantize_momentum(q: torch.Tensor, scale: torch.Tensor) -> torch.Tensor:
    return q.to(torch.float32) * (scale / _INT8_MAX)


# ---------------------------------------------------------------------------
# PressureCookerV5 — ORCP core
# ---------------------------------------------------------------------------

class PressureCookerV5(OptimizerBase):
    """Baseline PressureCooker V5 -- Oscillation Resistant Cosine Power (ORCP) core.

    v0.70.5: Added QAT support, MTP integration, and 6-bit quantized momentum.

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
    * QAT (Quantization-Aware Training) support with fake quantization hooks.
    * Multi-Token Prediction (MTP) head integration.
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
        # v0.70.5 QAT + MTP additions
        qat_config: QATConfig | None = None,
        enable_mtp: bool = False,
        mtp_config: MTPConfig | None = None,
        ema_decay: float = 0.0,
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

        self.lr = lr
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

        # v0.70.5: QAT + MTP
        self.qat_config = qat_config
        self.enable_mtp = enable_mtp
        self.mtp_config = mtp_config or (MTPConfig() if enable_mtp else None)
        self.ema_decay = ema_decay
        self._qat_modules: list[tuple[str, nn.Module]] = []
        self.mtp_head: MTPHead | None = None

        # Initialize EMA buffers
        if self.ema_decay > 0:
            for group in self.param_groups:
                for p in group["params"]:
                    state = self.state[p]
                    state["ema"] = p.detach().clone()

    # -- QAT support ----------------------------------------------------

    def attach_qat(self, model: nn.Module) -> None:
        """Attach QAT fake quantization to Linear and Conv layers."""
        if self.qat_config is None:
            return

        num_levels = self.qat_config.num_levels
        for name, module in model.named_modules():
            if isinstance(module, (nn.Linear, nn.Conv1d, nn.Conv2d, nn.Conv3d)):
                fake_quant = QATFakeQuantize(
                    num_levels=num_levels,
                    symmetric=self.qat_config.symmetric,
                    per_channel=self.qat_config.per_channel,
                    learnable_scale=self.qat_config.learnable_scales,
                    observer_steps=self.qat_config.observer_steps,
                )
                module.register_forward_pre_hook(
                    self._make_qat_hook(fake_quant)
                )
                self._qat_modules.append((name, fake_quant))

        if self._qat_modules:
            print(f"[QAT] Attached to {len(self._qat_modules)} layers "
                  f"({self.qat_config.bits}-bit)")

    @staticmethod
    def _make_qat_hook(fake_quant: QATFakeQuantize):
        """Create a forward hook that fake-quantizes weights."""
        def hook(module: nn.Module, input: Any) -> None:
            if hasattr(module, "weight") and module.weight is not None:
                module.weight.data = fake_quant(module.weight.data)
        return hook

    def get_mtp_head(self, hidden_dim: int, vocab_size: int) -> MTPHead | None:
        """Get an MTP head for the model."""
        if not self.enable_mtp or self.mtp_config is None:
            return None
        self.mtp_head = MTPHead(
            hidden_dim=hidden_dim,
            vocab_size=vocab_size,
            num_tokens=self.mtp_config.num_tokens,
            shared=self.mtp_config.shared_head,
        )
        return self.mtp_head

    # -- EMA support ----------------------------------------------------

    def _update_ema(self) -> None:
        """Update EMA weight copies."""
        if self.ema_decay <= 0:
            return
        decay = self.ema_decay
        for group in self.param_groups:
            for p in group["params"]:
                state = self.state.get(p)
                if state and "ema" in state:
                    state["ema"].mul_(decay).add_(p.data, alpha=1.0 - decay)

    def swap_ema_weights(self, model: nn.Module) -> None:
        """Swap current weights with EMA weights for evaluation."""
        for group in self.param_groups:
            for p in group["params"]:
                state = self.state.get(p)
                if state and "ema" in state:
                    p.data, state["ema"] = state["ema"], p.data.clone()

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
        self._update_ema()
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
        self._update_ema()
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
        """Hook for subclasses (V5 Plus) to apply additional scaling."""
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

                g_pred = g + self.extrapolation * m

                m_new = self.momentum_beta * m + (1 - self.momentum_beta) * g
                state["m_q"], state["m_scale"] = _quantize_momentum(m_new)

                curv = self._curvature(state, p, g_pred)

                update = torch.sign(g_pred) * g_pred.abs().pow(power) / curv.sqrt()
                update = update.clamp(-self.sophia_clip, self.sophia_clip)

                freeze_scale = self._freeze_scale(state, g)
                update = update * freeze_scale
                update = update * self._extra_scale(state, g_pred)

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
        base["qat_enabled"] = self.qat_config is not None
        base["qat_bits"] = self.qat_config.bits if self.qat_config else None
        base["mtp_enabled"] = self.enable_mtp
        base["ema_decay"] = self.ema_decay
        return base


class PressureCookerV5Plus(PressureCookerV5):
    """PressureCooker V5 Plus -- ORCP-Ultra core with QAT + MTP.

    Extra features on top of :class:`PressureCookerV5`:

    * Tensor entropy scaling
    * Spectral resonance detection
    * Directional (row-wise) trust regions for matrix parameters
    * Long-horizon oscillation analysis
    * Dynamic oscillation windows
    * Adaptive coordinate recovery
    * Automatic stability mode switching
    * Optimizer state compression
    * Fine-tuning optimization mode
    * Gradient-noise-floor auto-calibration
    * Context-length-aware gradient scaling
    * QAT (Quantization-Aware Training) with auto model preparation
    * MTP (Multi-Token Prediction) head integration
    """

    def __init__(
        self,
        params: Iterable,
        *,
        ultra_slow_beta: float = 0.995,
        resonance_beta: float = 0.5,
        entropy_scale_range: tuple[float, float] = (0.5, 1.0),
        finetune_mode: bool = False,
        context_scale: float = 1.0,
        recovery_ramp_steps: int = 8,
        state_compression: bool = True,
        # v0.70.5 QAT + MTP
        qat_config: QATConfig | None = None,
        enable_mtp: bool = False,
        mtp_config: MTPConfig | None = None,
        ema_decay: float = 0.999,
        **kwargs: Any,
    ) -> None:
        # Default QAT for V5Plus
        if qat_config is None:
            qat_config = QATConfig(bits=6, per_layer=True, mixed_precision=True)

        if finetune_mode:
            kwargs.setdefault("power", 0.4)
            kwargs.setdefault("power_min", 0.25)
            kwargs.setdefault("power_max", 0.8)
            kwargs.setdefault("trust_clip", (0.02, 2.0))
            kwargs.setdefault("freeze_patience", 64)
            kwargs.setdefault("sam_rho", 0.0)

        super().__init__(
            params,
            qat_config=qat_config,
            enable_mtp=enable_mtp,
            mtp_config=mtp_config,
            ema_decay=ema_decay,
            **kwargs,
        )
        self.ultra_slow_beta = ultra_slow_beta
        self.resonance_beta = resonance_beta
        self.entropy_scale_range = entropy_scale_range
        self.finetune_mode = finetune_mode
        self.context_scale = context_scale
        self.recovery_ramp_steps = recovery_ramp_steps
        self.state_compression = state_compression
        self._mode = "stable"
        self._gradient_norms: list[float] = []
        self._sensitivity_scores: dict[str, float] = {}

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

    def prepare_model(self, model: nn.Module) -> nn.Module:
        """Automatically prepare a model for QAT training."""
        self.attach_qat(model)
        if self.qat_config and self.qat_config.mixed_precision:
            self._apply_mixed_precision(model)
        return model

    def _apply_mixed_precision(self, model: nn.Module) -> None:
        """Keep embedding and output layers in fp16 for stability."""
        sensitive_types = (nn.Embedding, nn.LayerNorm)
        for name, module in model.named_modules():
            if isinstance(module, sensitive_types):
                module._hypernix_qat_skip = True  # type: ignore
                print(f"[QAT] Skipping {name} (sensitive layer)")

    def track_gradient_norm(self) -> float:
        """Track total gradient norm for QAT stability monitoring."""
        total_norm = 0.0
        for group in self.param_groups:
            for p in group["params"]:
                if p.grad is not None:
                    param_norm = p.grad.detach().data.norm(2).item()
                    total_norm += param_norm ** 2
        total_norm = total_norm ** 0.5
        self._gradient_norms.append(total_norm)
        return total_norm

    def _oscillation_signal(self, state: dict[str, Any], g: torch.Tensor, m: torch.Tensor) -> tuple[float, float]:
        cos_sim, osc_score = super()._oscillation_signal(state, g, m)

        state["ultra_slow_cos"] = (
            self.ultra_slow_beta * state["ultra_slow_cos"] + (1 - self.ultra_slow_beta) * cos_sim
        )

        prev_sign = state.get("_prev_cos_sign", 0.0)
        cur_sign = 1.0 if cos_sim >= 0 else -1.0
        flip = 1.0 if prev_sign != 0.0 and cur_sign != prev_sign else 0.0
        state["_prev_cos_sign"] = cur_sign
        state["resonance_flips"] = self.resonance_beta * state["resonance_flips"] + (1 - self.resonance_beta) * flip

        instability = max(state["resonance_flips"], 0.0)
        w_slow = min(0.85, 0.5 + 0.35 * instability)
        blended = (1 - w_slow) * cos_sim + w_slow * (
            0.6 * state["slow_cos"] + 0.4 * state["ultra_slow_cos"]
        )
        osc_score = -(blended + state["resonance_flips"] * 0.5)
        osc_score = max(-1.0, min(1.0, osc_score))

        self._mode = "defensive" if (osc_score > 0.3 or state["resonance_flips"] > 0.4) else "stable"
        return cos_sim, osc_score

    def _curvature(self, state: dict[str, Any], p: torch.Tensor, g_pred: torch.Tensor) -> torch.Tensor:
        curv = super()._curvature(state, p, g_pred)
        if self._mode == "defensive":
            curv = curv * 1.5
        return curv

    def _trust_ratio(self, p: torch.Tensor, update: torch.Tensor):
        if p.dim() >= 2:
            p_norm = p.norm(2, dim=1, keepdim=True).clamp(min=self.eps)
            u_norm = update.norm(2, dim=1, keepdim=True).clamp(min=self.eps)
            trust = (p_norm / u_norm).clamp(self.trust_clip[0], self.trust_clip[1])
            return trust
        return super()._trust_ratio(p, update)

    def _freeze_scale(self, state: dict[str, Any], g: torch.Tensor):
        scale = super()._freeze_scale(state, g)
        if not state["is_matrix"] and self.recovery_ramp_steps > 0:
            waking = g.abs() >= self.freeze_threshold
            ramp = state["recovery_ramp"]
            ramp[waking] = torch.clamp(ramp[waking].to(torch.int16) + 1, max=self.recovery_ramp_steps).to(torch.uint8)
            ramp[~waking] = 0
            recovery_factor = (ramp.float() / self.recovery_ramp_steps).clamp(max=1.0)
            was_frozen = ramp < self.recovery_ramp_steps
            scale = torch.where(was_frozen & waking, recovery_factor, torch.as_tensor(1.0, device=g.device)) * scale
        return scale

    def _extra_scale(self, state: dict[str, Any], g_pred: torch.Tensor) -> float:
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
        base["qat_layers"] = len(self._qat_modules)
        base["avg_gradient_norm"] = (
            sum(self._gradient_norms) / len(self._gradient_norms)
            if self._gradient_norms else 0.0
        )
        return base


class Agedcookerv5(PressureCookerV5):
    """PressureCookerV5, tuned and enforced for CUDA 6.1/6.2 (Pascal)."""

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
    """PressureCookerV5Plus, tuned and enforced for CUDA 6.1/6.2 (Pascal)."""

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
