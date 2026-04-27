"""flour — chat-quality logits processor.

Flour is what binds a dough together — without it the rest of the
ingredients fall apart on the countertop.  In hypernix, the
:class:`Flour` class binds together every chat-quality heuristic
you'd otherwise wire by hand on top of raw ``transformers``:

* **repetition penalty** (the OpenAI-style ``frequency_penalty`` /
  ``presence_penalty``),
* **no-repeat n-gram** blocking,
* **bad-word / phrase** suppression,
* **role-leak** suppression (strip ``"user:"`` / ``"<|im_start|>"``
  tokens the assistant would otherwise hallucinate),
* **stop-sequence** early termination,
* a smart ``smart_default()`` recipe that applies all of the above
  with values tuned for chat (not code completion).

A vanilla ``transformers`` chat loop has to combine
``LogitsProcessorList``, ``StoppingCriteriaList``,
``NoRepeatNGramLogitsProcessor``, ``RepetitionPenaltyLogitsProcessor``
and a separate ``BadWordsLogitsProcessor`` — one knob each, all
configured separately.  ``flour`` does it in one::

    from hypernix.flour import Flour

    f = Flour.smart_default(template="hyper-nix.2")

    bell = Bell(flour=f)            # works with hypernix.bell.Bell
    chat.say("hello")               # all heuristics applied automatically

Why this is "better than transformers for chatting":

1.  Stop sequences are matched on **decoded text**, not raw token
    ids — so ``"<|im_end|>"`` works even when the tokenizer splits
    it into 3 pieces.
2.  Role-leak suppression catches the failure mode where a
    half-trained chat model starts echoing ``user:`` and writing
    its own follow-up question.  Vanilla transformers has no
    primitive for this; hypernix's flour ships it on by default.
3.  All the knobs live on one dataclass, so a session config can
    be saved and reloaded as JSON without serialising
    ``LogitsProcessorList`` instances.

Flour does **not** require :class:`hypernix.bell.Bell` — you can
also call ``f.process(logits, produced_ids, decoded_so_far)``
directly inside any sampling loop.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import torch

# Forward-reference type hint to avoid circular import.
ChatTemplate = Any


# ---------------------------------------------------------------------------
# Built-in role-leak markers — strings the assistant should never
# emit because they belong to the chat-template scaffolding.
# ---------------------------------------------------------------------------

ROLE_LEAK_MARKERS: dict[str, tuple[str, ...]] = {
    "chatml": (
        "<|im_start|>", "<|im_end|>",
        "<|im_start|>user", "<|im_start|>system",
    ),
    "hyper-nix.2": (
        "<|im_start|>", "<|im_end|>",
        "<|im_start|>user", "<|im_start|>system",
    ),
    "llama3": (
        "<|start_header_id|>", "<|end_header_id|>", "<|eot_id|>",
        "<|start_header_id|>user<|end_header_id|>",
    ),
    "llama2": ("[INST]", "[/INST]", "<<SYS>>", "<</SYS>>"),
    "alpaca": ("### Instruction:", "### Response:"),
    "vicuna": ("USER:", "ASSISTANT:"),
    "plain":  ("user:", "system:", "assistant:"),
}


@dataclass
class Flour:
    """Chat-quality logits processor.

    Attributes:
        repetition_penalty: Multiplicative penalty applied to logits
            for tokens already produced.  ``1.0`` disables.  ``1.1``
            is the OpenAI default for chat.
        frequency_penalty: Linear penalty proportional to the *count*
            of each token in the produced sequence.
        presence_penalty: Linear penalty applied once per unique
            token already produced.
        no_repeat_ngram: If > 0, blocks any token that would close
            an n-gram already seen in the produced sequence.
        bad_words: Token-string blocklist.  Any token whose decoded
            form is in this set gets ``-inf`` logits.
        stop_sequences: Decoded-text suffixes that end the
            generation when matched.
        suppress_role_leaks: Adds the chat template's role markers
            to ``bad_words`` and ``stop_sequences`` automatically.
        template_name: Used to look up the right role markers when
            ``suppress_role_leaks=True``.
    """

    repetition_penalty: float = 1.0
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    no_repeat_ngram: int = 0
    bad_words: list[str] = field(default_factory=list)
    stop_sequences: list[str] = field(default_factory=list)
    suppress_role_leaks: bool = False
    template_name: str | None = None

    # Internal: cached lookup of bad-word token ids per tokenizer.
    _bad_word_id_cache: dict[int, list[int]] = field(
        default_factory=dict, repr=False, compare=False,
    )

    # ------------------------------------------------------------------
    # Recipes
    # ------------------------------------------------------------------

    @classmethod
    def smart_default(cls, *, template: str | None = None) -> Flour:
        """Reasonable defaults for chat: 1.1 repetition penalty,
        4-gram no-repeat, role-leak suppression on for the given
        template."""
        return cls(
            repetition_penalty=1.1,
            frequency_penalty=0.0,
            presence_penalty=0.0,
            no_repeat_ngram=4,
            bad_words=[],
            stop_sequences=[],
            suppress_role_leaks=template is not None,
            template_name=template,
        )

    @classmethod
    def aggressive(cls, *, template: str | None = None) -> Flour:
        """Heavier penalties for models that loop a lot."""
        return cls(
            repetition_penalty=1.3,
            frequency_penalty=0.5,
            presence_penalty=0.3,
            no_repeat_ngram=3,
            suppress_role_leaks=template is not None,
            template_name=template,
        )

    @classmethod
    def off(cls) -> Flour:
        """No-op flour — passes logits through unchanged."""
        return cls()

    # ------------------------------------------------------------------
    # Effective stop / bad-word lists
    # ------------------------------------------------------------------

    def effective_stop_sequences(self) -> list[str]:
        out = list(self.stop_sequences)
        if self.suppress_role_leaks and self.template_name:
            for s in ROLE_LEAK_MARKERS.get(self.template_name, ()):
                # Only the close-of-turn markers stop generation.
                if any(t in s for t in ("im_end", "eot_id", "</s>", "[/INST]")):
                    if s not in out:
                        out.append(s)
        return out

    def effective_bad_words(self) -> list[str]:
        out = list(self.bad_words)
        if self.suppress_role_leaks and self.template_name:
            for s in ROLE_LEAK_MARKERS.get(self.template_name, ()):
                if s not in out:
                    out.append(s)
        return out

    # ------------------------------------------------------------------
    # Stop-sequence detection (operates on decoded text)
    # ------------------------------------------------------------------

    def matched_stop(self, decoded_so_far: str) -> str | None:
        """Return the first stop sequence that ``decoded_so_far`` ends
        with, or ``None``.  Comparison is on decoded text, so token
        boundaries don't matter."""
        for s in self.effective_stop_sequences():
            if s and decoded_so_far.endswith(s):
                return s
        return None

    def strip_stop(self, decoded: str) -> str:
        """Strip a trailing stop sequence (and any whitespace before
        it) from ``decoded``, if present."""
        match = self.matched_stop(decoded)
        if match:
            return decoded[: -len(match)].rstrip()
        return decoded

    # ------------------------------------------------------------------
    # Logits processing
    # ------------------------------------------------------------------

    def process(
        self,
        logits: torch.Tensor,
        produced_ids: Sequence[int],
        *,
        tokenizer: Any | None = None,
    ) -> torch.Tensor:
        """Apply every active heuristic to a 1D / 2D logits tensor
        and return the result.

        ``logits`` shape: ``(vocab,)`` or ``(1, vocab)``.

        ``tokenizer`` is needed when ``bad_words`` or
        ``suppress_role_leaks`` is set — every other heuristic is
        tokenizer-free.
        """
        squeezed = logits.dim() == 1
        if squeezed:
            logits = logits.unsqueeze(0)
        out = logits.clone()

        # Patch (0.51.1): normalise produced_ids to a plain list of
        # ints up front so callers can pass a torch.Tensor / numpy
        # array / generator without tripping the ``if produced_ids``
        # ambiguity (was a TypeError on tensor input in 0.51.0).
        ids_list: list[int] = [int(t) for t in produced_ids]
        has_history = len(ids_list) > 0

        # 1. Repetition penalty (multiplicative).
        if self.repetition_penalty and self.repetition_penalty != 1.0 and has_history:
            ids = torch.tensor(
                sorted(set(ids_list)),
                device=out.device, dtype=torch.long,
            )
            seen = out[:, ids]
            out[:, ids] = torch.where(
                seen > 0,
                seen / self.repetition_penalty,
                seen * self.repetition_penalty,
            )

        # 2. Frequency penalty (linear in count).
        if self.frequency_penalty and has_history:
            counts: dict[int, int] = {}
            for tid in ids_list:
                counts[tid] = counts.get(tid, 0) + 1
            ids_l = list(counts.keys())
            ids_t = torch.tensor(ids_l, device=out.device, dtype=torch.long)
            cnts_t = torch.tensor(
                [counts[i] for i in ids_l],
                device=out.device, dtype=out.dtype,
            )
            out[:, ids_t] -= self.frequency_penalty * cnts_t

        # 3. Presence penalty (linear, once per unique token).
        if self.presence_penalty and has_history:
            uniq = torch.tensor(
                sorted(set(ids_list)),
                device=out.device, dtype=torch.long,
            )
            out[:, uniq] -= self.presence_penalty

        # 4. No-repeat n-gram.
        if self.no_repeat_ngram and len(ids_list) >= self.no_repeat_ngram:
            n = self.no_repeat_ngram
            tail = tuple(ids_list[-(n - 1):])
            banned: set[int] = set()
            for i in range(len(ids_list) - n + 1):
                if tuple(ids_list[i : i + n - 1]) == tail:
                    banned.add(ids_list[i + n - 1])
            if banned:
                ban_t = torch.tensor(
                    sorted(banned), device=out.device, dtype=torch.long,
                )
                out[:, ban_t] = float("-inf")

        # 5. Bad-words (resolved through the tokenizer when available).
        if tokenizer is not None:
            bad = self.effective_bad_words()
            if bad:
                ids = self._resolve_bad_word_ids(bad, tokenizer)
                if ids:
                    bad_t = torch.tensor(
                        ids, device=out.device, dtype=torch.long,
                    )
                    out[:, bad_t] = float("-inf")

        return out.squeeze(0) if squeezed else out

    # ------------------------------------------------------------------
    # Post-processing of a finished reply
    # ------------------------------------------------------------------

    def clean_reply(self, reply: str) -> str:
        """Strip trailing stop sequences, role markers and any
        half-emitted ``user:`` follow-on the model leaked in."""
        text = reply
        # Strip trailing stop seq (may already be done by the sampler,
        # but be defensive).
        text = self.strip_stop(text)
        # Cut at any role-leak marker.
        if self.suppress_role_leaks and self.template_name:
            markers = ROLE_LEAK_MARKERS.get(self.template_name, ())
            for m in markers:
                idx = text.find(m)
                if idx != -1:
                    text = text[:idx]
        # Generic "user: ..." leak.
        m = re.search(r"\n\s*(user|system)\s*:", text, flags=re.IGNORECASE)
        if m:
            text = text[: m.start()]
        return text.rstrip()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resolve_bad_word_ids(self, words: list[str], tokenizer: Any) -> list[int]:
        cache_key = id(tokenizer)
        cached = self._bad_word_id_cache.get(cache_key)
        if cached is not None and len(cached) >= len(words):
            return cached
        ids: list[int] = []
        for w in words:
            try:
                tids = tokenizer.encode(w, add_special_tokens=False)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(tids, list) and len(tids) == 1:
                ids.append(int(tids[0]))
        self._bad_word_id_cache[cache_key] = ids
        return ids


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def flour(
    *,
    repetition_penalty: float = 1.1,
    no_repeat_ngram: int = 4,
    template: str | None = "hyper-nix.2",
    aggressive: bool = False,
) -> Flour:
    """Quick constructor.  ``aggressive=True`` calls
    :meth:`Flour.aggressive`."""
    if aggressive:
        return Flour.aggressive(template=template)
    return Flour(
        repetition_penalty=repetition_penalty,
        no_repeat_ngram=no_repeat_ngram,
        suppress_role_leaks=template is not None,
        template_name=template,
    )


__all__ = [
    "Flour",
    "ROLE_LEAK_MARKERS",
    "flour",
]
