"""t1api.storage — SQLite persistence for local/dev T1 API deployments.

Per the spec: "SQLite for development, PostgreSQL for production." Beta 1
ships the SQLite backend only, used for usage events (the "basic usage
tracking" requirement). A PostgreSQL-backed implementation of the same
:class:`UsageStore` interface is Beta 3 scope ("production hardening"); the
interface is kept intentionally narrow so that swap-in is mechanical.

Stdlib-only (``sqlite3``) by design — the core of the T1 API (registry,
storage, usage) must stay importable without FastAPI/Pydantic installed.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_DEFAULT_DB_PATH = Path.home() / ".hypernix" / "t1api" / "t1api.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    requests INTEGER NOT NULL DEFAULT 1,
    endpoint TEXT NOT NULL DEFAULT '',
    server_id TEXT NOT NULL DEFAULT '',
    module_id TEXT NOT NULL DEFAULT '',
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_key_id ON usage_events(key_id);
CREATE INDEX IF NOT EXISTS idx_usage_model_id ON usage_events(model_id);
CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage_events(ts);
"""


class UsageStore:
    """Thread-safe SQLite-backed store for per-request usage events.

    Each connection is short-lived (opened per-call) since SQLite handles
    are not safe to share across threads without care, and the T1 API is
    expected to run under an async server with a thread pool. This keeps
    the store simple and correct at the cost of a little overhead — fine
    for the "basic usage tracking" Beta 1 requirement. A pooled connection
    strategy can be introduced later without changing the public API.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def record(
        self,
        *,
        key_id: str,
        model_id: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        requests: int = 1,
        endpoint: str = "",
        server_id: str = "",
        module_id: str = "",
        ts: float | None = None,
    ) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO usage_events
                   (key_id, model_id, input_tokens, output_tokens, requests,
                    endpoint, server_id, module_id, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    key_id,
                    model_id,
                    int(input_tokens),
                    int(output_tokens),
                    int(requests),
                    endpoint,
                    server_id,
                    module_id,
                    ts if ts is not None else time.time(),
                ),
            )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def totals_for_key(
        self, key_id: str, *, since: float | None = None, model_id: str | None = None
    ) -> dict[str, Any]:
        """Aggregate (requests, input_tokens, output_tokens) for a key,
        optionally filtered by a start timestamp and/or model_id."""
        query = (
            "SELECT COALESCE(SUM(requests),0) AS requests, "
            "COALESCE(SUM(input_tokens),0) AS input_tokens, "
            "COALESCE(SUM(output_tokens),0) AS output_tokens "
            "FROM usage_events WHERE key_id = ?"
        )
        params: list[Any] = [key_id]
        if since is not None:
            query += " AND ts >= ?"
            params.append(since)
        if model_id is not None:
            query += " AND model_id = ?"
            params.append(model_id)
        with self._lock, self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        return {
            "requests": row["requests"],
            "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"],
            "total_tokens": row["input_tokens"] + row["output_tokens"],
        }

    def breakdown_by_model(self, key_id: str, *, since: float | None = None) -> list[dict[str, Any]]:
        query = (
            "SELECT model_id, COALESCE(SUM(requests),0) AS requests, "
            "COALESCE(SUM(input_tokens),0) AS input_tokens, "
            "COALESCE(SUM(output_tokens),0) AS output_tokens "
            "FROM usage_events WHERE key_id = ?"
        )
        params: list[Any] = [key_id]
        if since is not None:
            query += " AND ts >= ?"
            params.append(since)
        query += " GROUP BY model_id ORDER BY (input_tokens + output_tokens) DESC"
        with self._lock, self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "model_id": r["model_id"],
                "requests": r["requests"],
                "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"],
                "total_tokens": r["input_tokens"] + r["output_tokens"],
            }
            for r in rows
        ]

    def event_count(self) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM usage_events").fetchone()
        return int(row["n"])


__all__ = ["UsageStore"]
