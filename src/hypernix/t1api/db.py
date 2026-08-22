"""t1api.db — the shared SQL backend: SQLite for development, PostgreSQL
for production.

Beta 1 established the pattern (short-lived per-call connections, WAL
mode, row-by-name access, one file); Beta 2 factored it into
:class:`SQLiteBackend` so servers/modules/jobs/billing/usage could share
it. Beta 3 adds the spec's "PostgreSQL for production" half **without
touching a single query in those five stores** — every one of them talks
to a backend through exactly this contract::

    with backend.connect() as conn:
        row = conn.execute("SELECT ... WHERE x = ?", (x,)).fetchone()

so the portability work lives here, in one place, instead of being
sprinkled through five modules as ``if postgres:`` branches.

What the wrapper normalizes
---------------------------

* **Placeholders.** Stores are written with SQLite's ``?``.
  :class:`_Connection` rewrites them to ``%s`` for psycopg, skipping
  anything inside a string literal so a legitimate ``'?'`` in SQL text
  survives.
* **Rows by name.** SQLite gets ``sqlite3.Row``, PostgreSQL gets
  psycopg's ``dict_row``. Both support ``row["column"]``, which is the
  only access pattern the stores use.
* **DDL dialect.** ``INTEGER PRIMARY KEY AUTOINCREMENT`` →
  ``BIGSERIAL PRIMARY KEY``, ``REAL`` → ``DOUBLE PRECISION``. See
  :func:`translate_ddl`. ``ON CONFLICT ... DO UPDATE SET ... excluded.x``
  (used by the billing ledger) is already valid in both, so it isn't
  translated.
* **Transaction + close.** Both dialects commit on clean exit, roll back
  on an exception, and *close* the connection either way. SQLite's own
  ``with conn:`` commits but never closes — the connection leak that
  fixes is why the wrapper exists for SQLite too, not just PostgreSQL.

PostgreSQL requires ``psycopg[binary]>=3`` (the ``hypernix[t1api-pg]``
extra). It is imported lazily, so a SQLite deployment never pays for it
and a missing install produces a clear message instead of an ImportError
from somewhere deep in the stack.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path.home() / ".hypernix" / "t1api" / "t1api.sqlite3"

DIALECT_SQLITE = "sqlite"
DIALECT_POSTGRES = "postgres"

# Matches a ``?`` placeholder that is NOT inside a single-quoted string.
# We scan the statement rather than using a naive str.replace so a literal
# question mark in e.g. ``WHERE note LIKE '%?%'`` is left alone.
_STRING_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")


def to_pg_placeholders(sql: str) -> str:
    """Rewrite SQLite ``?`` placeholders to psycopg ``%s``.

    ``?`` inside a single-quoted string literal is preserved, and any
    literal ``%`` elsewhere is doubled so psycopg's own ``%`` formatting
    doesn't misread it.
    """
    out: list[str] = []
    pos = 0
    for match in _STRING_LITERAL_RE.finditer(sql):
        out.append(sql[pos : match.start()].replace("%", "%%").replace("?", "%s"))
        out.append(match.group(0))
        pos = match.end()
    out.append(sql[pos:].replace("%", "%%").replace("?", "%s"))
    return "".join(out)


_DDL_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", re.I), "BIGSERIAL PRIMARY KEY"),
    (re.compile(r"\bREAL\b", re.I), "DOUBLE PRECISION"),
)


def translate_ddl(sql: str, dialect: str) -> str:
    """Translate a SQLite-flavoured ``CREATE TABLE``/``CREATE INDEX``
    script into *dialect*. A no-op for SQLite."""
    if dialect != DIALECT_POSTGRES:
        return sql
    for pattern, replacement in _DDL_REPLACEMENTS:
        sql = pattern.sub(replacement, sql)
    return sql


class _Connection:
    """Uniform connection facade over sqlite3 / psycopg.

    Deliberately implements only what the stores actually use —
    ``execute()`` returning something with ``fetchone()``/``fetchall()``,
    and the context-manager protocol. Anything richer would be a new API
    surface for five call sites that don't need it.
    """

    def __init__(self, raw: Any, dialect: str) -> None:
        self._raw = raw
        self.dialect = dialect

    # -- query -------------------------------------------------------
    def execute(self, sql: str, params: tuple | list = ()) -> Any:
        if self.dialect == DIALECT_POSTGRES:
            cur = self._raw.cursor()
            cur.execute(to_pg_placeholders(sql), tuple(params))
            return cur
        return self._raw.execute(sql, params)

    def executescript(self, sql: str) -> None:
        if self.dialect == DIALECT_POSTGRES:
            with self._raw.cursor() as cur:
                cur.execute(translate_ddl(sql, self.dialect))
            return
        self._raw.executescript(sql)

    # -- lifecycle ----------------------------------------------------
    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        try:
            self._raw.close()
        except Exception:  # noqa: BLE001 - closing must never mask the real error
            logger.debug("t1api.db: error closing connection", exc_info=True)

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if exc_type is None:
                self._raw.commit()
            else:
                self._raw.rollback()
        finally:
            self.close()
        return False  # never swallow the exception


class SQLBackend:
    """Base class: a named SQL dialect you can open connections to."""

    dialect: str = DIALECT_SQLITE

    def connect(self) -> _Connection:  # pragma: no cover - abstract
        raise NotImplementedError

    def executescript(self, sql: str) -> None:
        with self.connect() as conn:
            conn.executescript(translate_ddl(sql, self.dialect))

    @property
    def describe(self) -> str:  # pragma: no cover - cosmetic
        return self.dialect


class SQLiteBackend(SQLBackend):
    """One SQLite file. Multiple stores (servers/modules/jobs/billing/
    usage) can point at the *same* file — SQLite handles many tables in
    one file fine, and it keeps the single-file dev deployment simple.
    They can also point at different files; nothing here assumes a shared
    one.
    """

    dialect = DIALECT_SQLITE

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> _Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.row_factory = sqlite3.Row
        return _Connection(conn, DIALECT_SQLITE)

    @property
    def describe(self) -> str:
        return f"sqlite:{self.db_path}"


class PostgresBackend(SQLBackend):
    """PostgreSQL, for production deployments.

    Uses psycopg 3's built-in :class:`ConnectionPool` when
    ``psycopg_pool`` is installed (the ``[binary,pool]`` extra) and falls
    back to opening a connection per call otherwise — same short-lived
    model SQLite already uses, so correctness never depends on the pool
    being present, only throughput.
    """

    dialect = DIALECT_POSTGRES

    def __init__(self, dsn: str, *, pool_min: int = 1, pool_max: int = 10) -> None:
        if not dsn:
            raise ValueError("PostgresBackend requires a DSN (e.g. postgresql://user:pw@host/db)")
        self.dsn = dsn
        self._pool: Any = None
        self._pool_lock = threading.Lock()
        self._pool_min = pool_min
        self._pool_max = pool_max
        self._psycopg = _import_psycopg()

    def _get_pool(self) -> Any:
        if self._pool is not None:
            return self._pool
        with self._pool_lock:
            if self._pool is not None:
                return self._pool
            try:
                from psycopg_pool import ConnectionPool  # type: ignore
            except ImportError:
                logger.info(
                    "t1api.db: psycopg_pool not installed — using one connection per call. "
                    "Install 'hypernix[t1api-pg]' for pooling under load."
                )
                self._pool = False  # sentinel: "checked, unavailable"
                return self._pool
            from psycopg.rows import dict_row  # type: ignore

            self._pool = ConnectionPool(
                self.dsn,
                min_size=self._pool_min,
                max_size=self._pool_max,
                kwargs={"row_factory": dict_row},
                open=True,
            )
            return self._pool

    def connect(self) -> _Connection:
        from psycopg.rows import dict_row  # type: ignore

        pool = self._get_pool()
        if pool:
            # getconn() hands us a live connection; _Connection.close()
            # returns it to the pool rather than really closing it.
            raw = pool.getconn()
            return _PooledConnection(raw, pool)
        raw = self._psycopg.connect(self.dsn, row_factory=dict_row)
        return _Connection(raw, DIALECT_POSTGRES)

    @property
    def describe(self) -> str:
        return f"postgres:{_redact_dsn(self.dsn)}"


class _PooledConnection(_Connection):
    """A pooled psycopg connection: ``close()`` returns it to the pool."""

    def __init__(self, raw: Any, pool: Any) -> None:
        super().__init__(raw, DIALECT_POSTGRES)
        self._pool = pool

    def close(self) -> None:
        try:
            self._pool.putconn(self._raw)
        except Exception:  # noqa: BLE001
            logger.debug("t1api.db: error returning connection to pool", exc_info=True)


def _import_psycopg() -> Any:
    try:
        import psycopg  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "PostgreSQL support requires psycopg 3. Install it with:\n"
            "    pip install 'hypernix[t1api-pg]'\n"
            "or unset T1_DATABASE_URL to fall back to SQLite (development only)."
        ) from exc
    return psycopg


def _redact_dsn(dsn: str) -> str:
    """``postgresql://user:secret@host/db`` → ``postgresql://user:***@host/db``.

    A DSN carries a password; :attr:`SQLBackend.describe` ends up in logs
    and in ``GET /status``, so it must never carry the real one.
    """
    match = re.match(r"^(?P<scheme>\w+://)(?P<user>[^:/@]+):(?P<pw>[^@]*)@(?P<rest>.*)$", dsn)
    if not match:
        return dsn
    return f"{match['scheme']}{match['user']}:***@{match['rest']}"


def make_backend(
    *, database_url: str | None = None, db_path: str | Path | None = None
) -> SQLBackend:
    """Pick a backend: *database_url* (PostgreSQL) wins over *db_path*.

    This is the single decision point — ``create_app`` calls it once and
    every store receives the same backend instance, so a deployment
    switches SQLite → PostgreSQL by setting one environment variable
    (``T1_DATABASE_URL``) and changing nothing else.
    """
    if database_url:
        return PostgresBackend(database_url)
    return SQLiteBackend(db_path)


__all__ = [
    "DIALECT_POSTGRES",
    "DIALECT_SQLITE",
    "PostgresBackend",
    "SQLBackend",
    "SQLiteBackend",
    "make_backend",
    "to_pg_placeholders",
    "translate_ddl",
]
