"""industrial_range — LLM-as-judge labeler.

When you have access to a stronger model — a 70B Llama, a hosted
frontier API, or even a well-trained smaller HyperNix — use it as the
judge instead of relying on hand-rolled heuristics.  ``IndustrialRange``
wraps any object exposing a ``.complete(prompt, …)`` API (every
:class:`hypernix.old_oven.CodeOven` does) and produces ``GOOD`` /
``BAD`` labels by asking the judge directly.

It also supports **pairwise comparison** for preference-pair datasets
(:meth:`compare`) and an optional in-memory cache so repeated
``(prompt, response)`` queries don't re-bill the judge.

Drop a constructed instance into
:func:`hypernix.mediocre_fridge.collect_responses_from` as
``label_rule=judge`` exactly like a :class:`NewRange` or
:class:`OldRange`.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

LABEL_GOOD = "GOOD"
LABEL_BAD = "BAD"

DEFAULT_RUBRIC = (
    "You are evaluating a model's response to a prompt. Read the prompt and "
    "the response, then answer with exactly one word: GOOD if the response is "
    "correct, helpful, and on-topic; BAD if it is wrong, refused, empty, "
    "off-topic, or otherwise unhelpful."
)

DEFAULT_TEMPLATE = (
    "{rubric}\n\n"
    "PROMPT: {prompt}\n"
    "RESPONSE: {response}\n"
    "VERDICT:"
)

DEFAULT_PAIRWISE_RUBRIC = (
    "You are comparing two model responses to the same prompt. Read both "
    "and answer with exactly one letter: A if response A is better, B if "
    "response B is better, T if they are tied or both are equally bad."
)

DEFAULT_PAIRWISE_TEMPLATE = (
    "{rubric}\n\n"
    "PROMPT: {prompt}\n"
    "RESPONSE A: {a}\n"
    "RESPONSE B: {b}\n"
    "BETTER:"
)

# Cheap parse — the judge model is asked for a one-word verdict but
# may pad with whitespace, punctuation, or a short justification.
_GOOD_RE = re.compile(r"\bgood\b", re.IGNORECASE)
_BAD_RE = re.compile(r"\bbad\b", re.IGNORECASE)
_VERDICT_A = re.compile(r"\b[Aa]\b")
_VERDICT_B = re.compile(r"\b[Bb]\b")


@dataclass
class IndustrialRange:
    """LLM-as-judge labeler.

    ``judge`` must expose ``complete(prompt: str, max_new_tokens: int,
    temperature: float, stop: tuple[str, ...]) -> str`` — every CodeOven
    does, and so does any caller-supplied wrapper around an HTTP API.

    ``rubric`` is the system-style instruction prepended to every judge
    call.  ``template`` is the ``str.format``-able shape of the full
    judge prompt.  Defaults give you a workable pointwise GOOD/BAD
    judge out of the box.
    """

    judge: Any
    rubric: str = DEFAULT_RUBRIC
    template: str = DEFAULT_TEMPLATE
    pairwise_rubric: str = DEFAULT_PAIRWISE_RUBRIC
    pairwise_template: str = DEFAULT_PAIRWISE_TEMPLATE
    max_new_tokens: int = 8
    temperature: float = 0.0
    stop: tuple[str, ...] = ("\n", "PROMPT:", "RESPONSE:")
    cache: dict[tuple[str, ...], str] = field(default_factory=dict)
    use_cache: bool = True
    #: When True, an unparseable verdict falls back to BAD (conservative).
    fallback_label: str = LABEL_BAD

    # ------------------------------------------------------------------
    # Pointwise: label one (prompt, response) pair as GOOD / BAD
    # ------------------------------------------------------------------

    def label(self, prompt: str, response: str) -> str:
        if self.use_cache:
            key = ("point", prompt, response)
            if key in self.cache:
                return self.cache[key]

        judge_input = self.template.format(
            rubric=self.rubric, prompt=prompt, response=response,
        )
        out = self.judge.complete(
            judge_input,
            max_new_tokens=self.max_new_tokens,
            temperature=self.temperature,
            stop=self.stop,
        )
        verdict = self._parse_pointwise(out)
        if self.use_cache:
            self.cache[("point", prompt, response)] = verdict
        return verdict

    def __call__(self, prompt: str, response: str) -> str:
        return self.label(prompt, response)

    @staticmethod
    def _parse_pointwise(text: str) -> str:
        """Return GOOD / BAD from a free-form judge reply.

        Looks for a standalone GOOD or BAD token.  When both appear,
        whichever shows up first wins.  When neither, returns BAD
        (conservative — unlabelled examples shouldn't pollute the
        positive set).
        """
        good = _GOOD_RE.search(text)
        bad = _BAD_RE.search(text)
        if good and bad:
            return LABEL_GOOD if good.start() < bad.start() else LABEL_BAD
        if good:
            return LABEL_GOOD
        if bad:
            return LABEL_BAD
        return LABEL_BAD  # conservative default

    # ------------------------------------------------------------------
    # Pairwise: pick the better of two responses
    # ------------------------------------------------------------------

    def compare(self, prompt: str, a: str, b: str) -> str:
        """Return ``"A"``, ``"B"``, or ``"T"`` (tie)."""
        if self.use_cache:
            key = ("pair", prompt, a, b)
            if key in self.cache:
                return self.cache[key]

        judge_input = self.pairwise_template.format(
            rubric=self.pairwise_rubric, prompt=prompt, a=a, b=b,
        )
        out = self.judge.complete(
            judge_input,
            max_new_tokens=self.max_new_tokens,
            temperature=self.temperature,
            stop=self.stop,
        )
        verdict = self._parse_pairwise(out)
        if self.use_cache:
            self.cache[("pair", prompt, a, b)] = verdict
        return verdict

    @staticmethod
    def _parse_pairwise(text: str) -> str:
        """Return ``"A"`` / ``"B"`` / ``"T"`` from a free-form reply.

        Pass 1 (v0.50): also accept ``"tie"`` / ``"tied"`` /
        ``"equal"`` anywhere in the head, not just a leading ``T``.
        Previously ``"I think it's a tie"`` parsed as B.
        """
        head = text.strip()[:64]
        head_lower = head.lower()
        # Explicit tie words anywhere in the head win — they're
        # unambiguous.
        if any(w in head_lower for w in ("tie", "tied", "equal")):
            return "T"
        if head[:1].upper() == "T":
            return "T"
        ma = _VERDICT_A.search(head)
        mb = _VERDICT_B.search(head)
        if ma and mb:
            return "A" if ma.start() < mb.start() else "B"
        if ma:
            return "A"
        if mb:
            return "B"
        return "T"

    # ------------------------------------------------------------------
    # Batch convenience — sequential, but caches and short-circuits.
    # ------------------------------------------------------------------

    def label_batch(self, examples: Sequence[tuple[str, str]]) -> list[str]:
        return [self.label(p, r) for p, r in examples]

    def compare_batch(
        self, triples: Sequence[tuple[str, str, str]],
    ) -> list[str]:
        return [self.compare(p, a, b) for p, a, b in triples]


def industrial_range(judge: Any, **kwargs: Any) -> IndustrialRange:
    """Construct an :class:`IndustrialRange` around ``judge``.

    ``judge`` is anything with a ``.complete(prompt, max_new_tokens,
    temperature, stop)`` method — typically a CodeOven preheated from
    a stronger HF snapshot.
    """
    return IndustrialRange(judge=judge, **kwargs)
