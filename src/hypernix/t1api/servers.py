"""t1api.servers — the Server Registry.

Tracks which servers exist, whether they're trusted, and what they're
capable of, per the spec's requirement that "the server determines...
which servers may execute a job" — the client names a server_id; this
registry (not the client) decides whether that server is real, trusted,
and eligible.

Persisted in SQLite (via :class:`t1api.db.SQLiteBackend`) rather than a
static JSON file like the model registry, since servers register/
deregister themselves at runtime (``POST /servers/register``) instead of
being curated ahead of time.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .db import SQLiteBackend
from .errors import T1APIError, T1ErrorCode
from .security import validate_remote_address

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS servers (
    server_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    address TEXT NOT NULL,
    trust_level TEXT NOT NULL,
    status TEXT NOT NULL,
    capabilities TEXT NOT NULL,
    tags TEXT NOT NULL,
    registered_by TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_seen REAL
);
"""


class TrustLevel(StrEnum):
    """"Verify remote server trust before remote uploads" — a server
    starts UNTRUSTED and must be explicitly promoted by an admin
    (PATCH /servers/{id}) before it's eligible for remote module
    deployment. LOCAL is for the deployment's own loopback/Tailscale
    address, implicitly trusted since it's the operator's own machine."""

    UNTRUSTED = "untrusted"
    TRUSTED = "trusted"
    LOCAL = "local"


class ServerStatus(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


@dataclass
class ServerEntry:
    server_id: str
    name: str
    address: str
    trust_level: TrustLevel
    status: ServerStatus
    capabilities: list[str]
    tags: dict[str, str]
    registered_by: str
    created_at: float
    updated_at: float
    last_seen: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "server_id": self.server_id,
            "name": self.name,
            "address": self.address,
            "trust_level": self.trust_level.value,
            "status": self.status.value,
            "capabilities": self.capabilities,
            "tags": self.tags,
            "registered_by": self.registered_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_seen": self.last_seen,
        }

    @classmethod
    def _from_row(cls, row: Any) -> ServerEntry:
        return cls(
            server_id=row["server_id"],
            name=row["name"],
            address=row["address"],
            trust_level=TrustLevel(row["trust_level"]),
            status=ServerStatus(row["status"]),
            capabilities=json.loads(row["capabilities"]),
            tags=json.loads(row["tags"]),
            registered_by=row["registered_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_seen=row["last_seen"],
        )


class ServerRegistry:
    """Thread-safe, SQLite-backed server registry."""

    def __init__(self, backend: SQLiteBackend | None = None) -> None:
        self.backend = backend or SQLiteBackend()
        self._lock = threading.Lock()
        self.backend.executescript(_SCHEMA)

    # ------------------------------------------------------------------

    def register(
        self,
        *,
        name: str,
        address: str,
        registered_by: str,
        capabilities: list[str] | None = None,
        tags: dict[str, str] | None = None,
        trust_level: TrustLevel = TrustLevel.UNTRUSTED,
        allow_private_address: bool = False,
    ) -> ServerEntry:
        """Register a new server. *address* is validated the same way a
        module-source URL is (SSRF guard) — set ``allow_private_address``
        for local/Tailscale deployments, where a private address is
        expected rather than suspicious."""
        validate_remote_address(address, allow_private=allow_private_address)
        now = time.time()
        entry = ServerEntry(
            server_id=uuid.uuid4().hex,
            name=name,
            address=address,
            trust_level=trust_level,
            status=ServerStatus.UNKNOWN,
            capabilities=capabilities or [],
            tags=tags or {},
            registered_by=registered_by,
            created_at=now,
            updated_at=now,
        )
        with self._lock, self.backend.connect() as conn:
            conn.execute(
                """INSERT INTO servers
                   (server_id, name, address, trust_level, status, capabilities,
                    tags, registered_by, created_at, updated_at, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.server_id,
                    entry.name,
                    entry.address,
                    entry.trust_level.value,
                    entry.status.value,
                    json.dumps(entry.capabilities),
                    json.dumps(entry.tags),
                    entry.registered_by,
                    entry.created_at,
                    entry.updated_at,
                    entry.last_seen,
                ),
            )
        logger.info("t1api.servers: registered %s (%s) trust=%s", entry.server_id[:8], name, trust_level)
        return entry

    def get(self, server_id: str) -> ServerEntry | None:
        with self._lock, self.backend.connect() as conn:
            row = conn.execute("SELECT * FROM servers WHERE server_id = ?", (server_id,)).fetchone()
        return ServerEntry._from_row(row) if row else None

    def require(self, server_id: str) -> ServerEntry:
        entry = self.get(server_id)
        if entry is None:
            raise T1APIError(
                T1ErrorCode.SERVER_NOT_FOUND,
                f"Server '{server_id}' is not registered.",
                details={"server_id": server_id},
                http_status=404,
            )
        return entry

    def require_trusted(self, server_id: str) -> ServerEntry:
        """"Verify remote server trust before remote uploads" — the
        enforcement point. Raises ``SERVER_UNTRUSTED`` for anything not
        TRUSTED/LOCAL, distinct from ``SERVER_NOT_FOUND`` for a server
        that doesn't exist at all."""
        entry = self.require(server_id)
        if entry.trust_level == TrustLevel.UNTRUSTED:
            raise T1APIError(
                T1ErrorCode.SERVER_UNTRUSTED,
                f"Server '{server_id}' is not trusted for this operation. "
                "An admin must promote it first.",
                details={"server_id": server_id, "trust_level": entry.trust_level.value},
                http_status=403,
            )
        return entry

    def list(self, *, trust_level: TrustLevel | None = None, status: ServerStatus | None = None) -> list[ServerEntry]:
        query = "SELECT * FROM servers"
        clauses, params = [], []
        if trust_level is not None:
            clauses.append("trust_level = ?")
            params.append(trust_level.value)
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC"
        with self._lock, self.backend.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [ServerEntry._from_row(r) for r in rows]

    def update(
        self,
        server_id: str,
        *,
        name: str | None = None,
        status: ServerStatus | None = None,
        trust_level: TrustLevel | None = None,
        capabilities: list[str] | None = None,
        tags: dict[str, str] | None = None,
        touch_last_seen: bool = False,
    ) -> ServerEntry:
        entry = self.require(server_id)
        if name is not None:
            entry.name = name
        if status is not None:
            entry.status = status
        if trust_level is not None:
            entry.trust_level = trust_level
        if capabilities is not None:
            entry.capabilities = capabilities
        if tags is not None:
            entry.tags = tags
        entry.updated_at = time.time()
        if touch_last_seen:
            entry.last_seen = entry.updated_at
        with self._lock, self.backend.connect() as conn:
            conn.execute(
                """UPDATE servers SET name=?, address=?, trust_level=?, status=?,
                   capabilities=?, tags=?, updated_at=?, last_seen=? WHERE server_id=?""",
                (
                    entry.name,
                    entry.address,
                    entry.trust_level.value,
                    entry.status.value,
                    json.dumps(entry.capabilities),
                    json.dumps(entry.tags),
                    entry.updated_at,
                    entry.last_seen,
                    entry.server_id,
                ),
            )
        return entry

    def delete(self, server_id: str) -> None:
        self.require(server_id)  # raise SERVER_NOT_FOUND if missing, for a consistent error
        with self._lock, self.backend.connect() as conn:
            conn.execute("DELETE FROM servers WHERE server_id = ?", (server_id,))
        logger.info("t1api.servers: deleted %s", server_id[:8])


__all__ = ["TrustLevel", "ServerStatus", "ServerEntry", "ServerRegistry"]
