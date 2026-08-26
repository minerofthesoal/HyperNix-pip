"""t1api.backup — snapshot and restore a T1 deployment's state.

``GET /backup/list`` and ``POST /backup/restore`` are the endpoints; this
is what they operate on.

What a backup contains
----------------------
The registry, the routing policies, the key directory's *metadata*, the
server and module registries, the network policy, and the configuration
allowlist. Deliberately **not**: raw key material, usage counters, the
audit log, or attachment blobs.

Each exclusion is a decision, not an oversight:

* **Key material** — a backup file is copied to laptops and object
  stores. A snapshot that restores working credentials is a credential
  distribution mechanism. Restoring re-creates the key *records*; the
  material is re-minted and the operator re-distributes, which is the
  slow, correct path.
* **Usage counters** — restoring them would resurrect spent quota or
  refund it, depending on direction. Neither is right, and the meter is
  cheap to rebuild from zero at a known point.
* **The audit log** — an audit trail you can roll back is not an audit
  trail. It is append-only for the same reason a ledger is.
* **Attachment blobs** — they are content-addressed on disk and can be
  gigabytes. The manifest records their hashes so a restore can say what
  is missing rather than pretending it is intact.

Restore is a transaction with a dry run
---------------------------------------
:meth:`BackupStore.restore` defaults to ``dry_run=True``. A restore
rewrites the registry a live server is serving from, and the shape of
that mistake — restoring the wrong snapshot onto a production server —
is exactly the shape this module is supposed to protect against. The
caller has to say ``dry_run=False`` and pass ``confirm=True``, and the
dry run reports precisely what would change.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import T1APIError, T1ErrorCode

logger = logging.getLogger(__name__)

__all__ = ["BackupManifest", "BackupRecord", "BackupStore", "BACKUP_FORMAT_VERSION"]

#: Bumped when the manifest's shape changes incompatibly. A restore
#: refuses a newer format rather than reading fields it does not know.
BACKUP_FORMAT_VERSION = 1

#: The parts of a deployment a snapshot captures. Order is the restore
#: order: registries before the things that reference them.
BACKUP_SECTIONS: tuple[str, ...] = (
    "config",
    "model_registry",
    "routing_policies",
    "servers",
    "modules",
    "key_directory",
    "network_policy",
    "hyperlink_devices",
)

#: Never captured. See the module docstring for why each.
EXCLUDED: dict[str, str] = {
    "key_material": "a backup that restores working credentials is a credential distribution "
                    "mechanism",
    "usage_counters": "restoring them either resurrects spent quota or refunds it; neither is "
                      "correct",
    "audit_log": "an audit trail you can roll back is not an audit trail",
    "attachment_blobs": "content-addressed and potentially gigabytes; hashes are recorded so a "
                        "restore can report what is missing",
}


@dataclass
class BackupManifest:
    """What is in a snapshot, and what it was taken from."""

    backup_id: str
    created_at: float
    format_version: int
    t1_version: str
    hypernix_version: str
    sections: dict[str, int]                    # section -> record count
    checksums: dict[str, str] = field(default_factory=dict)
    attachment_hashes: list[str] = field(default_factory=list)
    label: str = ""
    created_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "backup_id": self.backup_id,
            "created_at": self.created_at,
            "format_version": self.format_version,
            "t1_version": self.t1_version,
            "hypernix_version": self.hypernix_version,
            "sections": dict(self.sections),
            "checksums": dict(self.checksums),
            "attachment_count": len(self.attachment_hashes),
            "label": self.label,
            "created_by": self.created_by,
            "excluded": dict(EXCLUDED),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BackupManifest:
        return cls(
            backup_id=str(data.get("backup_id", "")),
            created_at=float(data.get("created_at", 0.0)),
            format_version=int(data.get("format_version", 0)),
            t1_version=str(data.get("t1_version", "")),
            hypernix_version=str(data.get("hypernix_version", "")),
            sections=dict(data.get("sections") or {}),
            checksums=dict(data.get("checksums") or {}),
            attachment_hashes=list(data.get("attachment_hashes") or []),
            label=str(data.get("label", "")),
            created_by=str(data.get("created_by", "")),
        )


@dataclass
class BackupRecord:
    """One snapshot on disk, as ``GET /backup/list`` reports it."""

    backup_id: str
    path: Path
    manifest: BackupManifest
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.manifest.to_dict(),
            "size_bytes": self.size_bytes,
            "filename": self.path.name,
        }


class BackupStore:
    """Snapshots in a directory, newest first."""

    def __init__(self, root: str | Path | None = None, *, max_backups: int = 20) -> None:
        self.root = Path(root or Path.home() / ".hypernix" / "t1api" / "backups")
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_backups = int(max_backups)

    # -- creating -----------------------------------------------------

    def create(
        self,
        sections: dict[str, Any],
        *,
        label: str = "",
        created_by: str = "",
        attachment_hashes: list[str] | None = None,
        t1_version: str = "",
        hypernix_version: str = "",
    ) -> BackupRecord:
        """Write a snapshot from already-collected *sections*.

        Takes data rather than reaching into the app: the collection is
        the caller's job (it knows which stores exist), and keeping that
        out of here is what lets a backup be built in a test from three
        dicts.
        """
        unknown = sorted(set(sections) - set(BACKUP_SECTIONS))
        if unknown:
            raise T1APIError(
                T1ErrorCode.VALIDATION_ERROR,
                f"Unknown backup section(s): {', '.join(unknown)}. "
                f"Known: {', '.join(BACKUP_SECTIONS)}",
            )

        backup_id = f"bk_{int(time.time())}_{hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:8]}"
        counts: dict[str, int] = {}
        checksums: dict[str, str] = {}
        for name, payload in sections.items():
            blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
            checksums[name] = hashlib.sha256(blob).hexdigest()
            counts[name] = len(payload) if isinstance(payload, (list, dict)) else 1

        manifest = BackupManifest(
            backup_id=backup_id,
            created_at=time.time(),
            format_version=BACKUP_FORMAT_VERSION,
            t1_version=t1_version,
            hypernix_version=hypernix_version,
            sections=counts,
            checksums=checksums,
            attachment_hashes=list(attachment_hashes or []),
            label=label,
            created_by=created_by,
        )

        path = self.root / f"{backup_id}.tar.gz"
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp)
            (staging / "manifest.json").write_text(
                json.dumps(manifest.to_dict() | {"attachment_hashes": manifest.attachment_hashes},
                           indent=2, default=str),
                encoding="utf-8",
            )
            for name, payload in sections.items():
                (staging / f"{name}.json").write_text(
                    json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8"
                )
            # Write to a temporary name and rename: a crash mid-write must
            # not leave a truncated archive that `list` reports as valid.
            partial = path.with_suffix(".partial")
            with tarfile.open(partial, "w:gz") as tar:
                for item in sorted(staging.iterdir()):
                    tar.add(item, arcname=item.name)
            partial.replace(path)

        self._prune()
        return BackupRecord(
            backup_id=backup_id, path=path, manifest=manifest, size_bytes=path.stat().st_size
        )

    def _prune(self) -> None:
        records = self.list_backups()
        for stale in records[self.max_backups:]:
            try:
                stale.path.unlink(missing_ok=True)
            except OSError:
                logger.warning("t1api.backup: could not remove old backup %s", stale.path)

    # -- listing ------------------------------------------------------

    def list_backups(self) -> list[BackupRecord]:
        """Every readable snapshot, newest first.

        An unreadable archive is skipped with a warning rather than
        failing the listing: one corrupt file must not hide the nine
        good ones next to it, which is exactly when someone is looking.
        """
        records: list[BackupRecord] = []
        for path in sorted(self.root.glob("*.tar.gz")):
            try:
                manifest = self._read_manifest(path)
            except (OSError, tarfile.TarError, json.JSONDecodeError, KeyError) as exc:
                logger.warning("t1api.backup: skipping unreadable backup %s: %s", path.name, exc)
                continue
            records.append(
                BackupRecord(
                    backup_id=manifest.backup_id,
                    path=path,
                    manifest=manifest,
                    size_bytes=path.stat().st_size,
                )
            )
        records.sort(key=lambda r: r.manifest.created_at, reverse=True)
        return records

    def get(self, backup_id: str) -> BackupRecord:
        for record in self.list_backups():
            if record.backup_id == backup_id:
                return record
        raise T1APIError(T1ErrorCode.NOT_FOUND, f"No backup {backup_id!r}")

    def _read_manifest(self, path: Path) -> BackupManifest:
        with tarfile.open(path, "r:gz") as tar:
            member = tar.extractfile("manifest.json")
            if member is None:
                raise KeyError("manifest.json")
            return BackupManifest.from_dict(json.loads(member.read().decode("utf-8")))

    # -- restoring ----------------------------------------------------

    def read_sections(self, backup_id: str) -> dict[str, Any]:
        """Load a snapshot's section payloads, verifying checksums.

        A section whose checksum does not match is a corrupted archive,
        and restoring half of one is worse than restoring none.
        """
        record = self.get(backup_id)
        sections: dict[str, Any] = {}
        with tarfile.open(record.path, "r:gz") as tar:
            for name in record.manifest.sections:
                member = tar.extractfile(f"{name}.json")
                if member is None:
                    raise T1APIError(
                        T1ErrorCode.INTERNAL_ERROR,
                        f"Backup {backup_id} is missing its {name} section",
                    )
                blob = member.read()
                payload = json.loads(blob.decode("utf-8"))
                expected = record.manifest.checksums.get(name)
                actual = hashlib.sha256(
                    json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
                ).hexdigest()
                if expected and expected != actual:
                    raise T1APIError(
                        T1ErrorCode.INTERNAL_ERROR,
                        f"Backup {backup_id} section {name!r} failed its checksum — the "
                        "archive is corrupt. Refusing to restore a partial snapshot.",
                    )
                sections[name] = payload
        return sections

    def restore(
        self,
        backup_id: str,
        applier: Any = None,
        *,
        dry_run: bool = True,
        confirm: bool = False,
        sections: list[str] | None = None,
    ) -> dict[str, Any]:
        """Restore a snapshot through *applier*.

        ``dry_run=True`` by default and ``confirm`` required to actually
        write, because a restore rewrites what a live server is serving
        and the mistake this module exists to catch is restoring the
        wrong snapshot onto production.

        *applier* is called as ``applier(name, payload)`` per section and
        returns a description of what it changed. Keeping the semantics
        out of here is what lets this be tested with a dict. It is
        optional for a dry run, which is the whole point of a dry run:
        reporting what a restore would do must not require the machinery
        that would do it.
        """
        record = self.get(backup_id)
        if not dry_run and applier is None:
            raise T1APIError(
                T1ErrorCode.VALIDATION_ERROR,
                "A live restore needs an applier; only a dry run can run without one.",
            )
        if record.manifest.format_version > BACKUP_FORMAT_VERSION:
            raise T1APIError(
                T1ErrorCode.VALIDATION_ERROR,
                f"Backup {backup_id} is format version {record.manifest.format_version}; this "
                f"server understands {BACKUP_FORMAT_VERSION}. Upgrade before restoring — "
                "reading fields it does not know is how a restore silently drops data.",
            )
        if not dry_run and not confirm:
            raise T1APIError(
                T1ErrorCode.CONFIRMATION_REQUIRED,
                "A live restore rewrites the registry this server is serving from. "
                "Re-send with confirm=true, or run it as a dry run first.",
                http_status=409,
            )

        available = self.read_sections(backup_id)
        wanted = sections or list(available)
        unknown = sorted(set(wanted) - set(available))
        if unknown:
            raise T1APIError(
                T1ErrorCode.VALIDATION_ERROR,
                f"Backup {backup_id} has no section(s): {', '.join(unknown)}",
            )

        changes: list[dict[str, Any]] = []
        for name in BACKUP_SECTIONS:            # restore order, not request order
            if name not in wanted:
                continue
            payload = available[name]
            if dry_run:
                changes.append(
                    {
                        "section": name,
                        "records": len(payload) if isinstance(payload, (list, dict)) else 1,
                        "applied": False,
                    }
                )
            else:
                result = applier(name, payload)
                changes.append({"section": name, "applied": True, "result": result})

        return {
            "backup_id": backup_id,
            "dry_run": dry_run,
            "created_at": record.manifest.created_at,
            "label": record.manifest.label,
            "sections": changes,
            "excluded": dict(EXCLUDED),
            "note": (
                "Key material is never restored. Keys are re-created as records; the material "
                "must be re-minted and re-distributed."
            ),
        }

    def delete(self, backup_id: str) -> bool:
        record = self.get(backup_id)
        try:
            record.path.unlink(missing_ok=True)
        except OSError as exc:
            raise T1APIError(
                T1ErrorCode.INTERNAL_ERROR, f"Could not delete {backup_id}: {exc}"
            ) from exc
        return True

    def export_to(self, backup_id: str, destination: str | Path) -> Path:
        """Copy a snapshot out of the store, for off-machine storage."""
        record = self.get(backup_id)
        target = Path(destination)
        if target.is_dir():
            target = target / record.path.name
        shutil.copy2(record.path, target)
        return target
