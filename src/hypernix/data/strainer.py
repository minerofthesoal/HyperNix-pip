"""strainer — drop low-quality rows from a dataset.

Four tiers, all sharing :meth:`filter` (returns the kept rows)
and :meth:`stats` (returns ``KeptDropped`` counts):

* :class:`Colander`     — t1.  Coarsest.  Drops only empty / None
                                 entries.
* :class:`FineMesh`     — t2.  Colander + length floor / ceiling.
* :class:`NutMilkBag`   — t3.  FineMesh + character-set whitelist
                                 (defaults to printable ASCII +
                                 common unicode).
* :class:`Cheesecloth`  — t4.  NutMilkBag + duplicate detection
                                 (Jaccard 8-gram).  The most
                                 selective tier; suitable for
                                 deduplicating eval sets.

Operates on dicts (``record["text"]``) or plain strings.  Pass
``key="prompt"`` (etc.) to point at a different field.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class KeptDropped:
    kept: int = 0
    dropped: int = 0
    reasons: dict[str, int] = field(default_factory=dict)

    def add(self, reason: str | None) -> None:
        if reason is None:
            self.kept += 1
        else:
            self.dropped += 1
            self.reasons[reason] = self.reasons.get(reason, 0) + 1


def _text_of(record: Any, key: str | None) -> str:
    if isinstance(record, str):
        return record
    if isinstance(record, dict):
        if key is None:
            for k in ("text", "content", "prompt"):
                if k in record:
                    return str(record[k])
            return ""
        return str(record.get(key, ""))
    return str(record)


# ---------------------------------------------------------------------------
# Tier 1 — Colander
# ---------------------------------------------------------------------------

@dataclass
class Colander:
    """Drops empty / None / whitespace-only entries."""

    key: str | None = None
    name: str = "Colander"
    last_stats: KeptDropped = field(default_factory=KeptDropped, init=False, repr=False)

    def _check(self, record: Any) -> str | None:
        if record is None:
            return "none"
        text = _text_of(record, self.key)
        if not text or not text.strip():
            return "empty"
        return None

    def filter(self, records: Iterable[Any]) -> list[Any]:
        kept: list[Any] = []
        stats = KeptDropped()
        for r in records:
            reason = self._check(r)
            stats.add(reason)
            if reason is None:
                kept.append(r)
        self.last_stats = stats
        return kept

    def stats(self) -> KeptDropped:
        return self.last_stats


# ---------------------------------------------------------------------------
# Tier 2 — FineMesh
# ---------------------------------------------------------------------------

@dataclass
class FineMesh(Colander):
    """Colander + length floor / ceiling."""

    name: str = "FineMesh"
    min_length: int = 4
    max_length: int = 8192

    def _check(self, record: Any) -> str | None:
        base = super()._check(record)
        if base is not None:
            return base
        text = _text_of(record, self.key)
        n = len(text)
        if n < self.min_length:
            return f"too-short<{self.min_length}"
        if n > self.max_length:
            return f"too-long>{self.max_length}"
        return None


# ---------------------------------------------------------------------------
# Tier 3 — NutMilkBag
# ---------------------------------------------------------------------------

@dataclass
class NutMilkBag(FineMesh):
    """FineMesh + a character-set whitelist."""

    name: str = "NutMilkBag"
    #: Maximum proportion of non-whitelisted chars before drop.
    bad_char_threshold: float = 0.05

    def _is_allowed(self, ch: str) -> bool:
        if ch.isprintable():
            return True
        if ch in "\n\t":
            return True
        return False

    def _check(self, record: Any) -> str | None:
        base = super()._check(record)
        if base is not None:
            return base
        text = _text_of(record, self.key)
        if not text:
            return None
        bad = sum(1 for ch in text if not self._is_allowed(ch))
        if bad / max(1, len(text)) > self.bad_char_threshold:
            return "non-printable"
        return None


# ---------------------------------------------------------------------------
# Tier 4 — Cheesecloth
# ---------------------------------------------------------------------------

@dataclass
class Cheesecloth(NutMilkBag):
    """NutMilkBag + 8-gram Jaccard near-duplicate detection."""

    name: str = "Cheesecloth"
    ngram_size: int = 8
    similarity_threshold: float = 0.85

    _seen_ngrams: list[set[str]] = field(default_factory=list, init=False, repr=False)

    def _ngrams(self, text: str) -> set[str]:
        n = self.ngram_size
        return {text[i : i + n] for i in range(len(text) - n + 1)}

    def _check(self, record: Any) -> str | None:
        base = super()._check(record)
        if base is not None:
            return base
        text = _text_of(record, self.key)
        ngrams = self._ngrams(text)
        if not ngrams:
            return None
        for prev in self._seen_ngrams:
            if not prev:
                continue
            inter = len(ngrams & prev)
            union = len(ngrams | prev)
            if union and (inter / union) >= self.similarity_threshold:
                return "duplicate"
        self._seen_ngrams.append(ngrams)
        return None

    def filter(self, records: Iterable[Any]) -> list[Any]:
        # Reset memo on each call so a second filter() doesn't dedupe
        # against rows from the previous run.
        self._seen_ngrams = []
        return super().filter(records)


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

TIERS = {
    "colander": Colander,
    "fine-mesh": FineMesh,
    "nut-milk-bag": NutMilkBag,
    "cheesecloth": Cheesecloth,
}


def strainer(tier: str = "fine-mesh", **kw):
    if tier not in TIERS:
        raise ValueError(f"unknown strainer tier {tier!r}; valid: {sorted(TIERS)}")
    return TIERS[tier](**kw)


def strain(records: Iterable[Any], tier: str = "fine-mesh", **kw) -> list[Any]:
    """One-shot helper.  ``strain(rows, tier=\"cheesecloth\")``."""
    return strainer(tier=tier, **kw).filter(records)


__all__ = [
    "Cheesecloth",
    "Colander",
    "FineMesh",
    "KeptDropped",
    "NutMilkBag",
    "TIERS",
    "strain",
    "strainer",
]
