"""t1api.db — a tiny shared SQLite connection helper.

Beta 1's ``t1api.storage.UsageStore`` established the pattern (short-lived
per-call connections, WAL mode, ``Row`` factory, one file). Beta 2 adds
four more tables (servers, modules, jobs, billing) that want the same
pattern without four copies of the same boilerplate — this module is that
shared piece. Each Beta 2 store still owns its own schema/queries/lock;
this only factors out "open a connection to the right file, the right
way."

Stdlib-only, same as everything else in ``t1api``'s core.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

_DEFAULT_DB_PATH = Path.home() / ".hypernix" / "t1api" / "t1api.sqlite3"


class SQLiteBackend:
    """Wraps one SQLite file. Multiple stores (servers/modules/jobs/
    billing/usage) can point at the *same* file — SQLite handles multiple
    tables in one file fine, and it keeps a Beta-1-style single-file dev
    deployment simple. They can also point at different files if you'd
    rather split them; nothing here assumes a shared file.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.row_factory = sqlite3.Row
        return conn

    def executescript(self, sql: str) -> None:
        with self.connect() as conn:
            conn.executescript(sql)


__all__ = ["SQLiteBackend"]
