"""sink — where the output goes.

A sink is the terminal node of a pans / microwave / training pipeline:
take an iterable of strings (or dicts), append them to a file.  Supports
optional rotation (one file per N bytes) and deduplication via an
in-memory hash set.

Companion to :mod:`hypernix.pans`: ``Sink.pour(FryingPan(source))``
ends up with a cleaned, line-separated file ready for training.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Sink:
    """Append-only text sink.

    ``path`` is the base path.  With ``rotate_bytes`` > 0 the sink
    rolls over to ``path.1``, ``path.2`` … when the current file passes
    the threshold — handy when a 24/7 scraper would otherwise fill a
    disk.  Set ``dedupe=True`` to keep a running SHA1 set and skip
    lines that have been written before.
    """

    path: Path | str
    rotate_bytes: int | None = None
    dedupe: bool = False
    _seen: set[str] = field(default_factory=set, init=False, repr=False)
    _written: int = field(default=0, init=False, repr=False)
    _rotation: int = field(default=0, init=False, repr=False)

    def _current_path(self) -> Path:
        base = Path(self.path)
        if self._rotation == 0:
            return base
        return base.with_name(f"{base.name}.{self._rotation}")

    def write(self, line: str) -> bool:
        """Append ``line`` (newline added if missing).  Returns True on
        write, False when ``dedupe=True`` suppressed a duplicate."""
        payload = line if line.endswith("\n") else line + "\n"
        if self.dedupe:
            h = hashlib.sha1(payload.encode("utf-8")).hexdigest()
            if h in self._seen:
                return False
            self._seen.add(h)
        p = self._current_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(payload)
        self._written += len(payload)
        if self.rotate_bytes and self._written >= self.rotate_bytes:
            self._rotation += 1
            self._written = 0
        return True

    def pour(self, iterable: Iterable[str]) -> Path:
        """Write every item of ``iterable`` to the sink; return the
        *current* path (useful right after construction).  Does not
        rotate the return value mid-iteration."""
        for item in iterable:
            self.write(str(item))
        return self._current_path()

    def write_json(self, obj: dict) -> bool:
        return self.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))

    def drain(self) -> None:
        """No-op right now — we open/close the file per-write for
        crash-safety.  Present so callers can stop thinking about
        whether the sink is buffered."""
        return

    def close(self) -> None:
        self.drain()

    def __enter__(self) -> Sink:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
