"""food_processor — bulk text chopping / slicing / shredding.

A food processor turns bulky ingredients into ready-to-use pieces.
In hypernix, :mod:`food_processor` is the bulk-text counterpart to
the per-line toaster and per-file pan: it takes a large text blob
and chunks it into training-ready pieces.  Four blade tiers:

* :class:`ChopBlade`    — split on a separator (blank line by
                           default).  Fastest; preserves order.
* :class:`SliceBlade`   — fixed-length character slicing.  Produces
                           exactly ``slice_chars``-long pieces with
                           an optional ``overlap_chars`` of context.
* :class:`ShredBlade`   — whitespace-tokenized windowing.  Produces
                           ``window_tokens``-long windows sliding by
                           ``stride_tokens``.
* :class:`PureeBlade`   — whole-file blob as a single output, with
                           internal whitespace collapsed.

Each blade yields strings and pairs naturally with
:class:`hypernix.sink.Sink.pour` for on-disk output.
"""
from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

_WS_RE = re.compile(r"\s+")


def _read_text(source: Path | str) -> str:
    return Path(source).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Tier 1 — ChopBlade
# ---------------------------------------------------------------------------

@dataclass
class ChopBlade:
    """Split the file on ``separator`` and yield each non-empty piece."""

    source: Path | str
    separator: str = "\n\n"
    name: str = "ChopBlade"

    def __iter__(self) -> Iterator[str]:
        text = _read_text(self.source)
        for piece in text.split(self.separator):
            piece = piece.strip()
            if piece:
                yield piece


# ---------------------------------------------------------------------------
# Tier 2 — SliceBlade
# ---------------------------------------------------------------------------

@dataclass
class SliceBlade:
    """Fixed-length character slicing with optional overlap.  Good for
    turning a single huge document into training chunks of a known
    size."""

    source: Path | str
    slice_chars: int = 1024
    overlap_chars: int = 0
    name: str = "SliceBlade"

    def __iter__(self) -> Iterator[str]:
        text = _read_text(self.source)
        if self.slice_chars <= 0:
            raise ValueError("slice_chars must be > 0")
        step = max(1, self.slice_chars - self.overlap_chars)
        for i in range(0, len(text), step):
            piece = text[i : i + self.slice_chars]
            if piece.strip():
                yield piece
            if i + self.slice_chars >= len(text):
                break


# ---------------------------------------------------------------------------
# Tier 3 — ShredBlade
# ---------------------------------------------------------------------------

@dataclass
class ShredBlade:
    """Whitespace-tokenized sliding window."""

    source: Path | str
    window_tokens: int = 256
    stride_tokens: int = 128
    name: str = "ShredBlade"

    def __iter__(self) -> Iterator[str]:
        text = _read_text(self.source)
        tokens = text.split()
        if self.window_tokens <= 0:
            raise ValueError("window_tokens must be > 0")
        step = max(1, self.stride_tokens)
        for i in range(0, len(tokens), step):
            window = tokens[i : i + self.window_tokens]
            if not window:
                break
            yield " ".join(window)
            if i + self.window_tokens >= len(tokens):
                break


# ---------------------------------------------------------------------------
# Tier 4 — PureeBlade
# ---------------------------------------------------------------------------

@dataclass
class PureeBlade:
    """The whole file as one output, with internal whitespace
    collapsed.  Use when you want a training example that's a single
    (cleaned) blob."""

    source: Path | str
    name: str = "PureeBlade"

    def __iter__(self) -> Iterator[str]:
        text = _read_text(self.source)
        cleaned = _WS_RE.sub(" ", text).strip()
        if cleaned:
            yield cleaned


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

TIERS: dict[str, type] = {
    "chop": ChopBlade,
    "slice": SliceBlade,
    "shred": ShredBlade,
    "puree": PureeBlade,
}


def food_processor(tier: str, source: Path | str, **kw):
    cls = TIERS[tier.lower().replace("_", "-")]
    return cls(source=source, **kw)
