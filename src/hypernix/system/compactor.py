"""compactor — zip older checkpoints to save disk.

A compactor crushes things flat.  Here it walks a snapshot
directory, finds older checkpoint folders / files, and rolls
them into a single ``.zip`` (or ``.tar.gz``) so a long training
run doesn't fill the disk with intermediate snapshots.

Quick use::

    from hypernix.compactor import Compactor

    Compactor("./trained-pascal", keep_recent=3).compact()

    # or one-shot
    from hypernix.compactor import compact
    compact("./trained-pascal", keep_recent=3, fmt="tar.gz")

Detects checkpoints by the conventional ``ckpt-NNNN`` /
``checkpoint-NNNN`` / ``step-NNNN`` directory naming the
:mod:`hypernix.train` pipeline emits, plus any ``*.pt`` /
``*.safetensors`` files older than the keep window.
"""
from __future__ import annotations

import re
import shutil
import tarfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

#: Regex patterns matched against directory / file names to identify
#: checkpoint artifacts.  Each captures a numeric step in group 1.
_CKPT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^ckpt-(\d+)$"),
    re.compile(r"^checkpoint-(\d+)$"),
    re.compile(r"^step-(\d+)$"),
    re.compile(r"^.*-step-(\d+)(?:\.pt|\.safetensors)?$"),
    re.compile(r"^.*-ckpt-(\d+)(?:\.pt|\.safetensors)?$"),
)


def _step_of(name: str) -> int | None:
    for pat in _CKPT_PATTERNS:
        m = pat.match(name)
        if m:
            return int(m.group(1))
    return None


@dataclass
class Compactor:
    """Walks a directory and rolls older checkpoints into archives.

    Args:
        root: Directory to scan (typically the ``out_dir`` from a
            training run).
        keep_recent: How many of the most-recent checkpoints to leave
            uncompressed.  Defaults to 3.
        fmt: Archive format — ``"zip"`` (default), ``"tar"``, or
            ``"tar.gz"``.
        dry_run: When ``True``, plan the work but don't write or
            delete anything.  :meth:`compact` returns the planned
            actions for inspection.
        delete_originals: When ``True`` (default), remove the
            original checkpoint files / directories after they're
            successfully compressed.
    """

    root: Path | str
    keep_recent: int = 3
    fmt: str = "zip"
    dry_run: bool = False
    delete_originals: bool = True
    archive_dir: Path | str | None = None
    found: list[Path] = field(default_factory=list, init=False, repr=False)
    planned: list[tuple[Path, Path]] = field(
        default_factory=list, init=False, repr=False,
    )
    archived: list[Path] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.fmt not in ("zip", "tar", "tar.gz"):
            raise ValueError(f"unknown fmt {self.fmt!r}; valid: zip / tar / tar.gz")
        if self.keep_recent < 0:
            raise ValueError("keep_recent must be >= 0")

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self) -> list[Path]:
        """Return checkpoint paths sorted oldest-first by step number."""
        root = Path(self.root)
        if not root.exists():
            raise FileNotFoundError(f"compactor root {root} does not exist")
        entries: list[tuple[int, Path]] = []
        for p in root.iterdir():
            step = _step_of(p.name)
            if step is not None:
                entries.append((step, p))
        entries.sort()
        self.found = [p for _step, p in entries]
        return list(self.found)

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    def _archive_path_for(self, src: Path) -> Path:
        out_dir = Path(self.archive_dir) if self.archive_dir else src.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        suffix = ".zip" if self.fmt == "zip" else (
            ".tar.gz" if self.fmt == "tar.gz" else ".tar"
        )
        return out_dir / f"{src.name}{suffix}"

    def plan(self) -> list[tuple[Path, Path]]:
        """Return ``[(src, archive_path), ...]`` for what would be
        compacted, oldest-first."""
        self.discover()
        if self.keep_recent and self.found:
            stale = self.found[: -self.keep_recent] if self.keep_recent < len(self.found) else []
        else:
            stale = list(self.found)
        self.planned = [(src, self._archive_path_for(src)) for src in stale]
        return list(self.planned)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def compact(self) -> list[Path]:
        """Compress every stale checkpoint and (unless ``dry_run`` /
        ``delete_originals=False``) delete the originals.  Returns the
        list of created archive paths."""
        plan = self.plan()
        archives: list[Path] = []
        for src, archive in plan:
            if self.dry_run:
                archives.append(archive)
                continue
            self._archive_one(src, archive)
            if self.delete_originals:
                self._remove_original(src)
            archives.append(archive)
        self.archived = archives
        return archives

    def _archive_one(self, src: Path, archive: Path) -> None:
        if archive.exists():
            archive.unlink()
        if self.fmt == "zip":
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                if src.is_dir():
                    for child in src.rglob("*"):
                        if child.is_file():
                            zf.write(child, arcname=child.relative_to(src.parent))
                else:
                    zf.write(src, arcname=src.name)
        else:
            mode = "w:gz" if self.fmt == "tar.gz" else "w"
            with tarfile.open(archive, mode) as tf:
                tf.add(src, arcname=src.name)

    def _remove_original(self, src: Path) -> None:
        if src.is_dir():
            shutil.rmtree(src)
        else:
            src.unlink()


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def compact(
    root: Path | str,
    *,
    keep_recent: int = 3,
    fmt: str = "zip",
    dry_run: bool = False,
    delete_originals: bool = True,
    archive_dir: Path | str | None = None,
) -> list[Path]:
    """One-shot helper.  Returns the list of created archive paths."""
    return Compactor(
        root=root, keep_recent=keep_recent, fmt=fmt,
        dry_run=dry_run, delete_originals=delete_originals,
        archive_dir=archive_dir,
    ).compact()


def list_checkpoints(root: Path | str) -> list[Path]:
    """Discover checkpoint paths in ``root``, oldest-first."""
    return Compactor(root=root).discover()


def discover_old_checkpoints(
    root: Path | str, keep_recent: int = 3,
) -> Iterable[Path]:
    """Yield only the checkpoints that *would* be compacted under
    ``keep_recent``."""
    yield from (src for src, _archive in Compactor(
        root=root, keep_recent=keep_recent,
    ).plan())


__all__ = [
    "Compactor",
    "compact",
    "discover_old_checkpoints",
    "list_checkpoints",
]
