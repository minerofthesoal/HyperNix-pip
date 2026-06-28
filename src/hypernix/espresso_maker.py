"""espresso_maker — high-pressure short-pull evaluation.

Espresso is the fast, concentrated, pressure-brewed cousin of drip
coffee.  In hypernix, :mod:`espresso_maker` is the fast, concentrated
counterpart to :class:`hypernix.coffee_maker.CoffeeMaker`: run a model
against a small prompt battery and get scores back quickly.  No
warmup, no schedule, no retries — just a pull.

Four tiers, matching espresso drink sizes:

* :class:`Ristretto` — the shortest pull.  One sample per prompt,
                        greedy decode (temp 0), tiny token budget.
                        Use it for deterministic spot-checks.
* :class:`SingleShot` — standard espresso.  One sample, default
                        sampling, moderate token budget.
* :class:`DoubleShot` — two samples per prompt; returns the better
                        one according to an optional scorer.
* :class:`Lungo`      — long pull.  Many samples, high temperature,
                        longer token budget.  Diverse outputs for
                        eyeballing creativity / coverage.

All four share a :meth:`pull` method: given a list of prompts
(optionally with reference answers) and an oven, return a list of
:class:`Shot` records.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Shot:
    prompt: str
    output: str
    score: float | None = None
    reference: str | None = None


@dataclass
class EspressoMaker:
    """Base espresso maker.  Subclasses set sampling parameters."""

    oven: Any
    max_new_tokens: int = 32
    temperature: float = 0.0
    top_k: int = 1
    top_p: float = 1.0
    samples_per_prompt: int = 1
    scorer: Callable[[str, str, str | None], float] | None = None
    name: str = "EspressoMaker"
    history: list[Shot] = field(default_factory=list)

    def _score(self, prompt: str, output: str, reference: str | None) -> float | None:
        if self.scorer is None:
            return None
        return self.scorer(prompt, output, reference)

    def pull(
        self,
        prompts: Sequence[str],
        references: Sequence[str] | None = None,
    ) -> list[Shot]:
        """Generate ``samples_per_prompt`` samples per prompt, score
        each against its reference (if any), and return the best per
        prompt."""
        refs = list(references) if references is not None else [None] * len(prompts)
        if len(refs) != len(prompts):
            raise ValueError("len(prompts) != len(references)")
        out: list[Shot] = []
        for prompt, ref in zip(prompts, refs, strict=False):
            candidates: list[Shot] = []
            for _ in range(self.samples_per_prompt):
                gen = self.oven.complete(
                    prompt,
                    max_new_tokens=self.max_new_tokens,
                    temperature=self.temperature,
                    top_k=self.top_k, top_p=self.top_p,
                    stop=(), seed=None,
                )
                candidates.append(Shot(
                    prompt=prompt, output=gen,
                    score=self._score(prompt, gen, ref),
                    reference=ref,
                ))
            # Pick the best-scoring candidate; ties break on first.
            if any(c.score is not None for c in candidates):
                best = max(candidates, key=lambda s: (s.score or -1.0))
            else:
                best = candidates[0]
            out.append(best)
            self.history.append(best)
        return out

    @property
    def mean_score(self) -> float | None:
        scored = [s.score for s in self.history if s.score is not None]
        return sum(scored) / len(scored) if scored else None


# ---------------------------------------------------------------------------
# Tier 1 — Ristretto
# ---------------------------------------------------------------------------

@dataclass
class Ristretto(EspressoMaker):
    """Shortest pull.  Greedy decode, 16 tokens, single sample."""

    max_new_tokens: int = 16
    temperature: float = 0.0
    top_k: int = 1
    top_p: float = 1.0
    samples_per_prompt: int = 1
    name: str = "Ristretto"


# ---------------------------------------------------------------------------
# Tier 2 — SingleShot
# ---------------------------------------------------------------------------

@dataclass
class SingleShot(EspressoMaker):
    """Standard pull.  One sample, mild-temperature decode, 64 tokens."""

    max_new_tokens: int = 64
    temperature: float = 0.2
    top_k: int = 40
    top_p: float = 0.95
    samples_per_prompt: int = 1
    name: str = "SingleShot"


# ---------------------------------------------------------------------------
# Tier 3 — DoubleShot
# ---------------------------------------------------------------------------

@dataclass
class DoubleShot(EspressoMaker):
    """Two samples per prompt; the scorer picks the winner.  Provide
    ``scorer`` explicitly, otherwise the first sample always wins."""

    max_new_tokens: int = 96
    temperature: float = 0.4
    top_k: int = 40
    top_p: float = 0.95
    samples_per_prompt: int = 2
    name: str = "DoubleShot"


# ---------------------------------------------------------------------------
# Tier 4 — Lungo
# ---------------------------------------------------------------------------

@dataclass
class Lungo(EspressoMaker):
    """Long pull.  Many samples, high temperature, 256 tokens.  Good
    for "show me what the model thinks"; pair with a scorer to pick
    the winner."""

    max_new_tokens: int = 256
    temperature: float = 0.8
    top_k: int = 50
    top_p: float = 0.95
    samples_per_prompt: int = 4
    name: str = "Lungo"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

TIERS: dict[str, type[EspressoMaker]] = {
    "ristretto": Ristretto,
    "single-shot": SingleShot,
    "double-shot": DoubleShot,
    "lungo": Lungo,
}


def espresso_maker(
    tier: str, oven: Any, *, scorer=None, **kwargs: Any,
) -> EspressoMaker:
    """Construct a tier by name."""
    cls = TIERS[tier.lower().replace("_", "-")]
    return cls(oven=oven, scorer=scorer, **kwargs)


# Convenience shortcuts.
def ristretto(oven: Any, **kw: Any) -> Ristretto:
    return Ristretto(oven=oven, **kw)


def single_shot(oven: Any, **kw: Any) -> SingleShot:
    return SingleShot(oven=oven, **kw)


def double_shot(oven: Any, **kw: Any) -> DoubleShot:
    return DoubleShot(oven=oven, **kw)


def lungo(oven: Any, **kw: Any) -> Lungo:
    return Lungo(oven=oven, **kw)
