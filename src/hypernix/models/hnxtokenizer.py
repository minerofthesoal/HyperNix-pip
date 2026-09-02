"""hypernix.models.hnxtokenizer — the tokenizer a GGUF carries with it.

A GGUF is self-describing about its vocabulary: ``tokenizer.ggml.tokens``
is the whole token list, ``tokenizer.ggml.merges`` the BPE ranks when
there are any, ``tokenizer.ggml.scores`` the unigram scores when it is a
SentencePiece model. That is enough to turn text into the ids the model
was trained on without a second file to keep in sync.

Two families, and the difference matters
----------------------------------------
**BPE** (``tokenizer.ggml.model == "gpt2"``) works on bytes mapped into
printable characters, then merges pairs in rank order. **SentencePiece**
(``"llama"``) scores whole pieces and picks the segmentation with the
best total score, with ``▁`` standing in for a space.

Both are implemented here in the straightforward way rather than the
fast way: rank-ordered merging for BPE, Viterbi over the scores for
SPM. A tokenizer that is subtly wrong is worse than a slow one — every
downstream token is drawn from a distribution the model never saw — so
this favours matching the reference behaviour.

What it will not do
-------------------
Guess. A file with no ``tokenizer.ggml.tokens`` gets ``None`` from
:func:`tokenizer_from_metadata`, and the caller says so, because
inventing an encoding produces output that reads as a broken model
rather than as a missing tokenizer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["GGUFTokenizer", "tokenizer_from_metadata"]


def _byte_to_unicode() -> dict[int, str]:
    """GPT-2's reversible byte<->unicode map.

    Byte-level BPE needs every byte to be a printable character with no
    whitespace, so the bytes that are not get shifted into a private
    range. Getting this wrong shows up only on non-ASCII input, which is
    exactly where nobody looks.
    """
    printable = (
        list(range(ord("!"), ord("~") + 1))
        + list(range(ord("¡"), ord("¬") + 1))
        + list(range(ord("®"), ord("ÿ") + 1))
    )
    mapping = {b: chr(b) for b in printable}
    spare = 0
    for byte in range(256):
        if byte not in mapping:
            mapping[byte] = chr(256 + spare)
            spare += 1
    return mapping


_BYTE_ENCODER = _byte_to_unicode()
_BYTE_DECODER = {ch: b for b, ch in _BYTE_ENCODER.items()}


@dataclass
class GGUFTokenizer:
    """The vocabulary and merge rules a GGUF carries."""

    kind: str
    tokens: list[str] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)
    merge_ranks: dict[tuple[str, str], int] = field(default_factory=dict)
    bos_id: int | None = None
    eos_id: int | None = None
    unknown_id: int | None = None
    _index: dict[str, int] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not self._index:
            self._index = {token: i for i, token in enumerate(self.tokens)}

    @property
    def vocab_size(self) -> int:
        return len(self.tokens)

    @property
    def stop_ids(self) -> tuple[int, ...]:
        return (self.eos_id,) if self.eos_id is not None else ()

    # -- encoding --------------------------------------------------------

    def encode(self, text: str, *, add_bos: bool = True) -> list[int]:
        if self.kind == "spm":
            ids = self._encode_spm(text)
        else:
            ids = self._encode_bpe(text)
        if add_bos and self.bos_id is not None:
            ids = [self.bos_id, *ids]
        return ids

    def _merge(self, symbols: list[str]) -> list[str]:
        """Apply BPE merges until no adjacent pair has a rank."""
        while len(symbols) > 1:
            best_rank = None
            best_at = -1
            for index in range(len(symbols) - 1):
                rank = self.merge_ranks.get((symbols[index], symbols[index + 1]))
                if rank is not None and (best_rank is None or rank < best_rank):
                    best_rank, best_at = rank, index
            if best_at < 0:
                break
            symbols[best_at:best_at + 2] = [symbols[best_at] + symbols[best_at + 1]]
        return symbols

    def _encode_bpe(self, text: str) -> list[int]:
        mapped = "".join(_BYTE_ENCODER[b] for b in text.encode("utf-8"))
        ids: list[int] = []
        for piece in self._merge(list(mapped)):
            index = self._index.get(piece)
            if index is None:
                # Fall back to the characters, which are single bytes and
                # therefore always in a byte-level vocabulary.
                ids.extend(
                    self._index[ch] for ch in piece if ch in self._index
                )
            else:
                ids.append(index)
        return ids

    def _encode_spm(self, text: str) -> list[int]:
        """Viterbi over the unigram scores — the best total, not the
        longest first. Greedy longest-match is the classic shortcut here
        and it silently produces a different segmentation."""
        prepared = "▁" + text.replace(" ", "▁")
        n = len(prepared)
        best = [float("-inf")] * (n + 1)
        back: list[tuple[int, int]] = [(-1, -1)] * (n + 1)
        best[0] = 0.0
        for end in range(1, n + 1):
            for start in range(max(0, end - 32), end):
                if best[start] == float("-inf"):
                    continue
                index = self._index.get(prepared[start:end])
                if index is None:
                    continue
                score = best[start] + (
                    self.scores[index] if index < len(self.scores) else 0.0
                )
                if score > best[end]:
                    best[end] = score
                    back[end] = (start, index)

        if best[n] == float("-inf"):
            # An unsegmentable string. Fall back per character rather than
            # returning nothing, so an unusual glyph degrades instead of
            # emptying the prompt.
            return [
                self._index.get(ch, self.unknown_id or 0)
                for ch in prepared
                if ch in self._index or self.unknown_id is not None
            ]
        ids: list[int] = []
        cursor = n
        while cursor > 0:
            start, index = back[cursor]
            ids.append(index)
            cursor = start
        return list(reversed(ids))

    # -- decoding --------------------------------------------------------

    def decode(self, ids) -> str:
        pieces = [
            self.tokens[int(i)] for i in ids if 0 <= int(i) < len(self.tokens)
        ]
        if self.kind == "spm":
            return "".join(pieces).replace("▁", " ")
        joined = "".join(pieces)
        raw = bytes(_BYTE_DECODER.get(ch, ord(ch) & 0xFF) for ch in joined)
        return raw.decode("utf-8", errors="replace")


def tokenizer_from_metadata(metadata: dict) -> GGUFTokenizer | None:
    """Build a tokenizer from a GGUF's metadata, or ``None`` if it has none."""
    tokens = metadata.get("tokenizer.ggml.tokens")
    if not tokens:
        return None
    tokens = [str(t) for t in tokens]

    declared = str(metadata.get("tokenizer.ggml.model", "")).lower()
    merges_raw = metadata.get("tokenizer.ggml.merges") or []
    scores = [float(s) for s in (metadata.get("tokenizer.ggml.scores") or [])]

    if declared in ("llama", "spm", "sentencepiece"):
        kind = "spm"
    elif declared in ("gpt2", "bpe"):
        kind = "bpe"
    else:
        # Decide by what is actually present rather than by a name we do
        # not recognise: merges mean BPE, scores mean SentencePiece.
        kind = "bpe" if merges_raw else ("spm" if scores else "bpe")

    ranks: dict[tuple[str, str], int] = {}
    for rank, entry in enumerate(merges_raw):
        parts = str(entry).split(" ")
        if len(parts) == 2:
            ranks[(parts[0], parts[1])] = rank

    def _token_id(*keys: str) -> int | None:
        for key in keys:
            if key in metadata:
                try:
                    value = int(metadata[key])
                except (TypeError, ValueError):
                    continue
                if 0 <= value < len(tokens):
                    return value
        return None

    return GGUFTokenizer(
        kind=kind,
        tokens=tokens,
        scores=scores,
        merge_ranks=ranks,
        bos_id=_token_id("tokenizer.ggml.bos_token_id"),
        eos_id=_token_id("tokenizer.ggml.eos_token_id"),
        unknown_id=_token_id("tokenizer.ggml.unknown_token_id"),
    )


def _describe(tokenizer: Any) -> str:  # pragma: no cover - debugging aid
    if tokenizer is None:
        return "no tokenizer in this file"
    return f"{tokenizer.kind} tokenizer, {tokenizer.vocab_size} tokens"
