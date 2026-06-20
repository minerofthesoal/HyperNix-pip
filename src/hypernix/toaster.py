"""toaster — quick per-line formatting.

Where :mod:`hypernix.pans` is for a whole dataset pass, the toaster
is for formatting you want to apply *per line* while reading.
Four tiers modelled on real toasters:

* :class:`TwoSliceToaster`  — pair adjacent lines as (prompt,
                               response) Q/A entries.
* :class:`FourSliceToaster` — batch four lines into a 2-turn chat
                               (user / assistant / user / assistant).
* :class:`ConveyorToaster`  — streaming mode.  Yields a formatted
                               entry for every line as it arrives —
                               useful when you're feeding the
                               formatter from a live log.
* :class:`ToasterOven`      — whole-document formatting.  Reads the
                               entire file, applies a single-pass
                               header / footer wrap, yields one
                               string per document (separated by a
                               blank line in the source).
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path


def _open_stream(source: Path | str | Iterable[str]) -> Iterator[str]:
    if isinstance(source, (str, Path)):
        with Path(source).open(encoding="utf-8") as f:
            for line in f:
                yield line.rstrip("\n")
    else:
        yield from source


# ---------------------------------------------------------------------------
# Tier 1 — TwoSliceToaster
# ---------------------------------------------------------------------------

@dataclass
class TwoSliceToaster:
    """Two lines in, one entry out.  ``line_a`` is treated as the
    prompt, ``line_b`` as the response.  The output is
    ``"{prompt_tag}{a}\\n{response_tag}{b}"`` per pair.
    """

    source: Path | str | Iterable[str]
    prompt_tag: str = "Q: "
    response_tag: str = "A: "
    name: str = "TwoSliceToaster"

    def __iter__(self) -> Iterator[str]:
        buf: list[str] = []
        for line in _open_stream(self.source):
            line = line.strip()
            if not line:
                continue
            buf.append(line)
            if len(buf) == 2:
                yield f"{self.prompt_tag}{buf[0]}\n{self.response_tag}{buf[1]}"
                buf = []


# ---------------------------------------------------------------------------
# Tier 2 — FourSliceToaster
# ---------------------------------------------------------------------------

@dataclass
class FourSliceToaster:
    """Four lines in, one 2-turn chat entry out."""

    source: Path | str | Iterable[str]
    user_tag: str = "<USER>"
    assistant_tag: str = "<ASSISTANT>"
    name: str = "FourSliceToaster"

    def __iter__(self) -> Iterator[str]:
        buf: list[str] = []
        for line in _open_stream(self.source):
            line = line.strip()
            if not line:
                continue
            buf.append(line)
            if len(buf) == 4:
                yield (
                    f"{self.user_tag} {buf[0]}\n"
                    f"{self.assistant_tag} {buf[1]}\n"
                    f"{self.user_tag} {buf[2]}\n"
                    f"{self.assistant_tag} {buf[3]}"
                )
                buf = []


# ---------------------------------------------------------------------------
# Tier 3 — ConveyorToaster
# ---------------------------------------------------------------------------

@dataclass
class ConveyorToaster:
    """Streaming per-line formatter.  Wraps every line in a supplied
    template.  Matches the ``str.format``-friendly shape
    ``"{line}"`` — default template is ``"<TEXT>{line}</TEXT>"``.
    """

    source: Path | str | Iterable[str]
    template: str = "<TEXT>{line}</TEXT>"
    name: str = "ConveyorToaster"

    def __iter__(self) -> Iterator[str]:
        for line in _open_stream(self.source):
            line = line.rstrip()
            if not line:
                continue
            yield self.template.format(line=line)


# ---------------------------------------------------------------------------
# Tier 4 — ToasterOven
# ---------------------------------------------------------------------------

@dataclass
class ToasterOven:
    """Whole-document formatter.  Lines are grouped into documents
    separated by blank lines in the source; each document is
    bracketed by ``header`` / ``footer``."""

    source: Path | str | Iterable[str]
    header: str = "<DOCUMENT>"
    footer: str = "</DOCUMENT>"
    name: str = "ToasterOven"

    def __iter__(self) -> Iterator[str]:
        doc: list[str] = []
        for line in _open_stream(self.source):
            if not line.strip():
                if doc:
                    yield f"{self.header}\n" + "\n".join(doc) + f"\n{self.footer}"
                    doc = []
                continue
            doc.append(line.rstrip())
        if doc:
            yield f"{self.header}\n" + "\n".join(doc) + f"\n{self.footer}"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

TIERS: dict[str, type] = {
    "two-slice-toaster": TwoSliceToaster,
    "four-slice-toaster": FourSliceToaster,
    "conveyor-toaster": ConveyorToaster,
    "toaster-oven": ToasterOven,
}


def toaster(tier: str, source, **kw):
    cls = TIERS[tier.lower().replace("_", "-")]
    return cls(source=source, **kw)
