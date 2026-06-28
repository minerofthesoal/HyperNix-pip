"""table — a dead-simple tabular viewer.

Training produces two kinds of by-products worth inspecting: the
stdout log (``step``, ``loss`` per line) and any judge / preference
corpora emitted by :mod:`hypernix.mediocre_fridge`.  Both parse into
lists of dicts; :class:`Table` is a thin wrapper with ``.head``,
``.filter``, and ``.show`` so you can poke at them from a REPL without
reaching for pandas.

No dependencies beyond the standard library.  Column widths auto-size
from the data.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .mediocre_fridge import JUDGE_LABEL, JUDGE_PROMPT, JUDGE_RESPONSE
from .new_fridge import parse_training_log


@dataclass
class Table:
    """Minimal tabular view over ``rows``, a list of ``dict[str, Any]``."""

    rows: list[dict] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_rows(cls, rows: Iterable[dict]) -> Table:
        return cls(rows=list(rows))

    @classmethod
    def from_training_log(cls, path: Path | str) -> Table:
        """Load step/loss pairs from a training stdout capture."""
        text = Path(path).read_text(encoding="utf-8")
        pairs = parse_training_log(text)
        return cls(rows=[{"step": step, "loss": loss} for step, loss in pairs])

    @classmethod
    def from_judge_corpus(cls, path: Path | str) -> Table:
        """Load ``<JUDGE_PROMPT>...<JUDGE_LABEL>...`` lines."""
        rows: list[dict] = []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                prompt = line.split(JUDGE_PROMPT, 1)[1].split(JUDGE_RESPONSE, 1)[0]
                rest = line.split(JUDGE_RESPONSE, 1)[1]
                response = rest.split(JUDGE_LABEL, 1)[0]
                label = rest.split(JUDGE_LABEL, 1)[1]
            except IndexError:
                continue
            rows.append({"prompt": prompt, "response": response, "label": label})
        return cls(rows=rows)

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self.rows)

    def head(self, n: int = 10) -> list[dict]:
        return self.rows[: max(0, n)]

    def columns(self) -> list[str]:
        seen: list[str] = []
        for r in self.rows:
            for k in r:
                if k not in seen:
                    seen.append(k)
        return seen

    def filter(self, predicate: Callable[[dict], bool]) -> Table:
        return Table(rows=[r for r in self.rows if predicate(r)])

    def select(self, *columns: str) -> Table:
        """Drop every column not in ``columns``."""
        if not columns:
            return Table(rows=list(self.rows))
        return Table(rows=[{c: r.get(c) for c in columns} for r in self.rows])

    def sort_by(self, column: str, *, reverse: bool = False) -> Table:
        return Table(rows=sorted(self.rows, key=lambda r: r.get(column), reverse=reverse))

    # ------------------------------------------------------------------
    # Pretty-print
    # ------------------------------------------------------------------

    def show(self, n: int = 10, *, max_col_chars: int = 60) -> str:
        rows = self.head(n)
        if not rows:
            return "(empty table)"
        cols = self.columns()
        widths = {c: len(c) for c in cols}
        rendered: list[dict[str, str]] = []
        for r in rows:
            rr: dict[str, str] = {}
            for c in cols:
                s = str(r.get(c, ""))
                if len(s) > max_col_chars:
                    s = s[: max_col_chars - 1] + "…"
                rr[c] = s
                widths[c] = max(widths[c], len(s))
            rendered.append(rr)
        header = " | ".join(c.ljust(widths[c]) for c in cols)
        sep = "-+-".join("-" * widths[c] for c in cols)
        body = "\n".join(
            " | ".join(rr[c].ljust(widths[c]) for c in cols) for rr in rendered
        )
        footer = f"\n({len(self.rows)} rows total)" if len(self.rows) > n else ""
        return f"{header}\n{sep}\n{body}{footer}"

    def __repr__(self) -> str:
        return f"Table(rows={len(self.rows)}, columns={self.columns()})"
