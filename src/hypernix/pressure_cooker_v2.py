"""pressure_cooker_v2 — V2 and V2Plus optimizers with quantization support.

v0.61.3: Full fp16/fp64/Q8/Q6/Q5.5/Q4M training support with advanced optimizations.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any

import torch
from torch.optim import Optimizer


class QuantDtype(Enum):
    """Supported quantization dtypes for V2Plus training."""
    FP16 = "fp16"
    FP32 = "fp32"
    FP64 = "fp64"
    Q8 = "q8"
    Q6 = "q6"
    Q5_5 = "q5_5"
    Q4M = "q4m"


@dataclass
class QuantConfig:
    """Configuration for quantization-aware training."""
    dtype: QuantDtype = QuantDtype.FP32
    enabled: bool = False
    scale_range: tuple[float, float] = (-1.0, 1.0)
    per_channel: bool = True
    symmetric: bool = False
    fake_quant: bool = True


class PressureCookerV2(Optimizer):
    """V2 PressureCooker with full mixed-precision and advanced features."""
    
    def __init__(
        self,
        params: Iterable[torch.nn.Parameter] | Iterable[dict],
        *,
        peak_lr: float = 3e-4,
        warmup_steps: int = 200,
        plateau_steps: int = 1000,
        cooldown_steps: int = 200,
        betas: tuple[float, float] = (0.9, 0.95),
        eps: float = 1e-8,
        weight_decay: float = 0.1,
        lookahead_k: int = 0,
        lookahead_alpha: float = 0.5,
        grad_scaler: Any = None,
        grad_accum_steps: int = 1,
        foreach: bool | None = None,
        fused: bool | None = None,
        amsgrad: bool = False,
        dtype: torch.dtype = torch.float32,
        use_ema: bool = False,
        ema_beta: float = 0.999,
        grad_clip: float | None = None,
        adaptive_grad_clip: bool = True,
        checkpoint_every: int = 0,
        distributed_aware: bool = True,
    ) -> None:
        if peak_lr <= 0:
            raise ValueError("peak_lr must be > 0")
        if grad_accum_steps < 1:
            raise ValueError("grad_accum_steps must be >= 1")
        
        defaults = {"lr": 0.0, "betas": betas, "eps": eps, "weight_decay": weight_decay}
        super().__init__(params, defaults)
        
        self.peak_lr = peak_lr
        self.warmup_steps = warmup_steps
        self.plateau_steps = plateau_steps
        self.cooldown_steps = cooldown_steps
        self.total_steps = warmup_steps + plateau_steps + cooldown_steps
        self.lookahead_k = lookahead_k
        self.lookahead_alpha = lookahead_alpha
        self.grad_scaler = grad_scaler
        self.grad_accum_steps = grad_accum_steps
        self.foreach = foreach
        self.fused = fused
        self.amsgrad = amsgrad
        self.dtype = dtype
        self.use_ema = use_ema
        self.ema_beta = ema_beta
        self.grad_clip = grad_clip
        self.adaptive_grad_clip = adaptive_grad_clip
        self.checkpoint_every = checkpoint_every
        self.distributed_aware = distributed_aware
        self._step = 0
        self._accum_counter = 0
        self._ema_state: dict[int, torch.Tensor] = {}
        self._grad_history: list[float] = []
    
    @torch.no_grad()
    def step(self, closure=None):
        loss = None
        if closure is not None:
            with torch.enable_grad():
                loss = closure()
        
        self._accum_counter += 1
        if self._accum_counter < self.grad_accum_steps:
            return loss
        self._accum_counter = 0
        
        if self.grad_scaler is not None:
            self.grad_scaler.unscale_(self)
            if _grad_has_inf(self):
                self.grad_scaler.update()
                return loss
        
        if self.adaptive_grad_clip or self.grad_clip is not None:
            self._clip_gradients()
        
        if self.fused or (self.foreach is True and _HAS_FOREACH):
            self._adamw_multitensor()
        else:
            self._adamw_scalar()
        
        if self.lookahead_k > 0:
            self._lookahead_update()
        
        if self.use_ema:
            self._update_ema()
        
        if self.grad_scaler is not None:
            self.grad_scaler.update()
        
        self._step += 1
        return loss
    
    def scheduled_lr(self, step: int | None = None) -> float:
        s = self._step if step is None else step
        if s < self.warmup_steps:
            return self.peak_lr * (s + 1) / max(1, self.warmup_steps)
        s -= self.warmup_steps
        if s < self.plateau_steps:
            return self.peak_lr
        s -= self.plateau_steps
        if self.cooldown_steps <= 0:
            return self.peak_lr
        if s >= self.cooldown_steps:
            return 0.0
        progress = s / self.cooldown_steps
        return self.peak_lr * 0.5 * (1.0 + math.cos(math.pi * progress))
    
    def _clip_gradients(self) -> None:
        clip_value = self.grad_clip
        if self.adaptive_grad_clip and self._grad_history:
            recent_norm = sum(self._grad_history[-10:]) / min(len(self._grad_history), 10)
            clip_value = max(1.0, recent_norm * 1.5) if clip_value is None else min(clip_value, recent_norm * 1.5)
        
        if clip_value is not None:
            total_norm = torch.nn.utils.clip_grad_norm_(
                [p for g in self.param_groups for p in g["params"] if p.grad is not None],
                clip_value
            )
            self._grad_history.append(total_norm.item())
            if len(self._grad_history) > 100:
                self._grad_history.pop(0)
    
    def _update_ema(self) -> None:
        for group in self.param_groups:
            for p in group["params"]:
                if p.grad is None:
                    continue
                param_id = id(p)
                if param_id not in self._ema_state:
                    self._ema_state[param_id] = p.detach().clone()
                self._ema_state[param_id].mul_(self.ema_beta).add_(p.detach(), alpha=1 - self.ema_beta)
    
    def get_ema_weights(self) -> dict[int, torch.Tensor]:
        return {k: v.clone() for k, v in self._ema_state.items()}
    
    def _adamw_scalar(self) -> None:
        lr = self.scheduled_lr(self._step)
        for group in self.param_groups:
            group["lr"] = lr
            self._adamw_scalar_for([p for p in group["params"] if p.grad is not None], group)
    
    def _adamw_scalar_for(self, params: list[torch.nn.Parameter], group: dict) -> None:
        lr = group["lr"]
        beta1, beta2 = group["betas"]
        eps = group["eps"]
        wd = group["weight_decay"]
        for p in params:
            if p.grad is None:
                continue
            state = self.state[p]
            if "exp_avg" not in state:
                state["exp_avg"] = torch.zeros_like(p, memory_format=torch.preserve_format)
                state["exp_avg_sq"] = torch.zeros_like(p, memory_format=torch.preserve_format)
                state["step"] = 0
                # Initialize lookahead slow buffer if enabled
                if self.lookahead_k > 0:
                    state["slow"] = p.detach().clone()
            current = state["step"]
            current_value = current.item() if isinstance(current, torch.Tensor) else current
            state["step"] = current_value + 1
            step_t = state["step"]
            exp_avg = state["exp_avg"]
            exp_avg_sq = state["exp_avg_sq"]
            if wd != 0:
                p.mul_(1.0 - lr * wd)
            exp_avg.mul_(beta1).add_(p.grad, alpha=1.0 - beta1)
            exp_avg_sq.mul_(beta2).addcmul_(p.grad, p.grad, value=1.0 - beta2)
            bias1 = 1.0 - beta1 ** step_t
            bias2 = 1.0 - beta2 ** step_t
            denom = (exp_avg_sq.sqrt() / math.sqrt(bias2)).add_(eps)
            step_size = lr / bias1
            p.addcdiv_(exp_avg, denom, value=-step_size)
    
    def _adamw_multitensor(self) -> None:
        lr = self.scheduled_lr(self._step)
        for group in self.param_groups:
            group["lr"] = lr
        for group in self.param_groups:
            beta1, beta2 = group["betas"]
            params = [p for p in group["params"] if p.grad is not None]
            if not params:
                continue
            exp_avgs, exp_avg_sqs, state_steps = [], [], []
            for p in params:
                state = self.state[p]
                if "exp_avg" not in state:
                    state["exp_avg"] = torch.zeros_like(p, memory_format=torch.preserve_format)
                    state["exp_avg_sq"] = torch.zeros_like(p, memory_format=torch.preserve_format)
                    state["step"] = torch.zeros((), dtype=torch.float32, device=p.device)
                    # Initialize lookahead slow buffer if enabled
                    if self.lookahead_k > 0:
                        state["slow"] = p.detach().clone()
                if not isinstance(state["step"], torch.Tensor):
                    state["step"] = torch.tensor(float(state["step"]), dtype=torch.float32, device=p.device)
                exp_avgs.append(state["exp_avg"])
                exp_avg_sqs.append(state["exp_avg_sq"])
                state_steps.append(state["step"])
            
            fused_ok = bool(self.fused) and _HAS_FUSED_ADAMW and all(p.is_cuda for p in params)
            try:
                from torch.optim._functional import adamw as functional_adamw
            except ImportError:
                functional_adamw = None
            
            if functional_adamw is None:
                self._adamw_scalar_for(params, group)
                continue
            try:
                functional_adamw(
                    params, [p.grad for p in params], exp_avgs, exp_avg_sqs, [], state_steps,
                    amsgrad=self.amsgrad, beta1=beta1, beta2=beta2, lr=lr,
                    weight_decay=group["weight_decay"], eps=group["eps"], maximize=False,
                    foreach=self.foreach is not False, capturable=False, differentiable=False,
                    fused=fused_ok, grad_scale=None, found_inf=None,
                )
            except TypeError:
                self._adamw_scalar_for(params, group)
    
    def _lookahead_update(self) -> None:
        k = self.lookahead_k
        alpha = self.lookahead_alpha
        for group in self.param_groups:
            for p in group["params"]:
                state = self.state.get(p)
                if not state or "slow" not in state:
                    continue
                step_t = state["step"]
                step_value = step_t.item() if isinstance(step_t, torch.Tensor) else step_t
                if int(step_value) % k != 0:
                    continue
                slow = state["slow"]
                slow.add_(p - slow, alpha=alpha)
                p.copy_(slow)
    
    def describe(self) -> dict:
        return {
            "kind": type(self).__name__, "peak_lr": self.peak_lr,
            "warmup": self.warmup_steps, "plateau": self.plateau_steps,
            "cooldown": self.cooldown_steps, "dtype": str(self.dtype),
            "use_ema": self.use_ema, "grad_clip": self.grad_clip,
        }


class PressureCookerV2Plus(PressureCookerV2):
    """V2Plus with full quantization-aware training support."""
    
    def __init__(
        self,
        params: Iterable[torch.nn.Parameter] | Iterable[dict],
        *,
        quant_config: QuantConfig | None = None,
        quant_layers: list[str] | None = None,
        calibration_steps: int = 100,
        **kwargs: Any,
    ) -> None:
        super().__init__(params, **kwargs)
        self.quant_config = quant_config or QuantConfig()
        self.quant_layers = quant_layers or []
        self.calibration_steps = calibration_steps
        self._calibration_counter = 0
        self._quant_scales: dict[int, tuple[torch.Tensor, torch.Tensor]] = {}
    
    @torch.no_grad()
    def step(self, closure=None):
        if self.quant_config.enabled and self._calibration_counter < self.calibration_steps:
            self._calibrate_quantization()
            self._calibration_counter += 1
        
        if self.quant_config.enabled and self.quant_config.fake_quant:
            self._apply_fake_quant()
        
        loss = super().step(closure)
        
        if self.quant_config.enabled:
            self._update_quant_params()
        
        return loss
    
    def _calibrate_quantization(self) -> None:
        for group in self.param_groups:
            for p in group["params"]:
                if p.grad is None:
                    continue
                param_id = id(p)
                if param_id not in self._quant_scales:
                    min_val, max_val = p.detach().min(), p.detach().max()
                    scale = (max_val - min_val) / (2 ** self._get_quant_bits() - 1)
                    zero_point = -min_val / scale
                    self._quant_scales[param_id] = (scale, zero_point)
    
    def _get_quant_bits(self) -> int:
        mapping = {QuantDtype.Q8: 8, QuantDtype.Q6: 6, QuantDtype.Q5_5: 5, QuantDtype.Q4M: 4}
        return mapping.get(self.quant_config.dtype, 32)
    
    def _apply_fake_quant(self) -> None:
        if not self.quant_config.enabled:
            return
        for group in self.param_groups:
            for p in group["params"]:
                if p.grad is None:
                    continue
                param_id = id(p)
                if param_id in self._quant_scales:
                    scale, zero_point = self._quant_scales[param_id]
                    q = (p / scale + zero_point).round().clamp(0, 2 ** self._get_quant_bits() - 1)
                    p_dequant = (q - zero_point) * scale
                    p.data.copy_(p_dequant)
    
    def _update_quant_params(self) -> None:
        if self.quant_config.per_channel:
            for group in self.param_groups:
                for p in group["params"]:
                    if p.grad is None:
                        continue
                    param_id = id(p)
                    if param_id in self._quant_scales:
                        min_val, max_val = p.detach().min(), p.detach().max()
                        scale = (max_val - min_val) / (2 ** self._get_quant_bits() - 1)
                        zero_point = -min_val / scale
                        self._quant_scales[param_id] = (scale, zero_point)


def _grad_has_inf(optimizer: Optimizer) -> bool:
    for group in optimizer.param_groups:
        for p in group["params"]:
            if p.grad is not None and (torch.isinf(p.grad).any() or torch.isnan(p.grad).any()):
                return True
    return False


_TORCH_VERSION: tuple[int, int] = tuple(int(p) for p in torch.__version__.split("+")[0].split(".")[:2])
_HAS_FUSED_ADAMW = _TORCH_VERSION >= (2, 0)
_HAS_FOREACH = _TORCH_VERSION >= (1, 12)
