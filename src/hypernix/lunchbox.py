"""lunchbox — pack an eval / judge dataset for the HuggingFace Hub.

The kitchen-idiom equivalent of bringing home-cooked food to work:
you pack the records into a single box with a consistent layout,
and whoever unpacks it at the other end gets something coherent.

Use this when you're uploading an eval-results dataset (each row is
one model response + score + metadata) or a judge-training corpus
and want to avoid the classic `CastError: Couldn't cast ...
because column names don't match` from the HuggingFace dataset
viewer.  That error fires when the Parquet shards on disk disagree
about the column set — for example, you added a ``latency_s``
field to your evaluator halfway through the run and appended newer
shards next to older ones.

``Lunchbox`` guarantees **one schema** for the whole dataset by:

1. Collecting every record as a plain Python dict.
2. Computing the superset of keys across all records.
3. Filling missing cells with ``None`` (translated to Arrow null on
   write).
4. Writing via :mod:`datasets` so the ``huggingface`` metadata key
   embedded in the Parquet file matches the actual column layout.

The :mod:`datasets` library is a lazy dependency — it's pulled in
via :func:`hypernix.deps.ensure` on first use, respecting
``HYPERNIX_AUTO_INSTALL=0``.

Usage::

    from hypernix.lunchbox import Lunchbox

    box = Lunchbox()
    for result in evaluation_run():
        box.add(
            id=result.id,
            category=result.category,
            difficulty=result.difficulty,
            tier=result.tier,
            prompt=result.prompt,
            reference=result.reference,
            model_response=result.response,
            keyword_score=result.kw_score,
            latency_s=result.latency,
            variant=result.variant,
            pipeline_meta=result.meta,
        )

    # Write locally:
    box.pack("eval.parquet")

    # Or push directly:
    box.push_to_hub("ray0rf1re/eval", token=os.environ["HF_TOKEN"])

``Lunchbox.validate()`` runs before every write and raises
``ValueError`` if a column has mixed incompatible types (e.g. some
rows store ``keyword_score`` as float and others as str).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import deps

# Recommended column set for HyperNix-emitted eval datasets.  Not
# enforced — you can pack any schema you like — but this is the one
# the rest of hypernix (industrial_range, espresso_maker, smoker)
# can emit naturally and what the HuggingFace dataset viewer expects
# for ``ray0rf1re/eval``-style repos.
EVAL_SCHEMA: tuple[str, ...] = (
    "id",
    "category",
    "difficulty",
    "tier",
    "prompt",
    "reference",
    "model_response",
    "keyword_score",
    "latency_s",
    "variant",
    "pipeline_meta",
)


@dataclass
class Lunchbox:
    """Consistent-schema dataset packager."""

    records: list[dict[str, Any]] = field(default_factory=list)
    #: Optional explicit column order.  When set, :meth:`pack` and
    #: :meth:`push_to_hub` emit columns in this order and raise
    #: ``ValueError`` on unknown keys.  When ``None`` (default), the
    #: superset of record keys is used and order is alphabetical.
    required_columns: tuple[str, ...] | None = None

    # ------------------------------------------------------------------
    # Adding records
    # ------------------------------------------------------------------

    def add(self, **fields: Any) -> None:
        """Append one record.  Extra keys are allowed; missing keys
        are tolerated at pack time (filled with None)."""
        if self.required_columns is not None:
            unknown = set(fields) - set(self.required_columns)
            if unknown:
                raise ValueError(
                    f"unknown columns {sorted(unknown)}; "
                    f"allowed: {sorted(self.required_columns)}",
                )
        self.records.append(fields)

    def extend(self, iterable: Iterable[dict[str, Any]]) -> None:
        for r in iterable:
            self.add(**r)

    def __len__(self) -> int:
        return len(self.records)

    # ------------------------------------------------------------------
    # Normalisation + validation
    # ------------------------------------------------------------------

    def columns(self) -> list[str]:
        if self.required_columns is not None:
            return list(self.required_columns)
        seen: set[str] = set()
        for r in self.records:
            seen.update(r.keys())
        return sorted(seen)

    def normalize(self) -> list[dict[str, Any]]:
        """Return the records with every row having every column,
        missing cells as ``None``."""
        cols = self.columns()
        return [{c: r.get(c) for c in cols} for r in self.records]

    def validate(self) -> None:
        """Raise ``ValueError`` if a column has mixed non-None types
        across rows (e.g. ``keyword_score`` as float in some rows and
        str in others)."""
        col_types: dict[str, type] = {}
        for row in self.records:
            for k, v in row.items():
                if v is None:
                    continue
                t = type(v)
                # Accept int<->float as compatible (Arrow unifies).
                if t is int:
                    t = float
                prev = col_types.get(k)
                if prev is None:
                    col_types[k] = t
                elif prev is not t and not (prev is float and t is float):
                    raise ValueError(
                        f"column {k!r} has mixed types: {prev.__name__} and "
                        f"{t.__name__}.  Parquet writers reject this.",
                    )

    # ------------------------------------------------------------------
    # Write / push
    # ------------------------------------------------------------------

    def _build_hf_dataset(self):
        """Return a ``datasets.Dataset`` over the normalised rows.
        Lazy-imports ``datasets`` and installs it via
        ``deps.ensure`` on first use."""
        self.validate()
        try:
            from datasets import Dataset
        except ModuleNotFoundError:
            deps.ensure(["datasets>=2.14"], reimport=["datasets"])
            from datasets import Dataset
        return Dataset.from_list(self.normalize())

    def pack(self, path: Path | str) -> Path:
        """Write a single Parquet file to ``path`` with a coherent
        schema.  Returns the written path."""
        ds = self._build_hf_dataset()
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        ds.to_parquet(str(p))
        return p

    def pack_jsonl(self, path: Path | str) -> Path:
        """Write one JSON object per line — same normalisation, but
        no Parquet / pyarrow dependency."""
        self.validate()
        import json

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        rows = self.normalize()
        with p.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False))
                f.write("\n")
        return p

    def push_to_hub(
        self,
        repo_id: str,
        *,
        token: str | None = None,
        private: bool = False,
        commit_message: str = "Update dataset via hypernix.lunchbox",
        split: str = "train",
    ) -> str:
        """Push the packed dataset to the HuggingFace Hub.  Uses
        ``datasets.Dataset.push_to_hub`` so the per-shard
        ``huggingface`` metadata is coherent with the actual column
        layout — this is the fix for the classic ``CastError:
        Couldn't cast ... because column names don't match`` seen in
        the Hub dataset viewer when parquet shards drift.
        """
        ds = self._build_hf_dataset()
        ds.push_to_hub(
            repo_id, token=token, private=private,
            commit_message=commit_message, split=split,
        )
        return f"https://huggingface.co/datasets/{repo_id}"

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def for_eval(cls) -> Lunchbox:
        """Return a Lunchbox pre-configured with the recommended
        eval-results column set (:data:`EVAL_SCHEMA`)."""
        return cls(required_columns=EVAL_SCHEMA)

    @classmethod
    def from_records(
        cls,
        records: Iterable[dict[str, Any]],
        required_columns: tuple[str, ...] | None = None,
    ) -> Lunchbox:
        box = cls(required_columns=required_columns)
        box.extend(records)
        return box


def lunchbox(
    records: Iterable[dict[str, Any]] | None = None,
    *,
    required_columns: tuple[str, ...] | None = None,
) -> Lunchbox:
    """Construct a :class:`Lunchbox`.  Accepts an optional records
    iterable to preload."""
    box = Lunchbox(required_columns=required_columns)
    if records is not None:
        box.extend(records)
    return box
