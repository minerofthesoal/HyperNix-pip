"""Billing bindings on T2 keys, and the server's right to refuse them.

A **T2P key** is an ordinary T2 key that a server has attached a billing
binding to: a reference to a payment method held by a payment provider,
a spend cap, and a rate. It lets a key be issued to someone who pays for
their own usage instead of drawing on the operator's budget.

Two things are deliberately *not* in the key:

* **No card details, ever.** A binding holds provider-issued references —
  a customer token and a method token — and nothing that could be used to
  charge a card anywhere else. The T1 server is not in the cardholder
  data path and this module is what keeps it out.
* **No binding in the credential.** A key is pasted into terminals and
  config files and lands in shell history. The key says only *that* it is
  billing-bearing; the server looks the binding up by key ID.

And a server does not have to accept them. Somebody else's payment
arrangement is somebody else's business relationship, and an operator who
sells access through their own site has every reason to refuse a
credential that bills elsewhere. :class:`BillingKeyPolicy` is that
choice, and it is enforced at authentication rather than at charge time —
refusing after the work is done is a refund, not a policy.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .db import SQLiteBackend
from .errors import T1APIError, T1ErrorCode

__all__ = [
    "BillingKeyPolicy",
    "BillingBinding",
    "BillingBindingStore",
    "PaymentRequired",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS t1_billing_bindings (
    binding_id   TEXT PRIMARY KEY,
    key_id       TEXT NOT NULL UNIQUE,
    provider     TEXT NOT NULL,
    customer_ref TEXT NOT NULL,
    method_ref   TEXT NOT NULL,
    currency     TEXT NOT NULL,
    spend_cap    REAL,
    spent        REAL NOT NULL DEFAULT 0,
    active       INTEGER NOT NULL DEFAULT 1,
    created_at   REAL NOT NULL,
    note         TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_t1_billing_key ON t1_billing_bindings (key_id);
"""


class BillingKeyPolicy(StrEnum):
    """What a server does with a key that bills somewhere else."""

    #: Accept them and use the binding. For a server happy to let callers
    #: bring their own payment arrangement.
    ALLOW = "allow"

    #: Refuse them, and say where to pay instead. For an operator who
    #: sells access through their own site: a caller arriving with a
    #: foreign billing arrangement is told to go and buy access here.
    DENY = "deny"

    #: Accept the request, but never bill on the authenticating key.
    #: Payment must arrive as a *separate* T2P key in its own header, so
    #: the credential that identifies the caller and the credential that
    #: pays are different objects with different lifetimes — one can be
    #: rotated without disturbing the other, and a leaked auth key does
    #: not spend money.
    SEPARATE = "separate"


class PaymentRequired(T1APIError):
    """The server will not bill this key, and says what to do instead."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            T1ErrorCode.BILLING_PAYMENT_REQUIRED
            if hasattr(T1ErrorCode, "BILLING_PAYMENT_REQUIRED")
            else T1ErrorCode.VALIDATION_ERROR,
            message,
            details=details or {},
            http_status=402,
        )


@dataclass
class BillingBinding:
    """One key's payment arrangement.

    ``spend_cap`` is in ``currency`` units, not tokens: an operator caps
    money, and translating a token budget into money at the moment of the
    decision is what the cost calculator already does.
    """

    binding_id: str
    key_id: str
    provider: str
    customer_ref: str
    method_ref: str
    currency: str = "USD"
    spend_cap: float | None = None
    spent: float = 0.0
    active: bool = True
    created_at: float = field(default_factory=time.time)
    note: str = ""

    @property
    def remaining(self) -> float | None:
        if self.spend_cap is None:
            return None
        return max(0.0, self.spend_cap - self.spent)

    @property
    def exhausted(self) -> bool:
        return self.spend_cap is not None and self.spent >= self.spend_cap

    def public_dict(self) -> dict[str, Any]:
        """Safe to return over the API.

        The provider references are omitted. They are not secrets in the
        way a card number is, but they identify a payment method at the
        provider and there is no reason for a client to receive them.
        """
        return {
            "binding_id": self.binding_id,
            "key_id": self.key_id,
            "provider": self.provider,
            "currency": self.currency,
            "spend_cap": self.spend_cap,
            "spent": round(self.spent, 6),
            "remaining": self.remaining,
            "active": self.active,
            "created_at": self.created_at,
        }


class BillingBindingStore:
    """Bindings, keyed by the key they belong to.

    One binding per key, enforced by the schema rather than by a check:
    two bindings on one key is an unanswerable question at charge time,
    and a UNIQUE constraint answers it at write time instead.
    """

    def __init__(self, backend: SQLiteBackend | None = None) -> None:
        self.backend = backend or SQLiteBackend()
        self._lock = threading.Lock()
        self.backend.executescript(_SCHEMA)

    def bind(
        self,
        key_id: str,
        *,
        provider: str,
        customer_ref: str,
        method_ref: str,
        currency: str = "USD",
        spend_cap: float | None = None,
        note: str = "",
    ) -> BillingBinding:
        """Attach a payment arrangement to a key.

        Refuses anything that looks like a card number rather than a
        provider reference. The check is crude on purpose: it cannot
        prove a string is safe, but a 13-19 digit run is the one shape
        that must never be stored here, and catching it at the boundary
        beats discovering it in a database dump.
        """
        for label, value in (("customer_ref", customer_ref), ("method_ref", method_ref)):
            digits = "".join(ch for ch in value if ch.isdigit())
            if len(digits) >= 13 and len(digits) == len(value.replace(" ", "").replace("-", "")):
                raise T1APIError(
                    T1ErrorCode.VALIDATION_ERROR,
                    f"{label} looks like a card number. This server stores provider "
                    "references only and must never be in the cardholder data path.",
                )
        if spend_cap is not None and spend_cap <= 0:
            raise T1APIError(
                T1ErrorCode.VALIDATION_ERROR,
                "A spend cap must be positive. Use no cap for unlimited, rather than "
                "zero, which would refuse every request and read as a bug.",
            )

        binding = BillingBinding(
            binding_id=f"bind_{uuid.uuid4().hex[:16]}",
            key_id=key_id,
            provider=provider,
            customer_ref=customer_ref,
            method_ref=method_ref,
            currency=currency,
            spend_cap=spend_cap,
            note=note,
        )
        with self._lock, self.backend.connect() as conn:
            conn.execute(
                "INSERT INTO t1_billing_bindings (binding_id, key_id, provider, "
                "customer_ref, method_ref, currency, spend_cap, spent, active, "
                "created_at, note) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(key_id) DO UPDATE SET provider=excluded.provider, "
                "customer_ref=excluded.customer_ref, method_ref=excluded.method_ref, "
                "currency=excluded.currency, spend_cap=excluded.spend_cap, "
                "active=1, note=excluded.note",
                (
                    binding.binding_id, binding.key_id, binding.provider,
                    binding.customer_ref, binding.method_ref, binding.currency,
                    binding.spend_cap, 0.0, 1, binding.created_at, binding.note,
                ),
            )
        return self.get(key_id) or binding

    def get(self, key_id: str) -> BillingBinding | None:
        with self.backend.connect() as conn:
            row = conn.execute(
                "SELECT * FROM t1_billing_bindings WHERE key_id = ?", (key_id,)
            ).fetchone()
        if row is None:
            return None
        return BillingBinding(
            binding_id=row["binding_id"],
            key_id=row["key_id"],
            provider=row["provider"],
            customer_ref=row["customer_ref"],
            method_ref=row["method_ref"],
            currency=row["currency"],
            spend_cap=row["spend_cap"],
            spent=float(row["spent"] or 0.0),
            active=bool(row["active"]),
            created_at=float(row["created_at"]),
            note=row["note"] or "",
        )

    def release(self, key_id: str) -> bool:
        """Drop a key's binding.

        Called when a key is revoked. A binding that outlives its key is a
        standing authorisation to charge someone for a credential that no
        longer exists.
        """
        with self._lock, self.backend.connect() as conn:
            cur = conn.execute(
                "DELETE FROM t1_billing_bindings WHERE key_id = ?", (key_id,)
            )
            return cur.rowcount > 0

    def transfer(self, old_key_id: str, new_key_id: str) -> BillingBinding | None:
        """Move a binding to the key that replaced it.

        Rotation replaces a credential without ending the arrangement
        behind it, so the binding follows — carrying its spend with it,
        because a rotation that reset ``spent`` to zero would be a way to
        mint unlimited spend out of a cap.

        The destination is overwritten if it somehow already has one: the
        UNIQUE constraint on ``key_id`` makes two bindings on one key
        unrepresentable, and a freshly created key having one is not a
        state that should exist.
        """
        binding = self.get(old_key_id)
        if binding is None:
            return None
        with self._lock, self.backend.connect() as conn:
            conn.execute(
                "DELETE FROM t1_billing_bindings WHERE key_id = ?", (new_key_id,)
            )
            conn.execute(
                "UPDATE t1_billing_bindings SET key_id = ? WHERE key_id = ?",
                (new_key_id, old_key_id),
            )
        return self.get(new_key_id)

    def attach_to(self, keymaster: Any) -> None:
        """Follow a Keymaster's key lifecycle.

        Without this, ``release`` and ``transfer`` are methods nobody
        calls: revocation happens in the security layer, which knows
        nothing about billing, and a binding left behind on a dead key ID
        is a spend cap waiting to be inherited.

        Registration is best-effort. An older Keymaster without the hooks
        still works — it simply does not prune, which is the behaviour
        that existed before this method — so a version mismatch degrades
        instead of failing at startup.
        """
        if hasattr(keymaster, "on_revoke"):
            keymaster.on_revoke(lambda key_id, _reason="": self.release(key_id))
        if hasattr(keymaster, "on_rotate"):
            keymaster.on_rotate(self.transfer)

    def record_spend(self, key_id: str, amount: float) -> BillingBinding | None:
        """Add to what a binding has spent.

        Returns the updated binding, or None when there is none — a
        caller with no binding is not an error here, because the quota
        cascade has its own answer for that.
        """
        if amount <= 0:
            return self.get(key_id)
        with self._lock, self.backend.connect() as conn:
            conn.execute(
                "UPDATE t1_billing_bindings SET spent = spent + ? WHERE key_id = ?",
                (float(amount), key_id),
            )
        return self.get(key_id)

    def assert_within_cap(self, key_id: str, estimated: float = 0.0) -> None:
        """Refuse before the work, not after.

        An over-cap request that is discovered at charge time has already
        cost the operator the inference. The cap is checked against what
        the request is *estimated* to cost, for the same reason.
        """
        binding = self.get(key_id)
        if binding is None or binding.spend_cap is None:
            return
        if binding.spent + max(0.0, estimated) > binding.spend_cap:
            raise PaymentRequired(
                "This key's spend cap is reached.",
                details={
                    "reason": "spend_cap_reached",
                    "spend_cap": binding.spend_cap,
                    "spent": round(binding.spent, 6),
                    "currency": binding.currency,
                },
            )

    def list_bindings(self) -> list[BillingBinding]:
        with self.backend.connect() as conn:
            rows = conn.execute(
                "SELECT key_id FROM t1_billing_bindings ORDER BY created_at"
            ).fetchall()
        return [b for b in (self.get(r["key_id"]) for r in rows) if b is not None]

    def to_json(self) -> str:
        return json.dumps([b.public_dict() for b in self.list_bindings()], indent=2)
