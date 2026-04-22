"""pans — five progressive tiers of training-data preprocessing.

A *pan* reads text and yields processed strings.  Like cookware, each
pan applies more heat (transformation) than the one before it.  Chain
pans together with :class:`hypernix.sink.Sink` to write the output to
disk for training, or iterate them directly for use inline.

Tiers, lightest to heaviest:

1. :class:`FryingPan` — verbatim lines, lightly trimmed.
2. :class:`SaucePan`  — + whitespace normalization + empty-line drop.
3. :class:`Skillet`   — + chat/instruction formatting (role tags).
4. :class:`GrillPan`  — + hash-based deduplication + min-length filter.
5. :class:`Wok`       — + in-memory shuffle (and optional line-reversal
                          augmentation).

Every pan supports the same iterator protocol so callers can swap
tiers by name.
"""
from __future__ import annotations

import hashlib
import random
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

_WS_RE = re.compile(r"[ \t]+")
_MULTINEWLINE_RE = re.compile(r"\n{3,}")


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

@dataclass
class Pan:
    """Abstract pan.  Subclasses override :meth:`cook` (one line in,
    zero-or-one line out) or :meth:`iter` (full iterator override)."""

    source: Path | str | Iterable[str]
    name: str = "Pan"

    def _source_lines(self) -> Iterator[str]:
        if isinstance(self.source, (str, Path)):
            p = Path(self.source)
            with p.open(encoding="utf-8") as f:
                for line in f:
                    yield line.rstrip("\n")
        else:
            yield from self.source

    def cook(self, line: str) -> str | None:
        return line

    def iter(self) -> Iterator[str]:
        for raw in self._source_lines():
            out = self.cook(raw)
            if out is not None:
                yield out

    def __iter__(self) -> Iterator[str]:
        return self.iter()


# ---------------------------------------------------------------------------
# Tier 1 — FryingPan
# ---------------------------------------------------------------------------

@dataclass
class FryingPan(Pan):
    """Lightest tier.  Strip trailing whitespace, pass everything else
    through.  Useful when the input is already clean (already-formatted
    corpora, pre-tokenized chunks)."""

    name: str = "FryingPan"

    def cook(self, line: str) -> str | None:
        return line.rstrip()


# ---------------------------------------------------------------------------
# Tier 2 — SaucePan
# ---------------------------------------------------------------------------

@dataclass
class SaucePan(Pan):
    """Reduce.  Collapse runs of internal whitespace, drop empty lines,
    strip leading/trailing whitespace.  Standard mild cleaning for
    scraped or OCR'd text."""

    name: str = "SaucePan"

    def cook(self, line: str) -> str | None:
        line = _WS_RE.sub(" ", line.strip())
        return line or None


# ---------------------------------------------------------------------------
# Tier 3 — Skillet
# ---------------------------------------------------------------------------

@dataclass
class Skillet(Pan):
    """Versatile.  Applies chat / instruction formatting by wrapping
    each line with role tags.  ``mode='chat'`` yields
    ``<USER>line\\n<ASSISTANT>`` templates; ``mode='instruct'`` yields
    ``### Instruction: line\\n### Response:`` — use one when every input
    line is a user turn and the dataset is paired with assistant
    replies on the following line (or in a separate corpus).
    """

    name: str = "Skillet"
    mode: str = "chat"            # "chat" | "instruct"
    user_tag: str = "<USER>"
    assistant_tag: str = "<ASSISTANT>"

    def cook(self, line: str) -> str | None:
        line = line.strip()
        if not line:
            return None
        if self.mode == "instruct":
            return f"### Instruction: {line}\n### Response:"
        return f"{self.user_tag} {line}\n{self.assistant_tag}"


# ---------------------------------------------------------------------------
# Tier 4 — GrillPan
# ---------------------------------------------------------------------------

@dataclass
class GrillPan(Pan):
    """High direct heat.  SaucePan-style cleaning plus deduplication
    (SHA1 hash set) and a minimum length filter.  Safe on arbitrary
    web-scraped text: collapses boilerplate, drops single-word lines."""

    name: str = "GrillPan"
    min_chars: int = 8
    _seen: set[str] = field(default_factory=set, repr=False)

    def cook(self, line: str) -> str | None:
        line = _WS_RE.sub(" ", line.strip())
        if len(line) < self.min_chars:
            return None
        h = hashlib.sha1(line.encode("utf-8")).hexdigest()
        if h in self._seen:
            return None
        self._seen.add(h)
        return line


# ---------------------------------------------------------------------------
# Tier 5 — Wok
# ---------------------------------------------------------------------------

@dataclass
class Wok(Pan):
    """Heaviest.  Buffers the whole source in memory, shuffles it,
    and optionally injects line-reversal augmentation (``reverse_ratio``
    fraction of lines emitted in reverse word order).  Use this for
    small corpora where order-randomization matters and you can afford
    the memory."""

    name: str = "Wok"
    seed: int = 0
    reverse_ratio: float = 0.0

    def iter(self) -> Iterator[str]:
        # Pre-clean with SaucePan semantics.
        rng = random.Random(self.seed)
        buffer: list[str] = []
        for raw in self._source_lines():
            line = _WS_RE.sub(" ", raw.strip())
            if line:
                buffer.append(line)
        rng.shuffle(buffer)
        for line in buffer:
            if self.reverse_ratio > 0 and rng.random() < self.reverse_ratio:
                yield " ".join(reversed(line.split()))
            else:
                yield line


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

TIERS: dict[str, type[Pan]] = {
    "frying-pan": FryingPan,
    "sauce-pan": SaucePan,
    "skillet": Skillet,
    "grill-pan": GrillPan,
    "wok": Wok,
}


def pick_pan(tier: str, source: Path | str | Iterable[str], **kwargs: str) -> Pan:
    """Return a pan instance by tier name (``"frying-pan"``..``"wok"``)."""
    cls = TIERS[tier.lower().replace("_", "-")]
    return cls(source=source, **kwargs)
