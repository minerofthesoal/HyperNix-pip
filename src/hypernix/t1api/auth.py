"""t1api.auth — the T1 API's authentication/authorization glue.

Per the spec's "HYPERNIX-PIP INTEGRATION" requirement, this module does
**not** reimplement key storage, rotation, or quota enforcement — that
already exists in :mod:`hypernix.keymaster` (:class:`Keymaster`) and
:mod:`hypernix.gatekeeper` (:class:`Gatekeeper`), both of which already
speak the T1 key format and scope model described in the spec. T1AuthService
is a thin adapter that:

* turns Keymaster/Gatekeeper's exceptions into stable :class:`T1APIError`
  codes for the HTTP layer,
* adds a second, distinct credential type — short-lived **scoped tokens**
  (``POST /auth/token``) — for clients that shouldn't hold the raw T1 key
  on every request,
* implements the admin-only "convert a normal T1 token into an admin
  token" operation from the spec, expressed as promoting a target key to
  ``KeyType.ADMIN`` and re-issuing it via :meth:`Keymaster.rotate`-style
  recreate (never mutating scopes on a live key string in place — a scope
  change gets a new key, consistent with how Keymaster already treats
  rotation as "replace, don't mutate").

Scoped tokens are intentionally NOT a full JWT implementation — no new
required dependency for something this small. They're
``T1S.<payload_b64>.<sig_b64>``, HMAC-SHA256 signed with
``T1APIConfig.token_secret``. Losing/rotating the secret invalidates every
outstanding scoped token immediately, which is the desired revocation
story for a stateless token (see ``wiki/T1-API.md#authentication``).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass

from ..gatekeeper import Gatekeeper, QuotaViolation
from ..keymaster import Keymaster, KeyMeta, KeyScope, KeyType
from .errors import T1APIError, T1ErrorCode

logger = logging.getLogger(__name__)

_TOKEN_PREFIX = "T1S"


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


@dataclass
class AuthContext:
    """Everything a route handler needs after authenticating a request."""

    key_meta: KeyMeta
    scopes: set[KeyScope]
    via_scoped_token: bool = False

    @property
    def key_id(self) -> str:
        return self.key_meta.key_id

    @property
    def is_admin(self) -> bool:
        return self.key_meta.key_type == KeyType.ADMIN and KeyScope.ADMIN in self.scopes


@dataclass
class ScopedToken:
    token: str
    key_id: str
    scopes: list[str]
    expires_at: float


class T1AuthService:
    """Adapter over Keymaster + Gatekeeper for the T1 API HTTP layer."""

    def __init__(
        self,
        keymaster: Keymaster,
        gatekeeper: Gatekeeper,
        *,
        token_secret: str,
        default_ttl_seconds: int = 3600,
    ) -> None:
        self.keymaster = keymaster
        self.gatekeeper = gatekeeper
        self._token_secret = token_secret
        self.default_ttl_seconds = default_ttl_seconds
        if not token_secret:
            logger.warning(
                "t1api.auth: T1_TOKEN_SECRET is not set — scoped tokens (POST /auth/token) "
                "will be signed with an ephemeral in-process secret and become invalid on "
                "restart. Set T1_TOKEN_SECRET for any deployment with more than one worker "
                "process or that needs tokens to survive a restart."
            )
            import secrets as _secrets

            self._token_secret = _secrets.token_hex(32)

    # ------------------------------------------------------------------
    # Raw T1 key validation
    # ------------------------------------------------------------------

    def validate_key(self, key_str: str) -> AuthContext:
        """Validate a raw T1 key string. Used by POST /auth/t1/validate and
        as the fallback path when a request presents a raw key instead of
        a scoped token."""
        try:
            meta = self.gatekeeper.authenticate(key_str)
        except ValueError as exc:
            raise T1APIError(T1ErrorCode.AUTH_INVALID_KEY, str(exc), http_status=401) from exc
        except PermissionError as exc:
            msg = str(exc)
            # NOTE: Keymaster.revoke() removes the key from the active
            # lookup table entirely (archived, not just flagged inactive —
            # see keymaster.py::revoke), so Gatekeeper.authenticate() can
            # never actually produce a "has been revoked" message for a
            # key looked up by its raw string: a revoked key and a key
            # that never existed are indistinguishable at this layer, both
            # surfacing as "Unknown or unregistered T1 key." We map that
            # case to AUTH_INVALID_KEY rather than pretending we can tell
            # them apart. AUTH_REVOKED_KEY stays reachable in principle
            # (e.g. Keymaster.get(key_id)-based lookups by key_id, used
            # elsewhere) and is kept in T1ErrorCode for that reason.
            if "expired" in msg:
                code = T1ErrorCode.AUTH_EXPIRED_KEY
            else:
                code = T1ErrorCode.AUTH_INVALID_KEY
            raise T1APIError(code, msg, http_status=401) from exc
        return AuthContext(key_meta=meta, scopes=set(meta.scopes))

    # ------------------------------------------------------------------
    # Scoped tokens
    # ------------------------------------------------------------------

    def issue_scoped_token(
        self,
        key_str: str,
        *,
        ttl_seconds: int | None = None,
        scopes: list[str] | None = None,
    ) -> ScopedToken:
        """Exchange a validated raw T1 key for a short-lived scoped token.

        If *scopes* is given, it must be a subset of the underlying key's
        scopes (a token can only narrow permissions, never widen them).
        """
        ctx = self.validate_key(key_str)
        granted = {KeyScope(s) for s in scopes} if scopes else set(ctx.scopes)
        if not granted.issubset(ctx.scopes):
            raise T1APIError(
                T1ErrorCode.AUTH_INSUFFICIENT_SCOPE,
                "Requested scopes exceed the underlying T1 key's scopes.",
                details={"key_scopes": sorted(s.value for s in ctx.scopes)},
                http_status=403,
            )
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        exp = time.time() + max(1, ttl)
        payload = {
            "key_id": ctx.key_id,
            "scopes": sorted(s.value for s in granted),
            "exp": exp,
        }
        payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        sig = hmac.new(self._token_secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256)
        token = f"{_TOKEN_PREFIX}.{payload_b64}.{_b64url_encode(sig.digest())}"
        return ScopedToken(token=token, key_id=ctx.key_id, scopes=payload["scopes"], expires_at=exp)

    def verify_scoped_token(self, token: str) -> AuthContext:
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != _TOKEN_PREFIX:
            raise T1APIError(T1ErrorCode.AUTH_INVALID_TOKEN, "Malformed scoped token.", http_status=401)
        _, payload_b64, sig_b64 = parts
        expected_sig = hmac.new(
            self._token_secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256
        ).digest()
        try:
            given_sig = _b64url_decode(sig_b64)
        except Exception as exc:  # noqa: BLE001 - malformed input, not a real error path
            raise T1APIError(T1ErrorCode.AUTH_INVALID_TOKEN, "Malformed scoped token.", http_status=401) from exc
        if not hmac.compare_digest(expected_sig, given_sig):
            raise T1APIError(T1ErrorCode.AUTH_INVALID_TOKEN, "Scoped token signature mismatch.", http_status=401)
        try:
            payload = json.loads(_b64url_decode(payload_b64))
        except Exception as exc:  # noqa: BLE001
            raise T1APIError(T1ErrorCode.AUTH_INVALID_TOKEN, "Malformed scoped token payload.", http_status=401) from exc
        if payload.get("exp", 0) < time.time():
            raise T1APIError(T1ErrorCode.AUTH_EXPIRED_TOKEN, "Scoped token has expired.", http_status=401)

        key_meta = self.keymaster.get(payload["key_id"])
        if key_meta is None or not key_meta.is_valid:
            raise T1APIError(
                T1ErrorCode.AUTH_INVALID_TOKEN,
                "The T1 key backing this scoped token is no longer valid.",
                http_status=401,
            )
        scopes = {KeyScope(s) for s in payload.get("scopes", [])}
        return AuthContext(key_meta=key_meta, scopes=scopes, via_scoped_token=True)

    # ------------------------------------------------------------------
    # Quota check wrapper (used by routers before expensive operations)
    # ------------------------------------------------------------------

    def check_quota(self, key_id: str, *, endpoint: str = "", model: str = "", tokens_requested: int = 0) -> None:
        try:
            self.gatekeeper.check_quota(
                key_id, endpoint=endpoint, model=model, tokens_requested=tokens_requested
            )
        except QuotaViolation as exc:
            raise T1APIError(T1ErrorCode.RATE_LIMITED, str(exc), http_status=429) from exc

    # ------------------------------------------------------------------
    # Admin operations
    # ------------------------------------------------------------------

    def rotate_own_key(self, key_id: str) -> KeyMeta:
        try:
            return self.keymaster.rotate(key_id)
        except KeyError as exc:
            raise T1APIError(T1ErrorCode.NOT_FOUND, str(exc), http_status=404) from exc

    def admin_rotate(self, *, requester: AuthContext, target_key_id: str, promote_to_admin: bool = False) -> KeyMeta:
        """POST /auth/t1/admin/rotate — admin-only. Rotates *target_key_id*
        and, if requested, promotes the newly-issued key to an admin key.

        "support conversion of a normal T1 token into an admin token only
        when the authenticated user has the required permission" — the
        permission check here IS the admin-scope requirement on
        *requester*, enforced before anything else runs.
        """
        if not requester.is_admin:
            raise T1APIError(
                T1ErrorCode.AUTH_ADMIN_REQUIRED,
                "Only an admin-scoped T1 key may rotate another key or grant admin.",
                http_status=403,
            )
        target = self.keymaster.get(target_key_id)
        if target is None:
            raise T1APIError(T1ErrorCode.NOT_FOUND, f"Key {target_key_id} not found.", http_status=404)

        new_meta = self.keymaster.rotate(target_key_id)
        if promote_to_admin and new_meta.key_type != KeyType.ADMIN:
            # Recreate as an admin-typed key preserving the rest of the
            # settings, then revoke the just-rotated intermediate key —
            # mirrors Keymaster.rotate's own "replace, don't mutate" model.
            promoted = self.keymaster.create(
                key_type=KeyType.ADMIN,
                scopes=set(new_meta.scopes) | {KeyScope.ADMIN},
                expires_at=new_meta.expires_at,
                usage_cap=new_meta.usage_cap,
                request_limit=new_meta.request_limit,
                prefix=new_meta.prefix,
                tags={**new_meta.tags, "promoted_from": new_meta.key_id},
                rotation_window=new_meta.rotation_window,
                note=f"promoted to admin by {requester.key_id[:8]}",
            )
            self.keymaster.revoke(new_meta.key_id, reason="promoted to admin key")
            logger.info(
                "t1api.auth: key %s promoted to admin key %s by %s",
                target_key_id[:8],
                promoted.key_id[:8],
                requester.key_id[:8],
            )
            return promoted
        return new_meta


__all__ = ["AuthContext", "ScopedToken", "T1AuthService"]
