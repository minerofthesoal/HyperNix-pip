"""tupperware — automated dataset round splitting for multi-phase training.

Splits a chosen dataset into N training rounds with automatic step
budgets, per-round learning rates, and optional evaluation at the end
of each round.  Pairs naturally with :mod:`hypernix.pressure_cooker_v3`
and :mod:`hypernix.abbicus` for curriculum-style fine-tunes.

Usage::

    from hypernix.tupperware import Tupperware, TupperwareConfig

    box = Tupperware(TupperwareConfig(num_rounds=4, eval_each_round=True))
    plan = box.plan(num_tokens=120_000, param_count=80_000_000)
    slices = box.split_file("./corpus.txt", out_dir="./rounds")
    for rnd, cfg in enumerate(plan):
        train_on(slices[rnd], steps=cfg.steps, lr=cfg.lr)
        if cfg.eval_after:
            evaluate(...)
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RoundPlan:
    """One round of a multi-phase training schedule."""

    round_index: int
    steps: int
    lr: float
    warmup_steps: int
    cooldown_steps: int
    eval_after: bool
    token_start: int
    token_end: int

    @property
    def total_optimizer_steps(self) -> int:
        return self.warmup_steps + self.steps + self.cooldown_steps


@dataclass
class TupperwareConfig:
    """Configuration for round splitting and step/LR planning."""

    num_rounds: int = 3
    total_steps: int | None = None
    base_lr: float | None = None
    eval_each_round: bool = False
    eval_final_only: bool = False
    warmup_ratio: float = 0.05
    cooldown_ratio: float = 0.03
    min_steps_per_round: int = 50
    lr_decay_per_round: float = 0.85
    tokens_per_step: int = 512


def _optimal_base_lr(param_count: int) -> float:
    """Scale-aware LR heuristic (Chinchilla-style sqrt scaling)."""
    if param_count <= 0:
        return 3e-4
    ref = 7e7  # ~70M params reference (nano-llama scale)
    scale = math.sqrt(ref / max(param_count, 1))
    return min(6e-4, max(1e-5, 3e-4 * scale))


def _split_boundaries(total: int, parts: int) -> list[tuple[int, int]]:
    """Return ``[(start, end), ...]`` slices covering ``[0, total)``."""
    if parts < 1:
        raise ValueError("parts must be >= 1")
    if total <= 0:
        return [(0, 0)] * parts
    base, rem = divmod(total, parts)
    out: list[tuple[int, int]] = []
    start = 0
    for i in range(parts):
        size = base + (1 if i < rem else 0)
        out.append((start, start + size))
        start += size
    return out


class Tupperware:
    """Automated dataset round splitter with step/LR planning."""

    def __init__(self, config: TupperwareConfig | None = None) -> None:
        self.config = config or TupperwareConfig()
        if self.config.num_rounds < 1:
            raise ValueError("num_rounds must be >= 1")

    def plan(
        self,
        *,
        num_tokens: int,
        param_count: int = 0,
        total_steps: int | None = None,
    ) -> list[RoundPlan]:
        """Build per-round step budgets and learning rates.

        Step count defaults to ``num_tokens / (tokens_per_step * num_rounds)``
        when ``total_steps`` is not set on the config or passed here.
        """
        cfg = self.config
        steps_budget = total_steps or cfg.total_steps
        if steps_budget is None:
            tps = max(1, cfg.tokens_per_step)
            steps_budget = max(
                cfg.min_steps_per_round * cfg.num_rounds,
                num_tokens // (tps * cfg.num_rounds),
            )

        per_round = max(cfg.min_steps_per_round, steps_budget // cfg.num_rounds)
        base_lr = cfg.base_lr if cfg.base_lr is not None else _optimal_base_lr(param_count)
        token_slices = _split_boundaries(num_tokens, cfg.num_rounds)

        warmup = max(1, int(per_round * cfg.warmup_ratio))
        cooldown = max(1, int(per_round * cfg.cooldown_ratio))
        core_steps = max(1, per_round - warmup - cooldown)

        plans: list[RoundPlan] = []
        for i in range(cfg.num_rounds):
            lr = base_lr * (cfg.lr_decay_per_round ** i)
            eval_after = cfg.eval_each_round and (
                not cfg.eval_final_only or i == cfg.num_rounds - 1
            )
            t_start, t_end = token_slices[i]
            plans.append(
                RoundPlan(
                    round_index=i,
                    steps=core_steps,
                    lr=lr,
                    warmup_steps=warmup,
                    cooldown_steps=cooldown,
                    eval_after=eval_after,
                    token_start=t_start,
                    token_end=t_end,
                )
            )
        return plans

    def split_lines(self, lines: list[str]) -> list[list[str]]:
        """Split text lines evenly across rounds."""
        n = len(lines)
        bounds = _split_boundaries(n, self.config.num_rounds)
        return [lines[s:e] for s, e in bounds]

    def split_file(self, dataset_path: Path | str, out_dir: Path | str) -> list[Path]:
        """Write one text file per round; return paths in order."""
        src = Path(dataset_path)
        if not src.exists():
            raise FileNotFoundError(f"dataset not found: {src}")
        dest = Path(out_dir)
        dest.mkdir(parents=True, exist_ok=True)

        text = src.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        if not lines:
            lines = [text] if text else [""]

        chunks = self.split_lines(lines)
        paths: list[Path] = []
        stem = src.stem
        for i, chunk in enumerate(chunks):
            out = dest / f"{stem}.round{i + 1:02d}.txt"
            out.write_text("".join(chunk), encoding="utf-8")
            paths.append(out)
        return paths

    def run_rounds(
        self,
        plans: list[RoundPlan],
        dataset_paths: list[Path | str],
        train_fn: Callable[[Path, RoundPlan], Any],
        eval_fn: Callable[[Path, RoundPlan, Any], dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Execute ``train_fn`` per round; optionally ``eval_fn`` after each."""
        if len(plans) != len(dataset_paths):
            raise ValueError("plans and dataset_paths must have the same length")

        results: list[dict[str, Any]] = []
        for plan, path in zip(plans, dataset_paths, strict=True):
            train_out = train_fn(Path(path), plan)
            entry: dict[str, Any] = {
                "round": plan.round_index,
                "steps": plan.steps,
                "lr": plan.lr,
                "dataset": str(path),
                "train_result": train_out,
            }
            if plan.eval_after and eval_fn is not None:
                entry["eval"] = eval_fn(Path(path), plan, train_out)
            results.append(entry)
        return results

    def describe(self) -> dict[str, Any]:
        """Return a JSON-serializable summary of the config."""
        return {
            "kind": "Tupperware",
            "num_rounds": self.config.num_rounds,
            "eval_each_round": self.config.eval_each_round,
            "eval_final_only": self.config.eval_final_only,
            "warmup_ratio": self.config.warmup_ratio,
            "cooldown_ratio": self.config.cooldown_ratio,
            "lr_decay_per_round": self.config.lr_decay_per_round,
        }


__all__ = [
    "RoundPlan",
    "Tupperware",
    "TupperwareConfig",
]
