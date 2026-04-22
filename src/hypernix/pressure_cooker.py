"""pressure_cooker — custom AdamW-based optimizer for training runs.

The pressure metaphor:

* **Warmup** — pressure builds: LR rises linearly from 0 to ``peak_lr``
  over ``warmup_steps``.
* **Plateau** — pressure holds: LR stays at ``peak_lr`` for
  ``plateau_steps``.
* **Cooldown** — pressure releases: LR cosine-decays to 0 over
  ``cooldown_steps``.
* **Lookahead seal** — every ``k`` inner steps, the "slow" weights
  are pulled toward the fast weights by a factor of ``alpha`` (the
  Zhang et al. 2019 Lookahead trick).  This is the pressure seal
  that keeps the fast weights from exploding.

Call :meth:`step` once per training step *after* ``loss.backward()``.
The LR schedule is driven by an internal step counter; you do not need
a separate ``torch.optim.lr_scheduler``.

Under the hood this is AdamW — so everything a vanilla
``torch.optim.AdamW`` consumer needs (parameter groups, weight
decay, betas) works the same way.
"""
from __future__ import annotations

import math
from collections.abc import Iterable

import torch
from torch.optim import Optimizer


class PressureCooker(Optimizer):
    """AdamW + warmup / plateau / cooldown schedule + lookahead."""

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
    ) -> None:
        if peak_lr <= 0:
            raise ValueError("peak_lr must be > 0")
        if warmup_steps < 0 or plateau_steps < 0 or cooldown_steps < 0:
            raise ValueError("schedule step counts must be >= 0")
        if not 0.0 <= lookahead_alpha <= 1.0:
            raise ValueError("lookahead_alpha must be in [0, 1]")

        defaults = {
            "lr": 0.0,                              # set from schedule on every step
            "betas": betas,
            "eps": eps,
            "weight_decay": weight_decay,
        }
        super().__init__(params, defaults)

        self.peak_lr = peak_lr
        self.warmup_steps = warmup_steps
        self.plateau_steps = plateau_steps
        self.cooldown_steps = cooldown_steps
        self.total_steps = warmup_steps + plateau_steps + cooldown_steps
        self.lookahead_k = lookahead_k
        self.lookahead_alpha = lookahead_alpha
        self._step = 0

    # ------------------------------------------------------------------
    # LR schedule
    # ------------------------------------------------------------------

    def scheduled_lr(self, step: int | None = None) -> float:
        """Return the LR that :meth:`step` would use at ``step`` (or the
        current internal step when ``None``)."""
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
        # Cosine from peak to 0.
        progress = s / self.cooldown_steps
        return self.peak_lr * 0.5 * (1.0 + math.cos(math.pi * progress))

    # ------------------------------------------------------------------
    # Step
    # ------------------------------------------------------------------

    @torch.no_grad()
    def step(self, closure=None):  # type: ignore[override]
        loss = None
        if closure is not None:
            with torch.enable_grad():
                loss = closure()

        lr = self.scheduled_lr(self._step)

        for group in self.param_groups:
            group["lr"] = lr
            beta1, beta2 = group["betas"]
            eps = group["eps"]
            wd = group["weight_decay"]

            for p in group["params"]:
                if p.grad is None:
                    continue
                grad = p.grad
                state = self.state[p]

                if "exp_avg" not in state:
                    state["exp_avg"] = torch.zeros_like(p, memory_format=torch.preserve_format)
                    state["exp_avg_sq"] = torch.zeros_like(p, memory_format=torch.preserve_format)
                    state["step"] = 0
                    if self.lookahead_k > 0:
                        state["slow"] = p.detach().clone()

                state["step"] += 1
                step_t = state["step"]
                exp_avg = state["exp_avg"]
                exp_avg_sq = state["exp_avg_sq"]

                # Decoupled weight decay — AdamW style.
                if wd != 0:
                    p.mul_(1.0 - lr * wd)

                exp_avg.mul_(beta1).add_(grad, alpha=1.0 - beta1)
                exp_avg_sq.mul_(beta2).addcmul_(grad, grad, value=1.0 - beta2)

                bias1 = 1.0 - beta1 ** step_t
                bias2 = 1.0 - beta2 ** step_t
                denom = (exp_avg_sq.sqrt() / math.sqrt(bias2)).add_(eps)
                step_size = lr / bias1
                p.addcdiv_(exp_avg, denom, value=-step_size)

                # Lookahead seal.
                if self.lookahead_k > 0 and step_t % self.lookahead_k == 0:
                    slow = state["slow"]
                    slow.add_(p - slow, alpha=self.lookahead_alpha)
                    p.copy_(slow)

        self._step += 1
        return loss

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def phase(self, step: int | None = None) -> str:
        """Return ``"warmup"`` / ``"plateau"`` / ``"cooldown"`` / ``"done"``
        for the current (or given) step."""
        s = self._step if step is None else step
        if s < self.warmup_steps:
            return "warmup"
        if s < self.warmup_steps + self.plateau_steps:
            return "plateau"
        if s < self.total_steps:
            return "cooldown"
        return "done"

    def __repr__(self) -> str:
        return (
            f"PressureCooker(peak_lr={self.peak_lr}, warmup={self.warmup_steps}, "
            f"plateau={self.plateau_steps}, cooldown={self.cooldown_steps}, "
            f"lookahead={f'k={self.lookahead_k}, alpha={self.lookahead_alpha}' if self.lookahead_k else 'off'})"
        )


def pressure_cooker(
    params: Iterable[torch.nn.Parameter] | Iterable[dict],
    **kwargs,
) -> PressureCooker:
    """Construct a :class:`PressureCooker` from keyword arguments."""
    return PressureCooker(params, **kwargs)
