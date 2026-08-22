"""t1api.keys — the key directory: listing, import, and assignment.

Backs the spec's ``GET /keys``, ``POST /keys/import`` and
``POST /keys/assign``, and one thing they imply that matters more than
the endpoints themselves.

**Where a caller's plan comes from.** Beta 2's ``POST /models/route``
took ``plan`` from the request body. That is precisely the shape the
design principle forbids — "The client must NEVER be trusted to decide
what it is allowed to access... The server determines which models the
user can access, which limits apply, which fallback models are allowed."
A client that names its own plan can name the most generous one. Beta 3
moves plan ownership here: a plan is a property of an **assignment**
that an administrator records against a key, and
:meth:`KeyDirectory.resolve_plan` is what the routing layer asks. A
client-supplied plan is now, at most, a request that must match what the
server already believes.

Division of responsibility with Keymaster
-----------------------------------------
:mod:`hypernix.keymaster` owns key *lifecycle* — creation, the raw key
string, encryption at rest, rotation, revocation, expiry. This module
owns T1-specific *assignment* — which plan, account, user, servers, and
model subset a key is bound to — in its own table. Nothing here reaches
into Keymaster's private state or writes its files; a key can be rotated
by Keymaster without this module knowing, and an assignment survives
because it is keyed by ``key_id``, which rotation preserves in
``rotated_from`` lineage.

Secrets
-------
No method in this module ever returns a raw key string, and
:meth:`import_payload` deliberately discards the raw keys from its
return value even though it must read them to import. ``GET /keys``
returns masked identifiers and metadata only — "Never expose raw
credentials through API responses."
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..keymaster import Keymaster, KeyMeta, KeyType
from .db import SQLBackend, SQLiteBackend
from .errors import T1APIError, T1ErrorCode
from .registry import ModelRegistry

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS key_assignments (
    key_id TEXT PRIMARY KEY,
    plan TEXT NOT NULL DEFAULT '',
    account_id TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL DEFAULT '',
    server_ids TEXT NOT NULL DEFAULT '[]',
    allowed_models TEXT NOT NULL DEFAULT '[]',
    note TEXT NOT NULL DEFAULT '',
    assigned_by TEXT NOT NULL DEFAULT '',
    assigned_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_key_assign_account ON key_assignments(account_id);
CREATE INDEX IF NOT EXISTS idx_key_assign_plan ON key_assignments(plan);
"""


@dataclass
class KeyAssignment:
    """What a key is bound to, server-side.

    ``allowed_models`` empty means "whatever the plan's routing policy
    permits" — the normal case. A non-empty list is a *narrowing*: the
    key may only use models on it, and every entry was checked against
    the model registry when the assignment was written, so an assignment
    can never smuggle in an unregistered model id.
    """

    key_id: str
    plan: str = ""
    account_id: str = ""
    user_id: str = ""
    server_ids: list[str] = field(default_factory=list)
    allowed_models: list[str] = field(default_factory=list)
    note: str = ""
    assigned_by: str = ""
    assigned_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        # Masked here too: an assignment record is returned inside
        # GET /keys and POST /keys/assign responses, and every identifier
        # crossing the API boundary uses the same masked form.
        return {
            "key_id": mask_key_id(self.key_id),
            "plan": self.plan,
            "account_id": self.account_id,
            "user_id": self.user_id,
            "server_ids": list(self.server_ids),
            "allowed_models": list(self.allowed_models),
            "note": self.note,
            "assigned_at": self.assigned_at,
        }


def mask_key_id(key_id: str, keep: int = 12) -> str:
    if not key_id:
        return ""
    return key_id[:keep] + "…" if len(key_id) > keep else key_id


@dataclass
class KeySummary:
    """The public, credential-free view of a key. This is the *only*
    shape ``GET /keys`` ever returns."""

    key_id: str
    key_type: str
    scopes: list[str]
    active: bool
    created_at: float
    expires_at: float | None
    prefix: str
    server_id: str
    usage_count: int
    request_count: int
    usage_cap: int | None
    request_limit: int | None
    rotated_from: str | None
    assignment: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "key_id": mask_key_id(self.key_id),
            "key_type": self.key_type,
            "scopes": self.scopes,
            "active": self.active,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "prefix": self.prefix,
            "server_id": self.server_id,
            "usage_count": self.usage_count,
            "request_count": self.request_count,
            "usage_cap": self.usage_cap,
            "request_limit": self.request_limit,
            "rotated_from": mask_key_id(self.rotated_from) if self.rotated_from else None,
            "assignment": self.assignment,
        }


class KeyDirectory:
    """Key listing, import, and assignment on top of Keymaster."""

    def __init__(
        self,
        keymaster: Keymaster,
        registry: ModelRegistry,
        backend: SQLBackend | None = None,
        *,
        default_plan: str = "free",
    ) -> None:
        self.keymaster = keymaster
        self.registry = registry
        self.backend = backend or SQLiteBackend()
        self.default_plan = default_plan
        self._lock = threading.RLock()
        self.backend.executescript(_SCHEMA)

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list_keys(
        self,
        *,
        requester_key_id: str,
        is_admin: bool,
        key_type: str | None = None,
        include_inactive: bool = False,
    ) -> list[KeySummary]:
        """List keys. A non-admin caller sees exactly one key: their own.

        This is the scope rule "Non-admin tokens must not... access other
        users' secrets" applied to the key directory. It is enforced here
        rather than in the router so the same guarantee holds for any
        future caller of this service.
        """
        typed = KeyType(key_type) if key_type else None
        metas = self.keymaster.list(key_type=typed, active_only=not include_inactive, include_expired=include_inactive)
        if not is_admin:
            metas = [m for m in metas if m.key_id == requester_key_id]
        return [self._summarize(m) for m in metas]

    def get_key(self, key_id: str, *, requester_key_id: str, is_admin: bool) -> KeySummary:
        if not is_admin and key_id != requester_key_id:
            raise T1APIError(
                T1ErrorCode.AUTH_INSUFFICIENT_SCOPE,
                "You may only inspect your own key.",
                http_status=403,
            )
        meta = self.keymaster.get(key_id)
        if meta is None:
            raise T1APIError(T1ErrorCode.NOT_FOUND, f"Key {mask_key_id(key_id)} not found.", http_status=404)
        return self._summarize(meta)

    def _summarize(self, meta: KeyMeta) -> KeySummary:
        assignment = self.get_assignment(meta.key_id)
        return KeySummary(
            key_id=meta.key_id,
            key_type=meta.key_type.value,
            scopes=sorted(s.value for s in meta.scopes),
            active=meta.active,
            created_at=meta.created_at,
            expires_at=meta.expires_at,
            prefix=meta.prefix,
            server_id=meta.server_id,
            usage_count=meta.usage_count,
            request_count=meta.request_count,
            usage_cap=meta.usage_cap,
            request_limit=meta.request_limit,
            rotated_from=meta.rotated_from,
            assignment=assignment.to_dict() if assignment else None,
        )

    # ------------------------------------------------------------------
    # Import
    # ------------------------------------------------------------------

    def import_payload(self, payload: dict[str, Any], *, imported_by: str) -> dict[str, Any]:
        """Import a Keymaster export payload (``{"keys": [...]}``).

        Admin-only at the HTTP layer. The payload contains raw key
        strings by necessity — that is what an export *is* — so this
        method is careful in three ways: it validates the shape before
        handing anything to Keymaster, it never logs the payload, and its
        return value contains only masked key ids and counts. Duplicate
        key ids are skipped by Keymaster (existing key wins), which makes
        a repeated import idempotent rather than destructive.
        """
        if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
            raise T1APIError(
                T1ErrorCode.VALIDATION_ERROR,
                "Import payload must be a Keymaster export object: {\"keys\": [ ... ]}.",
                http_status=422,
            )
        records = payload["keys"]
        if not records:
            raise T1APIError(
                T1ErrorCode.VALIDATION_ERROR, "Import payload contains no keys.", http_status=422
            )
        for index, record in enumerate(records):
            if not isinstance(record, dict) or "key_id" not in record or "key" not in record:
                raise T1APIError(
                    T1ErrorCode.VALIDATION_ERROR,
                    f"Key record #{index} is missing required fields (key_id, key).",
                    details={"index": index},
                    http_status=422,
                )

        before = {m.key_id for m in self.keymaster.list(active_only=False, include_expired=True)}
        imported_ids = self.keymaster.import_keys({"keys": records})
        skipped = [r["key_id"] for r in records if r["key_id"] in before]

        logger.info(
            "t1api.keys: imported %d key(s), skipped %d duplicate(s) (requested by %s)",
            len(imported_ids),
            len(skipped),
            mask_key_id(imported_by, keep=8),
        )
        return {
            "imported": len(imported_ids),
            "skipped": len(skipped),
            "imported_key_ids": [mask_key_id(k) for k in imported_ids],
            "skipped_key_ids": [mask_key_id(k) for k in skipped],
        }

    # ------------------------------------------------------------------
    # Assignment
    # ------------------------------------------------------------------

    def assign(
        self,
        key_id: str,
        *,
        assigned_by: str,
        plan: str | None = None,
        account_id: str | None = None,
        user_id: str | None = None,
        server_ids: list[str] | None = None,
        allowed_models: list[str] | None = None,
        note: str | None = None,
        server_validator: Any = None,
    ) -> KeyAssignment:
        """Bind a key to a plan/account/user/servers/model subset.

        Every referenced entity is validated before anything is written:

        * the key must exist in Keymaster,
        * each model id must be in the registry (``MODEL_NOT_SUPPORTED``
          otherwise) — this is the registry rule applied to assignment,
          so "assigned to a key" can't become a way to name a model the
          registry never heard of,
        * each server id must exist, when a *server_validator* (normally
          :meth:`ServerRegistry.require`) is supplied.

        Fields left as ``None`` keep their existing value, so this is a
        partial update; pass an empty list to clear a list field.
        """
        if self.keymaster.get(key_id) is None:
            raise T1APIError(
                T1ErrorCode.NOT_FOUND, f"Key {mask_key_id(key_id)} not found.", http_status=404
            )
        for model_id in allowed_models or []:
            self.registry.require(model_id)
        if server_validator is not None:
            for server_id in server_ids or []:
                server_validator(server_id)

        existing = self.get_assignment(key_id)
        assignment = KeyAssignment(
            key_id=key_id,
            plan=_pick(plan, existing.plan if existing else self.default_plan),
            account_id=_pick(account_id, existing.account_id if existing else ""),
            user_id=_pick(user_id, existing.user_id if existing else ""),
            server_ids=list(server_ids) if server_ids is not None else (existing.server_ids if existing else []),
            allowed_models=(
                list(allowed_models) if allowed_models is not None else (existing.allowed_models if existing else [])
            ),
            note=_pick(note, existing.note if existing else ""),
            assigned_by=assigned_by,
            assigned_at=time.time(),
        )
        with self._lock, self.backend.connect() as conn:
            conn.execute(
                """INSERT INTO key_assignments
                   (key_id, plan, account_id, user_id, server_ids, allowed_models,
                    note, assigned_by, assigned_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(key_id) DO UPDATE SET
                     plan=excluded.plan, account_id=excluded.account_id,
                     user_id=excluded.user_id, server_ids=excluded.server_ids,
                     allowed_models=excluded.allowed_models, note=excluded.note,
                     assigned_by=excluded.assigned_by, assigned_at=excluded.assigned_at""",
                (
                    assignment.key_id,
                    assignment.plan,
                    assignment.account_id,
                    assignment.user_id,
                    json.dumps(assignment.server_ids),
                    json.dumps(assignment.allowed_models),
                    assignment.note,
                    assignment.assigned_by,
                    assignment.assigned_at,
                ),
            )
        return assignment

    def get_assignment(self, key_id: str) -> KeyAssignment | None:
        with self._lock, self.backend.connect() as conn:
            row = conn.execute("SELECT * FROM key_assignments WHERE key_id = ?", (key_id,)).fetchone()
        return _row_to_assignment(row) if row else None

    def list_assignments(self, *, account_id: str | None = None) -> list[KeyAssignment]:
        query = "SELECT * FROM key_assignments"
        params: list[Any] = []
        if account_id is not None:
            query += " WHERE account_id = ?"
            params.append(account_id)
        query += " ORDER BY assigned_at DESC"
        with self._lock, self.backend.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_row_to_assignment(r) for r in rows]

    # ------------------------------------------------------------------
    # Server-side authority (the reason this module exists)
    # ------------------------------------------------------------------

    def resolve_plan(self, key_id: str, *, requested_plan: str | None = None) -> str:
        """The plan this key actually has.

        A *requested_plan* is honoured only if it matches the assigned
        plan; a mismatch is a scope error, not a silent downgrade,
        because a client asking for a plan it doesn't hold is either a
        bug worth surfacing or an escalation attempt worth refusing. With
        no assignment on record the key gets :attr:`default_plan` — and a
        client naming anything other than that default still gets the
        refusal.
        """
        assignment = self.get_assignment(key_id)
        actual = assignment.plan if assignment and assignment.plan else self.default_plan
        if requested_plan is not None and requested_plan != actual:
            raise T1APIError(
                T1ErrorCode.AUTH_INSUFFICIENT_SCOPE,
                f"This key is assigned to plan '{actual}', not '{requested_plan}'. "
                "Plans are assigned server-side (POST /keys/assign); a client cannot select one.",
                details={"assigned_plan": actual},
                http_status=403,
            )
        return actual

    def assert_model_allowed(self, key_id: str, model_id: str) -> None:
        """Enforce a key's model narrowing, if it has one."""
        assignment = self.get_assignment(key_id)
        if assignment is None or not assignment.allowed_models:
            return
        if model_id not in assignment.allowed_models:
            raise T1APIError(
                T1ErrorCode.AUTH_INSUFFICIENT_SCOPE,
                f"Model '{model_id}' is not in this key's assigned model list.",
                details={"allowed_models": assignment.allowed_models},
                http_status=403,
            )

    def usage_identity(self, key_id: str) -> tuple[str, str]:
        """``(user_id, account_id)`` for usage attribution, or empty
        strings. Lets usage be reported per-user and per-account without
        every call site knowing how assignment works."""
        assignment = self.get_assignment(key_id)
        if assignment is None:
            return "", ""
        return assignment.user_id, assignment.account_id


def _pick(new: str | None, existing: str) -> str:
    return existing if new is None else new


def _row_to_assignment(row: Any) -> KeyAssignment:
    return KeyAssignment(
        key_id=row["key_id"],
        plan=row["plan"],
        account_id=row["account_id"],
        user_id=row["user_id"],
        server_ids=json.loads(row["server_ids"] or "[]"),
        allowed_models=json.loads(row["allowed_models"] or "[]"),
        note=row["note"],
        assigned_by=row["assigned_by"],
        assigned_at=row["assigned_at"],
    )


__all__ = ["KeyAssignment", "KeyDirectory", "KeySummary", "mask_key_id"]
