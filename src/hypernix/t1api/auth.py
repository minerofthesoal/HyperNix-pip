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

from hypernix.security.gatekeeper import Gatekeeper, QuotaViolation
from hypernix.security.keymaster import Keymaster, KeyMeta, KeyScope, KeyType

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
        # 0.0, not "now": the throttle exists to stop repeated reloads, not
        # to delay the first one. Starting at the current time would make
        # the first unknown key — the exact case this refresh is for —
        # wait out the whole interval before it could be found.
        self._last_key_reload = 0.0

    # ------------------------------------------------------------------
    # Raw T1 key validation
    # ------------------------------------------------------------------

    # Keymaster loads its key files once, at construction. A key created
    # after the server started — which is exactly what the documented
    # quickstart tells you to do (`gkey create`, then point waiter at the
    # already-running server) — is therefore invisible until a restart.
    # validate_key() reloads once on an unknown key to close that gap.
    #
    # The reload is throttled because it is disk I/O reachable by an
    # unauthenticated caller: without a floor, a stream of garbage keys
    # would force a directory scan per request, which is a denial-of-
    # service handed out for free. One reload every few seconds bounds
    # that to noise while still picking up a newly-minted key promptly.
    _RELOAD_MIN_INTERVAL_SECONDS = 5.0

    def _maybe_reload_keys(self) -> bool:
        """Re-read the key store, at most once per interval.

        Returns True if a reload actually happened, so the caller knows
        whether a retry is worth attempting.
        """
        now = time.monotonic()
        if now - self._last_key_reload < self._RELOAD_MIN_INTERVAL_SECONDS:
            return False
        self._last_key_reload = now
        try:
            self.keymaster._load_all()
        except Exception:  # noqa: BLE001 - a failed refresh must not mask the auth error
            logger.warning("t1api.auth: could not refresh the key store", exc_info=True)
            return False
        return True

    def validate_key(self, key_str: str) -> AuthContext:
        """Validate a raw T1 key string. Used by POST /auth/t1/validate and
        as the fallback path when a request presents a raw key instead of
        a scoped token."""
        try:
            meta = self.gatekeeper.authenticate(key_str)
        except (ValueError, PermissionError):
            # Unknown key: it may simply have been created after this
            # process started. Refresh once and try again — if it is still
            # unknown, fall through to the normal error handling below so
            # the caller sees the real message.
            if self._maybe_reload_keys():
                try:
                    meta = self.gatekeeper.authenticate(key_str)
                except (ValueError, PermissionError):
                    return self._validate_uncached(key_str)
                return AuthContext(key_meta=meta, scopes=set(meta.scopes))
            return self._validate_uncached(key_str)
        return AuthContext(key_meta=meta, scopes=set(meta.scopes))

    def _validate_uncached(self, key_str: str) -> AuthContext:
        """The original validation path, raising the stable error codes."""
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
