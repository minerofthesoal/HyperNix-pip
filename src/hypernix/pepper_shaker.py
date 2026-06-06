"""pepper_shaker — sharper, higher-intensity perturbations.

Where :mod:`hypernix.salt_shaker` adds subtle flavor, pepper bites.
Use this when you want augmentations that change meaning or add
deliberate difficulty — hard-negative mining, typo-robustness
training, MLM-style masking.

Three tiers, coarsest to finest:

* :class:`SmallShaker`   — t1.  Random word masking.  Replaces a
                             fraction of whole words with a mask
                             token (``[MASK]`` by default).
* :class:`Dish`          — t2.  Typo injection: drops a random
                             character inside a word, then
                             duplicates a random character in a
                             different word.  Produces plausible
                             real-world typos.
* :class:`TallHandmade`  — t3.  Negation injection.  Prepends "NOT "
                             to a random token with probability
                             ``rate``; useful for training judges or
                             entailment models to handle negation.

Like the salt shakers, every pepper shaker shares a ``Shaker`` base
and plugs into :class:`hypernix.sink.Sink.pour`.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import ClassVar

from .salt_shaker import Shaker

# ---------------------------------------------------------------------------
# t1 — SmallShaker
# ---------------------------------------------------------------------------

@dataclass
class SmallShaker(Shaker):
    """Random word masking at ``rate``.  Replaces whole whitespace-
    separated tokens with ``mask_token``."""

    mask_token: str = "[MASK]"
    name: ClassVar[str] = "SmallShaker"

    def season(self, line: str) -> str:
        tokens = line.split()
        if not tokens:
            return line
        out = [
            self.mask_token if self._rng.random() < self.rate else t
            for t in tokens
        ]
        return " ".join(out)


# ---------------------------------------------------------------------------
# t2 — Dish
# ---------------------------------------------------------------------------

@dataclass
class Dish(Shaker):
    """Typo injection.  For each word with probability ``rate``,
    either drops a random internal character or duplicates one.
    Preserves first and last characters so words remain recognisable
    (the classic "jumbled letters still readable" effect)."""

    name: ClassVar[str] = "Dish"

    def _typo(self, word: str) -> str:
        if len(word) < 3:
            return word
        kind = self._rng.choice(("drop", "duplicate"))
        idx = self._rng.randint(1, len(word) - 2)
        if kind == "drop":
            return word[:idx] + word[idx + 1 :]
        return word[:idx] + word[idx] + word[idx:]

    def season(self, line: str) -> str:
        tokens = line.split()
        if not tokens:
            return line
        out = [
            self._typo(t) if self._rng.random() < self.rate else t
            for t in tokens
        ]
        return " ".join(out)


# ---------------------------------------------------------------------------
# t3 — TallHandmade
# ---------------------------------------------------------------------------

@dataclass
class TallHandmade(Shaker):
    """Negation injection.  Prepends ``negator`` ("NOT " by default)
    to a random token at ``rate``.  Useful for hard-negative mining
    and negation-robust classifier training."""

    negator: str = "NOT"
    name: ClassVar[str] = "TallHandmade"

    def season(self, line: str) -> str:
        tokens = line.split()
        if not tokens:
            return line
        out: list[str] = []
        for t in tokens:
            if self._rng.random() < self.rate:
                out.append(self.negator)
            out.append(t)
        return " ".join(out)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

TIERS: dict[str, type[Shaker]] = {
    "small-shaker": SmallShaker,
    "dish": Dish,
    "tall-handmade": TallHandmade,
}


def pepper_shaker(tier: str, source, **kw) -> Shaker:
    """Construct a pepper-shaker tier by short name."""
    key = tier.lower().replace("_", "-")
    if key not in TIERS:
        raise ValueError(
            f"unknown pepper tier {tier!r}; valid: {sorted(TIERS)}"
        )
    return TIERS[key](source=source, **kw)


def _iter_source(_src) -> Iterator[str]:  # pragma: no cover
    # Re-exported symbol for callers that want to iterate a raw source
    # without constructing a Shaker.  (Kept for API symmetry with
    # ``salt_shaker.Shaker._source_lines`` which is private.)
    if isinstance(_src, (list, tuple)):
        yield from _src
    elif hasattr(_src, "read"):
        for line in _src:
            yield line
    elif isinstance(_src, str):
        yield _src
    else:
        for item in _src:
            yield str(item)
