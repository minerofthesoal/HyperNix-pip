"""t1api.netpolicy — IP allowlists, blocklists, and forced per-subject limits.

Implements three spec requirements that Beta 2 could only *record*
client-side (``waiter -B``/``-W``/``-a``/``-r`` stored intent in the
local config and printed "not wired to a server endpoint yet"):

* "Add IP allowlists." — :meth:`NetworkPolicy.allow`
* "Add optional IP blacklists." — :meth:`NetworkPolicy.block`
* the design principle's own bullet: the server decides "if the non
  whitelisted user/person trying to get access is both, not black listed
  and that the server allows non whitelisted users to connect" — which
  is exactly the three-way decision :meth:`NetworkPolicy.evaluate`
  makes, and the reason ``allow_unlisted`` is a first-class server-side
  setting rather than an implied default.
* "-r = force limits on specific T1 key/server IDs" — :meth:`set_limit`,
  consumed by :mod:`t1api.ratelimit`.

Decision order (deliberate, and the order the tests pin):

1. **Blocklist wins over everything.** A blocked address is denied even
   if it also appears on the allowlist — a later allowlist entry must
   never silently un-block something an operator explicitly blocked. To
   un-block, you appeal (remove the block); that's what an appeal *is*.
2. **Allowlisted → allowed**, regardless of ``allow_unlisted``.
3. **Neither** → allowed only if ``allow_unlisted`` is true.

Entries are single addresses or CIDR networks (``10.0.0.0/8``,
``100.64.0.0/10`` for Tailscale), matched with :mod:`ipaddress` so
``10.1.2.3`` matches a ``10.0.0.0/8`` rule without any string
prefix-matching guesswork. Anything unparseable is rejected at write
time, not silently stored as a rule that can never match.
"""
from __future__ import annotations

import ipaddress
import logging
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .db import SQLBackend, SQLiteBackend
from .errors import T1APIError, T1ErrorCode

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS net_policy_entries (
    entry_id TEXT PRIMARY KEY,
    cidr TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    expires_at REAL
);
CREATE INDEX IF NOT EXISTS idx_netpolicy_kind ON net_policy_entries(kind);
CREATE TABLE IF NOT EXISTS forced_limits (
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    requests_per_window INTEGER,
    tokens_per_window INTEGER,
    window_seconds REAL NOT NULL DEFAULT 60,
    reason TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    PRIMARY KEY (subject_type, subject_id)
);
"""


class EntryKind(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"


class Decision(StrEnum):
    ALLOWED_LISTED = "allowed_listed"  # explicitly allowlisted
    ALLOWED_UNLISTED = "allowed_unlisted"  # not listed, server permits unlisted
    DENIED_BLOCKED = "denied_blocked"  # explicitly blocklisted
    DENIED_NOT_LISTED = "denied_not_listed"  # not listed, server requires allowlisting

    @property
    def allowed(self) -> bool:
        return self in (Decision.ALLOWED_LISTED, Decision.ALLOWED_UNLISTED)


@dataclass
class PolicyEntry:
    entry_id: str
    cidr: str
    kind: EntryKind
    reason: str
    created_by: str
    created_at: float
    expires_at: float | None = None

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "cidr": self.cidr,
            "kind": self.kind.value,
            "reason": self.reason,
            "created_by": self.created_by[:8] + "…" if len(self.created_by) > 8 else self.created_by,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "expired": self.is_expired,
        }


@dataclass
class ForcedLimit:
    """An operator-imposed cap on one T1 key or one server (``waiter -r``).

    Both limits are optional: setting only ``requests_per_window`` caps
    request rate and leaves token throughput alone, and vice versa. A
    forced limit is a *ceiling* — :mod:`t1api.ratelimit` applies it in
    addition to the configured default rules, never instead of them, so
    ``-r`` can only tighten, never widen, what a subject is allowed.
    """

    subject_type: str  # "key" | "server"
    subject_id: str
    requests_per_window: int | None
    tokens_per_window: int | None
    window_seconds: float
    reason: str = ""
    created_by: str = ""
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_type": self.subject_type,
            "subject_id": self.subject_id[:12] + "…" if len(self.subject_id) > 12 else self.subject_id,
            "requests_per_window": self.requests_per_window,
            "tokens_per_window": self.tokens_per_window,
            "window_seconds": self.window_seconds,
            "reason": self.reason,
            "created_at": self.created_at,
        }


def parse_cidr(value: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    """Parse a single address or CIDR into a network.

    A bare ``10.1.2.3`` becomes ``10.1.2.3/32`` so single addresses and
    ranges are matched by exactly the same code path.
    """
    text = value.strip()
    if not text:
        raise T1APIError(
            T1ErrorCode.VALIDATION_ERROR, "Empty IP/CIDR value.", http_status=422
        )
    try:
        return ipaddress.ip_network(text, strict=False)
    except ValueError as exc:
        raise T1APIError(
            T1ErrorCode.VALIDATION_ERROR,
            f"'{value}' is not a valid IP address or CIDR range.",
            details={"value": value},
            http_status=422,
        ) from exc


class NetworkPolicy:
    """Persistent IP allow/block lists plus forced per-subject limits.

    Entries live in SQL (so they survive a restart and are shared across
    worker processes) but are cached in memory and refreshed on write,
    because :meth:`evaluate` runs on *every* request and must not do a
    database round-trip per call. Multi-process deployments pick up
    another worker's writes within :attr:`refresh_interval` seconds.
    """

    def __init__(
        self,
        backend: SQLBackend | None = None,
        *,
        allow_unlisted: bool = True,
        refresh_interval: float = 5.0,
    ) -> None:
        self.backend = backend or SQLiteBackend()
        self.allow_unlisted = allow_unlisted
        self.refresh_interval = refresh_interval
        self._lock = threading.RLock()
        self._cache: list[PolicyEntry] = []
        self._cache_loaded_at = 0.0
        self.backend.executescript(_SCHEMA)
        self._refresh(force=True)

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def _refresh(self, *, force: bool = False) -> None:
        with self._lock:
            if not force and (time.monotonic() - self._cache_loaded_at) < self.refresh_interval:
                return
            with self.backend.connect() as conn:
                rows = conn.execute("SELECT * FROM net_policy_entries").fetchall()
            self._cache = [_row_to_entry(r) for r in rows]
            self._cache_loaded_at = time.monotonic()

    # ------------------------------------------------------------------
    # Evaluation — the hot path
    # ------------------------------------------------------------------

    def evaluate(self, client_ip: str | None) -> tuple[Decision, str | None]:
        """Decide whether *client_ip* may connect.

        Returns ``(decision, matched_cidr)``. An unparseable or missing
        address is treated as unlisted rather than as an error: the
        address comes from the transport layer, and a deployment behind
        a proxy that doesn't forward one should not have every request
        fail — it should fall under whatever ``allow_unlisted`` says,
        which is the operator's explicit choice.
        """
        self._refresh()
        if not client_ip:
            return (
                (Decision.ALLOWED_UNLISTED, None)
                if self.allow_unlisted
                else (Decision.DENIED_NOT_LISTED, None)
            )
        try:
            addr = ipaddress.ip_address(client_ip.strip())
        except ValueError:
            return (
                (Decision.ALLOWED_UNLISTED, None)
                if self.allow_unlisted
                else (Decision.DENIED_NOT_LISTED, None)
            )

        with self._lock:
            entries = list(self._cache)

        allow_match: str | None = None
        for entry in entries:
            if entry.is_expired:
                continue
            try:
                network = ipaddress.ip_network(entry.cidr, strict=False)
            except ValueError:  # pragma: no cover - rejected at write time
                continue
            if addr.version != network.version or addr not in network:
                continue
            if entry.kind == EntryKind.BLOCK:
                # Blocklist wins immediately — no allowlist entry can
                # override an explicit block (see module docstring).
                return Decision.DENIED_BLOCKED, entry.cidr
            allow_match = entry.cidr

        if allow_match is not None:
            return Decision.ALLOWED_LISTED, allow_match
        if self.allow_unlisted:
            return Decision.ALLOWED_UNLISTED, None
        return Decision.DENIED_NOT_LISTED, None

    def require_allowed(self, client_ip: str | None) -> Decision:
        """:meth:`evaluate`, but raises the appropriate stable error.

        Both denial reasons map to 403 with distinct messages so an
        operator reading a client's report can tell "you are banned"
        apart from "this server only accepts allowlisted addresses"
        without needing server logs.
        """
        decision, matched = self.evaluate(client_ip)
        if decision.allowed:
            return decision
        if decision == Decision.DENIED_BLOCKED:
            raise T1APIError(
                T1ErrorCode.IP_BLOCKED,
                "This address is blocked by the server's IP blacklist.",
                details={"matched": matched},
                http_status=403,
            )
        raise T1APIError(
            T1ErrorCode.IP_NOT_ALLOWLISTED,
            "This server only accepts connections from allowlisted addresses.",
            http_status=403,
        )

    # ------------------------------------------------------------------
    # Mutation (admin-only at the HTTP layer)
    # ------------------------------------------------------------------

    def _upsert(
        self,
        cidr: str,
        kind: EntryKind,
        *,
        reason: str,
        created_by: str,
        expires_at: float | None,
    ) -> PolicyEntry:
        import uuid

        network = parse_cidr(cidr)
        normalized = str(network)
        entry = PolicyEntry(
            entry_id=uuid.uuid4().hex,
            cidr=normalized,
            kind=kind,
            reason=reason,
            created_by=created_by,
            created_at=time.time(),
            expires_at=expires_at,
        )
        with self._lock, self.backend.connect() as conn:
            # Idempotent by CIDR: re-adding an address updates its kind
            # and reason rather than erroring, so `waiter -B <ip>` twice
            # is harmless and `-W` on a blocked address is an explicit,
            # visible kind change rather than a duplicate row.
            conn.execute(
                """INSERT INTO net_policy_entries
                   (entry_id, cidr, kind, reason, created_by, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(cidr) DO UPDATE SET
                     kind=excluded.kind, reason=excluded.reason,
                     created_by=excluded.created_by, created_at=excluded.created_at,
                     expires_at=excluded.expires_at""",
                (
                    entry.entry_id,
                    entry.cidr,
                    entry.kind.value,
                    entry.reason,
                    entry.created_by,
                    entry.created_at,
                    entry.expires_at,
                ),
            )
        self._refresh(force=True)
        logger.info("t1api.netpolicy: %s %s (%s)", kind.value, normalized, reason or "no reason given")
        return entry

    def block(
        self,
        cidr: str,
        *,
        reason: str = "",
        created_by: str = "",
        expires_at: float | None = None,
    ) -> PolicyEntry:
        """``waiter -B`` — blacklist an address or range."""
        return self._upsert(cidr, EntryKind.BLOCK, reason=reason, created_by=created_by, expires_at=expires_at)

    def allow(
        self,
        cidr: str,
        *,
        reason: str = "",
        created_by: str = "",
        expires_at: float | None = None,
    ) -> PolicyEntry:
        """``waiter -W`` — allowlist an address or range."""
        return self._upsert(cidr, EntryKind.ALLOW, reason=reason, created_by=created_by, expires_at=expires_at)

    def remove(self, cidr: str) -> bool:
        """``waiter -a`` — appeal: drop an entry entirely.

        Returns True if something was removed. Removing a block is the
        appeal path; removing an allow revokes a grant. Both are the same
        operation because both are "this rule no longer applies".
        """
        normalized = str(parse_cidr(cidr))
        with self._lock, self.backend.connect() as conn:
            existing = conn.execute(
                "SELECT COUNT(*) AS n FROM net_policy_entries WHERE cidr = ?", (normalized,)
            ).fetchone()
            conn.execute("DELETE FROM net_policy_entries WHERE cidr = ?", (normalized,))
        self._refresh(force=True)
        return int(existing["n"]) > 0

    def list_entries(self, *, kind: EntryKind | None = None) -> list[PolicyEntry]:
        self._refresh(force=True)
        with self._lock:
            entries = list(self._cache)
        if kind is not None:
            entries = [e for e in entries if e.kind == kind]
        return sorted(entries, key=lambda e: (e.kind.value, e.cidr))

    def set_allow_unlisted(self, value: bool) -> None:
        """Flip "does this server accept non-allowlisted clients at all".

        Held in memory, not the database: it's a deployment posture set
        by ``T1_ALLOW_UNLISTED_CLIENTS`` (or ``waiter serv -L``'s
        server-side equivalent), and a restart should return to whatever
        the environment says rather than to whatever the last API call
        happened to set.
        """
        with self._lock:
            self.allow_unlisted = bool(value)
        logger.info("t1api.netpolicy: allow_unlisted=%s", value)

    # ------------------------------------------------------------------
    # Forced limits (waiter -r)
    # ------------------------------------------------------------------

    def set_limit(
        self,
        subject_type: str,
        subject_id: str,
        *,
        requests_per_window: int | None = None,
        tokens_per_window: int | None = None,
        window_seconds: float = 60.0,
        reason: str = "",
        created_by: str = "",
    ) -> ForcedLimit:
        if subject_type not in ("key", "server"):
            raise T1APIError(
                T1ErrorCode.VALIDATION_ERROR,
                "Forced limits apply to subject_type 'key' or 'server'.",
                details={"subject_type": subject_type},
                http_status=422,
            )
        if requests_per_window is None and tokens_per_window is None:
            raise T1APIError(
                T1ErrorCode.VALIDATION_ERROR,
                "A forced limit must set requests_per_window, tokens_per_window, or both.",
                http_status=422,
            )
        limit = ForcedLimit(
            subject_type=subject_type,
            subject_id=subject_id,
            requests_per_window=requests_per_window,
            tokens_per_window=tokens_per_window,
            window_seconds=window_seconds,
            reason=reason,
            created_by=created_by,
            created_at=time.time(),
        )
        with self._lock, self.backend.connect() as conn:
            conn.execute(
                """INSERT INTO forced_limits
                   (subject_type, subject_id, requests_per_window, tokens_per_window,
                    window_seconds, reason, created_by, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(subject_type, subject_id) DO UPDATE SET
                     requests_per_window=excluded.requests_per_window,
                     tokens_per_window=excluded.tokens_per_window,
                     window_seconds=excluded.window_seconds,
                     reason=excluded.reason, created_by=excluded.created_by,
                     created_at=excluded.created_at""",
                (
                    limit.subject_type,
                    limit.subject_id,
                    limit.requests_per_window,
                    limit.tokens_per_window,
                    limit.window_seconds,
                    limit.reason,
                    limit.created_by,
                    limit.created_at,
                ),
            )
        return limit

    def get_limit(self, subject_type: str, subject_id: str) -> ForcedLimit | None:
        with self._lock, self.backend.connect() as conn:
            row = conn.execute(
                "SELECT * FROM forced_limits WHERE subject_type = ? AND subject_id = ?",
                (subject_type, subject_id),
            ).fetchone()
        return _row_to_limit(row) if row else None

    def clear_limit(self, subject_type: str, subject_id: str) -> bool:
        with self._lock, self.backend.connect() as conn:
            existing = conn.execute(
                "SELECT COUNT(*) AS n FROM forced_limits WHERE subject_type = ? AND subject_id = ?",
                (subject_type, subject_id),
            ).fetchone()
            conn.execute(
                "DELETE FROM forced_limits WHERE subject_type = ? AND subject_id = ?",
                (subject_type, subject_id),
            )
        return int(existing["n"]) > 0

    def list_limits(self) -> list[ForcedLimit]:
        with self._lock, self.backend.connect() as conn:
            rows = conn.execute("SELECT * FROM forced_limits ORDER BY created_at DESC").fetchall()
        return [_row_to_limit(r) for r in rows]


def _row_to_entry(row: Any) -> PolicyEntry:
    return PolicyEntry(
        entry_id=row["entry_id"],
        cidr=row["cidr"],
        kind=EntryKind(row["kind"]),
        reason=row["reason"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
    )


def _row_to_limit(row: Any) -> ForcedLimit:
    return ForcedLimit(
        subject_type=row["subject_type"],
        subject_id=row["subject_id"],
        requests_per_window=row["requests_per_window"],
        tokens_per_window=row["tokens_per_window"],
        window_seconds=row["window_seconds"],
        reason=row["reason"],
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


__all__ = [
    "Decision",
    "EntryKind",
    "ForcedLimit",
    "NetworkPolicy",
    "PolicyEntry",
    "parse_cidr",
]
