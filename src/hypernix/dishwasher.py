"""dishwasher — clean up training-run leftovers.

Four tiers of escalating aggressiveness, all sharing a common
``run()`` interface that returns a :class:`CleanReport`:

* :class:`HandWash`   — t1.  Conservative.  Removes only ``*.log``
                              and ``__pycache__`` directories.
* :class:`QuickWash`  — t2.  HandWash + ``*.tmp`` / ``*.partial`` /
                              ``*.lock`` files.
* :class:`NormalWash` — t3.  QuickWash + every checkpoint older
                              than the ``keep_recent`` window
                              (delegates discovery to
                              :mod:`hypernix.compactor`).
* :class:`HeavyDuty`  — t4.  NormalWash + the entire HuggingFace
                              cache directory under
                              ``~/.cache/huggingface``, intermediate
                              fp16 GGUFs, and any ``dist/`` /
                              ``build/`` directories left over from
                              ``python -m build``.

Every tier supports ``dry_run=True`` to plan-without-deleting,
and reports total bytes freed so a CI job can assert
"this clean recovered ≥ X MB".
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import compactor as _compactor


@dataclass
class CleanReport:
    files_removed: list[Path] = field(default_factory=list)
    dirs_removed: list[Path] = field(default_factory=list)
    bytes_freed: int = 0

    def merge(self, other: CleanReport) -> CleanReport:
        self.files_removed.extend(other.files_removed)
        self.dirs_removed.extend(other.dirs_removed)
        self.bytes_freed += other.bytes_freed
        return self

    def __str__(self) -> str:
        return (
            f"CleanReport(files={len(self.files_removed)}, "
            f"dirs={len(self.dirs_removed)}, "
            f"freed={_human_bytes(self.bytes_freed)})"
        )


def _human_bytes(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024 if isinstance(n, int) else 1
    return f"{n} PiB"


def _path_size(p: Path) -> int:
    if p.is_file():
        try:
            return p.stat().st_size
        except OSError:
            return 0
    if p.is_dir():
        total = 0
        for child in p.rglob("*"):
            if child.is_file():
                try:
                    total += child.stat().st_size
                except OSError:
                    continue
        return total
    return 0


def _remove(p: Path, *, dry_run: bool, report: CleanReport) -> None:
    size = _path_size(p)
    if p.is_file():
        if not dry_run:
            try:
                p.unlink()
            except OSError:
                return
        report.files_removed.append(p)
    elif p.is_dir():
        if not dry_run:
            try:
                shutil.rmtree(p)
            except OSError:
                return
        report.dirs_removed.append(p)
    report.bytes_freed += size


# ---------------------------------------------------------------------------
# Tier 1 — HandWash
# ---------------------------------------------------------------------------

@dataclass
class HandWash:
    """Conservative.  Logs + __pycache__ only."""

    root: Path | str = "."
    dry_run: bool = False
    name: str = "HandWash"

    def run(self) -> CleanReport:
        report = CleanReport()
        root = Path(self.root)
        for pat in ("**/*.log", "**/__pycache__"):
            for p in sorted(root.glob(pat)):
                _remove(p, dry_run=self.dry_run, report=report)
        return report


# ---------------------------------------------------------------------------
# Tier 2 — QuickWash
# ---------------------------------------------------------------------------

@dataclass
class QuickWash(HandWash):
    """HandWash + transient artefacts."""

    name: str = "QuickWash"

    def run(self) -> CleanReport:
        report = super().run()
        root = Path(self.root)
        for pat in ("**/*.tmp", "**/*.partial", "**/*.lock", "**/.DS_Store"):
            for p in sorted(root.glob(pat)):
                _remove(p, dry_run=self.dry_run, report=report)
        return report


# ---------------------------------------------------------------------------
# Tier 3 — NormalWash
# ---------------------------------------------------------------------------

@dataclass
class NormalWash(QuickWash):
    """QuickWash + stale checkpoints (keeps the most-recent N)."""

    name: str = "NormalWash"
    keep_recent: int = 3

    def run(self) -> CleanReport:
        report = super().run()
        root = Path(self.root)
        for snapshot_dir in [root, *[p for p in root.glob("*") if p.is_dir()]]:
            try:
                stale = list(_compactor.discover_old_checkpoints(
                    snapshot_dir, keep_recent=self.keep_recent,
                ))
            except FileNotFoundError:
                continue
            for p in stale:
                _remove(p, dry_run=self.dry_run, report=report)
        return report


# ---------------------------------------------------------------------------
# Tier 4 — HeavyDuty
# ---------------------------------------------------------------------------

@dataclass
class HeavyDuty(NormalWash):
    """NormalWash + intermediate GGUFs + HF hub cache + build dirs."""

    name: str = "HeavyDuty"
    purge_hf_cache: bool = False  # off by default — heavy-duty *can* purge,
                                  # but only when explicitly opted in.

    def run(self) -> CleanReport:
        report = super().run()
        root = Path(self.root)
        # Intermediate fp16 GGUFs (kept around between convert + quantize).
        for p in sorted(root.glob("**/*-fp16.gguf")):
            _remove(p, dry_run=self.dry_run, report=report)
        # Build artifacts.
        for d in ("dist", "build", ".pytest_cache", ".ruff_cache"):
            target = root / d
            if target.exists():
                _remove(target, dry_run=self.dry_run, report=report)
        if self.purge_hf_cache:
            hf = Path.home() / ".cache" / "huggingface"
            if hf.exists():
                _remove(hf, dry_run=self.dry_run, report=report)
        return report


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

TIERS = {
    "hand": HandWash,
    "quick": QuickWash,
    "normal": NormalWash,
    "heavy": HeavyDuty,
}


def dishwasher(tier: str = "normal", **kw):
    if tier not in TIERS:
        raise ValueError(f"unknown dishwasher tier {tier!r}; valid: {sorted(TIERS)}")
    return TIERS[tier](**kw)


def wash(tier: str = "normal", root: Path | str = ".", **kw) -> CleanReport:
    """One-shot helper.  ``wash(\"heavy\", \"./trained\")``."""
    return dishwasher(tier=tier, root=root, **kw).run()


__all__ = [
    "CleanReport",
    "HandWash",
    "HeavyDuty",
    "NormalWash",
    "QuickWash",
    "TIERS",
    "dishwasher",
    "wash",
]
