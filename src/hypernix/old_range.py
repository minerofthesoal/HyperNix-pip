"""old_range — scored rubric labeler with explainability.

Where :class:`hypernix.new_range.NewRange` returns just ``GOOD`` or
``BAD`` from a first-fail rule chain, ``old_range`` runs every rule,
collects per-rule scores in [0, 1], aggregates them with a weighted
mean, and converts the aggregate into a label via a threshold.

Each rule is a :class:`ScoredRule` — a callable returning a float in
[0, 1] (1.0 = perfect, 0.0 = clearly bad) plus a short reason string.
That makes :meth:`OldRange.label_with_breakdown` a useful triage tool
for "why was this example flagged?" questions during dataset cleanup.

This range also supports **reference-based** scoring: rules that need
the canonical answer (token overlap, keyword presence) consult
``OldRange.references`` keyed by prompt.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from .new_range import (
    DIGIT_RE,
    LABEL_BAD,
    LABEL_GOOD,
    MATH_TRIGGER_RE,
    REFUSAL_PATTERNS,
)

#: Score type alias. A None score means "this rule has no opinion on
#: this example" and is skipped by the aggregator (no spurious 1.0
#: vote from rules that don't apply).
Score = tuple[float | None, str]
ScoredRule = Callable[[str, str, dict], Score]


_TOKEN_RE = re.compile(r"\w+")

#: Stopwords stripped before token-overlap so common function words
#: ("is", "the", "of", …) don't make any wrong answer look partially
#: correct.
_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "have", "in", "is", "it", "its", "of", "on", "or", "that",
    "the", "this", "to", "was", "were", "will", "with",
})


def _tokens(text: str) -> set[str]:
    return {
        t.lower() for t in _TOKEN_RE.findall(text)
        if t.lower() not in _STOPWORDS
    }


# ---------------------------------------------------------------------------
# Built-in scored rules
# ---------------------------------------------------------------------------

def length_score(prompt: str, response: str, ctx: dict) -> Score:
    """1.0 for responses in [min_chars, soft_max_chars], 0.0 if empty,
    linearly drops past soft_max_chars to 0.0 at hard_max_chars."""
    n = len(response.strip())
    soft = ctx.get("soft_max_chars", 1024)
    hard = ctx.get("hard_max_chars", 4096)
    if n == 0:
        return 0.0, "empty"
    if n < ctx.get("min_chars", 1):
        return 0.0, f"too_short ({n} < min)"
    if n <= soft:
        return 1.0, f"len ok ({n})"
    if n >= hard:
        return 0.0, f"too_long ({n} > hard)"
    # Linear interpolation between soft and hard.
    return max(0.0, 1.0 - (n - soft) / max(1, (hard - soft))), f"len {n}"


def refusal_score(prompt: str, response: str, ctx: dict) -> Score:
    """0.0 if the response contains a refusal phrase, 1.0 otherwise."""
    low = response.lower()
    for p in REFUSAL_PATTERNS:
        if p in low:
            return 0.0, f"refusal: {p!r}"
    return 1.0, "no refusal"


def math_digit_score(prompt: str, response: str, ctx: dict) -> Score:
    """For math-y prompts: 1.0 if the response has digits, else 0.0.
    For non-math prompts: None (no opinion)."""
    if not MATH_TRIGGER_RE.search(prompt):
        return None, "non-math prompt"
    if DIGIT_RE.search(response):
        return 1.0, "has digit"
    return 0.0, "math prompt without digit"


def overlap_score(prompt: str, response: str, ctx: dict) -> Score:
    """Token-overlap with a reference answer in ``ctx['references']``.

    Returns None (no opinion) if no reference is present for this prompt.
    """
    refs = ctx.get("references", {})
    ref = refs.get(prompt)
    if ref is None:
        return None, "no reference"
    a, b = _tokens(ref), _tokens(response)
    if not a:
        return None, "empty reference"
    overlap = len(a & b) / len(a)
    return overlap, f"overlap {overlap:.2f}"


def keyword_score(prompt: str, response: str, ctx: dict) -> Score:
    """1.0 if the response contains every required keyword for this prompt.

    ``ctx['keywords']`` should be a dict ``{prompt: [must_contain, ...]}``.
    Returns None (no opinion) when there's no entry.
    """
    keywords = ctx.get("keywords", {}).get(prompt)
    if not keywords:
        return None, "no keywords"
    low = response.lower()
    hits = sum(1 for k in keywords if k.lower() in low)
    return hits / len(keywords), f"{hits}/{len(keywords)} keywords"


def repetition_score(prompt: str, response: str, ctx: dict) -> Score:
    """0.0 on long single-character runs, 1.0 otherwise."""
    min_run = ctx.get("min_repetition_run", 12)
    if len(response) < min_run:
        return 1.0, "short enough"
    for i in range(len(response) - min_run + 1):
        if len(set(response[i : i + min_run])) == 1:
            return 0.0, f"run of {min_run}× {response[i]!r}"
    return 1.0, "no long runs"


# ---------------------------------------------------------------------------
# OldRange
# ---------------------------------------------------------------------------

#: Sentinel for ``OldRange.fatal_rules`` meaning "every rule is fatal
#: at 0.0".  This is the default: a rule that scores exactly 0 is
#: stating "definitely BAD per my criteria", which shouldn't be
#: drowned out by other rules abstaining or partially passing.
ALL_RULES_FATAL: tuple[str, ...] = ("*",)


@dataclass
class OldRange:
    """Weighted-mean scored rubric with fatal-rule short-circuit.

    Each rule returns ``(score, reason)`` where score is a float in
    [0, 1] OR ``None`` (= "no opinion, skip this rule").

    The aggregate is the weighted mean over rules that did vote.
    Rules listed in ``fatal_rules`` short-circuit to ``BAD`` when they
    score 0.0 — this stops "no opinion" rules from drowning out a
    clearly-broken response.

    ``threshold`` is the cutoff between ``GOOD`` and ``BAD`` on the
    aggregate (default 0.5).

    ``weights`` maps rule names to floats; missing rules default to 1.0.
    """

    rules: list[ScoredRule] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)
    threshold: float = 0.5
    references: dict[str, str] = field(default_factory=dict)
    keywords: dict[str, list[str]] = field(default_factory=dict)
    soft_max_chars: int = 1024
    hard_max_chars: int = 4096
    min_chars: int = 1
    fatal_rules: tuple[str, ...] = ALL_RULES_FATAL

    def __post_init__(self) -> None:
        if not self.rules:
            self.rules = list(default_scored_rules())

    def _ctx(self) -> dict:
        return {
            "references": self.references,
            "keywords": self.keywords,
            "soft_max_chars": self.soft_max_chars,
            "hard_max_chars": self.hard_max_chars,
            "min_chars": self.min_chars,
        }

    def score(self, prompt: str, response: str) -> float:
        return self.label_with_breakdown(prompt, response)[1]

    def label_with_breakdown(
        self, prompt: str, response: str,
    ) -> tuple[str, float, list[tuple[str, float | None, str]]]:
        """Return ``(label, aggregate_score, [(rule_name, score, reason), ...])``.

        ``score`` is None for rules that abstained.  ``aggregate_score``
        is the weighted mean over the non-None scores; when a fatal
        rule scored 0 the label is forced to BAD regardless.
        """
        ctx = self._ctx()
        breakdown: list[tuple[str, float | None, str]] = []
        total = 0.0
        weight_sum = 0.0
        forced_bad = False
        for rule in self.rules:
            name = getattr(rule, "__name__", repr(rule))
            w = self.weights.get(name, 1.0)
            s, reason = rule(prompt, response, ctx)
            breakdown.append((name, s, reason))
            if s is None:
                continue
            if s == 0.0 and (
                "*" in self.fatal_rules or name in self.fatal_rules
            ):
                forced_bad = True
            total += w * s
            weight_sum += w
        agg = total / weight_sum if weight_sum else 0.0
        if forced_bad:
            return LABEL_BAD, agg, breakdown
        label = LABEL_GOOD if agg >= self.threshold else LABEL_BAD
        return label, agg, breakdown

    def label(self, prompt: str, response: str) -> str:
        return self.label_with_breakdown(prompt, response)[0]

    def __call__(self, prompt: str, response: str) -> str:
        return self.label(prompt, response)


def default_scored_rules() -> Iterable[ScoredRule]:
    return (
        length_score,
        refusal_score,
        math_digit_score,
        overlap_score,
        keyword_score,
        repetition_score,
    )


def old_range(
    *,
    references: dict[str, str] | None = None,
    keywords: dict[str, list[str]] | None = None,
    threshold: float = 0.5,
    weights: dict[str, float] | None = None,
) -> OldRange:
    return OldRange(
        rules=list(default_scored_rules()),
        weights=weights or {},
        threshold=threshold,
        references=references or {},
        keywords=keywords or {},
    )
