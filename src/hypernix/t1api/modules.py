"""t1api.modules — the Module Registry.

Covers the spec's "MODULE SYSTEM" list: creation, upload (local + remote-
source registration), versioning, listing, metadata, and sync tracking
against the server registry.

**What this module deliberately does NOT do**: execute, import, or run
any uploaded module content. "Prevent arbitrary remote code execution
through module upload/deployment" is satisfied here by never being in the
business of running the bytes it stores — a module is an opaque,
checksummed blob (local upload) or a validated-but-unfetched source URL
(remote registration) that some other operator-controlled process is
responsible for actually consuming. Local file paths are always resolved
through :func:`t1api.security.sanitize_module_path`; remote source URLs
always through :func:`t1api.security.validate_remote_address`.

Remote fetch and cross-server sync are asynchronous by design — see
``t1api.jobs``. This module only tracks *intent* and *state*
(``PENDING_FETCH``, ``deployed_servers``); the actual network transport
for "push module bytes to a remote server" isn't implemented, since Beta 2
has no second real server to test that against (this is called out
explicitly in ``wiki/T1-API.md``, not hidden).
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .db import SQLiteBackend
from .errors import T1APIError, T1ErrorCode
from .security import sanitize_module_path, validate_remote_address

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS modules (
    module_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    owner_key_id TEXT NOT NULL,
    status TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_url TEXT,
    storage_path TEXT,
    checksum TEXT,
    size_bytes INTEGER,
    deployed_servers TEXT NOT NULL,
    metadata TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(name, version)
);
"""

_DEFAULT_STORAGE_DIR = Path.home() / ".hypernix" / "t1api" / "modules"


class ModuleStatus(StrEnum):
    DRAFT = "draft"  # created, no content yet
    PENDING_FETCH = "pending_fetch"  # remote source registered, not yet staged
    ACTIVE = "active"  # content present and checksummed
    DEPRECATED = "deprecated"


class SourceType(StrEnum):
    NONE = "none"
    LOCAL = "local"
    REMOTE = "remote"


@dataclass
class ModuleEntry:
    module_id: str
    name: str
    version: str
    owner_key_id: str
    status: ModuleStatus
    source_type: SourceType
    source_url: str | None
    storage_path: str | None
    checksum: str | None
    size_bytes: int | None
    deployed_servers: list[str]
    metadata: dict[str, Any]
    created_at: float
    updated_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "name": self.name,
            "version": self.version,
            "owner_key_id": self.owner_key_id,
            "status": self.status.value,
            "source_type": self.source_type.value,
            "source_url": self.source_url,
            "checksum": self.checksum,
            "size_bytes": self.size_bytes,
            "deployed_servers": self.deployed_servers,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def _from_row(cls, row: Any) -> ModuleEntry:
        return cls(
            module_id=row["module_id"],
            name=row["name"],
            version=row["version"],
            owner_key_id=row["owner_key_id"],
            status=ModuleStatus(row["status"]),
            source_type=SourceType(row["source_type"]),
            source_url=row["source_url"],
            storage_path=row["storage_path"],
            checksum=row["checksum"],
            size_bytes=row["size_bytes"],
            deployed_servers=json.loads(row["deployed_servers"]),
            metadata=json.loads(row["metadata"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class ModuleRegistry:
    """Thread-safe, SQLite-backed module registry + local blob storage."""

    def __init__(self, backend: SQLiteBackend | None = None, *, storage_dir: str | Path | None = None) -> None:
        self.backend = backend or SQLiteBackend()
        self.storage_dir = Path(storage_dir) if storage_dir is not None else _DEFAULT_STORAGE_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.backend.executescript(_SCHEMA)

    # ------------------------------------------------------------------

    def create(
        self, *, name: str, version: str, owner_key_id: str, metadata: dict[str, Any] | None = None
    ) -> ModuleEntry:
        now = time.time()
        entry = ModuleEntry(
            module_id=uuid.uuid4().hex,
            name=name,
            version=version,
            owner_key_id=owner_key_id,
            status=ModuleStatus.DRAFT,
            source_type=SourceType.NONE,
            source_url=None,
            storage_path=None,
            checksum=None,
            size_bytes=None,
            deployed_servers=[],
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )
        try:
            with self._lock, self.backend.connect() as conn:
                conn.execute(
                    """INSERT INTO modules
                       (module_id, name, version, owner_key_id, status, source_type,
                        source_url, storage_path, checksum, size_bytes, deployed_servers,
                        metadata, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        entry.module_id, entry.name, entry.version, entry.owner_key_id,
                        entry.status.value, entry.source_type.value, entry.source_url,
                        entry.storage_path, entry.checksum, entry.size_bytes,
                        json.dumps(entry.deployed_servers), json.dumps(entry.metadata),
                        entry.created_at, entry.updated_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise T1APIError(
                T1ErrorCode.MODULE_ALREADY_EXISTS,
                f"Module '{name}' version '{version}' already exists.",
                details={"name": name, "version": version},
                http_status=409,
            ) from exc
        logger.info("t1api.modules: created %s %s@%s", entry.module_id[:8], name, version)
        return entry

    def get(self, module_id: str) -> ModuleEntry | None:
        with self._lock, self.backend.connect() as conn:
            row = conn.execute("SELECT * FROM modules WHERE module_id = ?", (module_id,)).fetchone()
        return ModuleEntry._from_row(row) if row else None

    def require(self, module_id: str) -> ModuleEntry:
        entry = self.get(module_id)
        if entry is None:
            raise T1APIError(
                T1ErrorCode.MODULE_NOT_FOUND,
                f"Module '{module_id}' is not registered.",
                details={"module_id": module_id},
                http_status=404,
            )
        return entry

    def list(
        self, *, status: ModuleStatus | None = None, owner_key_id: str | None = None, name: str | None = None
    ) -> list[ModuleEntry]:
        query = "SELECT * FROM modules"
        clauses, params = [], []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if owner_key_id is not None:
            clauses.append("owner_key_id = ?")
            params.append(owner_key_id)
        if name is not None:
            clauses.append("name = ?")
            params.append(name)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC"
        with self._lock, self.backend.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [ModuleEntry._from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def upload_local(self, module_id: str, content: bytes, *, filename: str) -> ModuleEntry:
        """Store *content* under this module's sanitized storage path and
        mark it ACTIVE. *filename* is untrusted client input — resolved
        through :func:`sanitize_module_path` before ever touching disk."""
        entry = self.require(module_id)
        safe_path = sanitize_module_path(f"{module_id}/{filename}", self.storage_dir)
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        safe_path.write_bytes(content)
        checksum = hashlib.sha256(content).hexdigest()
        relative = str(safe_path.relative_to(self.storage_dir.resolve()))

        entry.source_type = SourceType.LOCAL
        entry.storage_path = relative
        entry.checksum = checksum
        entry.size_bytes = len(content)
        entry.status = ModuleStatus.ACTIVE
        entry.updated_at = time.time()
        self._persist(entry)
        logger.info(
            "t1api.modules: uploaded local content for %s (%d bytes, sha256=%s)",
            module_id[:8], entry.size_bytes, checksum[:12],
        )
        return entry

    def register_remote_source(
        self, module_id: str, source_url: str, *, allow_private: bool = False
    ) -> ModuleEntry:
        """Validate and record a remote source URL. Does NOT fetch it —
        marks the module PENDING_FETCH; actual staging happens as an
        async job (``t1api.jobs``), composed at the router layer so this
        module doesn't depend on the job queue."""
        entry = self.require(module_id)
        validate_remote_address(source_url, allow_private=allow_private)
        entry.source_type = SourceType.REMOTE
        entry.source_url = source_url
        entry.status = ModuleStatus.PENDING_FETCH
        entry.updated_at = time.time()
        self._persist(entry)
        logger.info("t1api.modules: registered remote source for %s -> %s", module_id[:8], source_url)
        return entry

    def read_content(self, module_id: str) -> bytes:
        entry = self.require(module_id)
        if entry.storage_path is None:
            raise T1APIError(
                T1ErrorCode.NOT_FOUND,
                f"Module '{module_id}' has no stored content yet.",
                details={"module_id": module_id, "status": entry.status.value},
                http_status=404,
            )
        path = self.storage_dir.resolve() / entry.storage_path
        return path.read_bytes()

    # ------------------------------------------------------------------
    # Update / sync / delete
    # ------------------------------------------------------------------

    def update(
        self, module_id: str, *, metadata: dict[str, Any] | None = None, status: ModuleStatus | None = None
    ) -> ModuleEntry:
        entry = self.require(module_id)
        if metadata is not None:
            entry.metadata = metadata
        if status is not None:
            entry.status = status
        entry.updated_at = time.time()
        self._persist(entry)
        return entry

    def mark_synced(self, module_id: str, server_id: str) -> ModuleEntry:
        """Record that *module_id* has been synced to *server_id*. Called
        by the router after :class:`t1api.servers.ServerRegistry`
        confirms the target is trusted — this method itself doesn't check
        trust, matching the "caller enforces" pattern used throughout."""
        entry = self.require(module_id)
        if server_id not in entry.deployed_servers:
            entry.deployed_servers = [*entry.deployed_servers, server_id]
        entry.updated_at = time.time()
        self._persist(entry)
        return entry

    def delete(self, module_id: str) -> None:
        entry = self.require(module_id)
        if entry.storage_path:
            path = self.storage_dir.resolve() / entry.storage_path
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning("t1api.modules: could not remove stored file for %s", module_id[:8])
        with self._lock, self.backend.connect() as conn:
            conn.execute("DELETE FROM modules WHERE module_id = ?", (module_id,))
        logger.info("t1api.modules: deleted %s", module_id[:8])

    def _persist(self, entry: ModuleEntry) -> None:
        with self._lock, self.backend.connect() as conn:
            conn.execute(
                """UPDATE modules SET name=?, version=?, status=?, source_type=?, source_url=?,
                   storage_path=?, checksum=?, size_bytes=?, deployed_servers=?, metadata=?,
                   updated_at=? WHERE module_id=?""",
                (
                    entry.name, entry.version, entry.status.value, entry.source_type.value,
                    entry.source_url, entry.storage_path, entry.checksum, entry.size_bytes,
                    json.dumps(entry.deployed_servers), json.dumps(entry.metadata),
                    entry.updated_at, entry.module_id,
                ),
            )


__all__ = ["ModuleStatus", "SourceType", "ModuleEntry", "ModuleRegistry"]
