"""t1api.deps — FastAPI ``Depends()`` wiring.

Everything a route needs (auth service, registry, usage meter, config) is
attached to ``app.state`` in :func:`t1api.app.create_app` and pulled back
out here via ``Request.app.state``. This keeps the app embeddable — a
caller mounting the T1 router into an existing FastAPI app just needs to
set the same ``app.state`` attributes, no global singletons involved.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Header, Request

from .auth import AuthContext, T1AuthService
from .config import T1APIConfig
from .errors import T1APIError, T1ErrorCode
from .registry import ModelRegistry
from .usage import UsageMeter


def new_request_id() -> str:
    return uuid.uuid4().hex


def get_request_id(request: Request) -> str:
    """Every response includes a unique request ID — set once per request
    by the request-ID middleware and reused here so logs and the response
    body agree."""
    rid = getattr(request.state, "request_id", None)
    if rid is None:
        rid = new_request_id()
        request.state.request_id = rid
    return rid


def get_auth_service(request: Request) -> T1AuthService:
    return request.app.state.t1_auth_service


def get_registry(request: Request) -> ModelRegistry:
    return request.app.state.t1_registry


def get_usage_meter(request: Request) -> UsageMeter:
    return request.app.state.t1_usage_meter


def get_config(request: Request) -> T1APIConfig:
    return request.app.state.t1_config


def get_routing_engine(request: Request):
    return request.app.state.t1_routing_engine


def get_server_registry(request: Request):
    return request.app.state.t1_server_registry


def get_module_registry(request: Request):
    return request.app.state.t1_module_registry


def get_job_queue(request: Request):
    return request.app.state.t1_job_queue


def get_event_bus(request: Request):
    return request.app.state.t1_event_bus


def get_billing_ledger(request: Request):
    return request.app.state.t1_billing_ledger


# --- Beta 3 subsystems -------------------------------------------------


def get_audit_log(request: Request):
    return request.app.state.t1_audit_log


def get_network_policy(request: Request):
    return request.app.state.t1_network_policy


def get_rate_limiter(request: Request):
    return request.app.state.t1_rate_limiter


def get_key_directory(request: Request):
    return request.app.state.t1_key_directory


def get_cost_calculator(request: Request):
    return request.app.state.t1_cost_calculator


def get_deployment_coordinator(request: Request):
    return request.app.state.t1_deployment


def get_cert_verifier(request: Request):
    return request.app.state.t1_cert_verifier


def get_client_ip(request: Request) -> str:
    """The caller's address, honouring X-Forwarded-For only from a
    trusted proxy.

    Set once by the network-policy middleware and cached on
    ``request.state`` — every later consumer (audit, rate limiting,
    handlers) must see the *same* address the access decision was made
    on. Recomputing it per call site would be a way for the two to drift
    apart, which is how an audit record ends up naming a different
    client than the one that was actually allowed in.
    """
    cached = getattr(request.state, "client_ip", None)
    if cached is not None:
        return cached
    return resolve_client_ip(request)


def resolve_client_ip(request: Request) -> str:
    """Compute the caller's address from the transport and, when the
    immediate peer is a trusted proxy, ``X-Forwarded-For``.

    ``X-Forwarded-For`` is client-settable, so it is read **only** when
    the direct peer is in ``T1_TRUSTED_PROXIES``. Without that check a
    client could put any address in the header and defeat both the IP
    blocklist and per-IP rate limiting in one line.
    """
    peer = request.client.host if request.client else ""
    config: T1APIConfig = request.app.state.t1_config
    trusted = getattr(config, "trusted_proxies", ())
    if not trusted or not peer:
        return peer
    verifier = getattr(request.app.state, "t1_cert_verifier", None)
    if verifier is None or not verifier.is_trusted_proxy(peer):
        return peer
    forwarded = request.headers.get("x-forwarded-for", "")
    if not forwarded:
        return peer
    # Left-most entry is the original client; the rest are proxy hops.
    return forwarded.split(",")[0].strip() or peer


def require_confirmation(request: Request, *, action: str) -> None:
    """Enforce "Require explicit confirmation for destructive operations".

    A destructive endpoint calls this; it passes only when the request
    carries ``?confirm=true``. Deliberately a query parameter rather than
    a body field so it survives ``DELETE`` (which has no body by
    convention) and shows up in the request line an operator reads back
    afterwards.
    """
    config: T1APIConfig = request.app.state.t1_config
    if not config.require_destructive_confirmation:
        return
    value = request.query_params.get("confirm", "").strip().lower()
    if value in ("1", "true", "yes"):
        return
    raise T1APIError(
        T1ErrorCode.CONFIRMATION_REQUIRED,
        f"{action} is destructive and requires explicit confirmation. Re-send with ?confirm=true.",
        details={"action": action},
        http_status=409,
    )


def _extract_credential(authorization: str | None) -> str:
    if not authorization:
        raise T1APIError(
            T1ErrorCode.AUTH_MISSING_CREDENTIALS,
            "Missing Authorization header. Use 'Authorization: Bearer <T1 key or scoped token>'.",
            http_status=401,
        )
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return authorization.strip()


def get_auth_context(
    request: Request,
    authorization: str | None = Header(default=None),
) -> AuthContext:
    """Resolve the caller's :class:`AuthContext` from either a raw T1 key
    or a scoped token — both are accepted on every authenticated route so
    a client can use whichever credential it currently holds."""
    svc: T1AuthService = get_auth_service(request)
    credential = _extract_credential(authorization)
    if credential.startswith("T1S."):
        ctx = svc.verify_scoped_token(credential)
    else:
        ctx = svc.validate_key(credential)
    _enforce_local_only(request, ctx)
    return ctx


def _enforce_local_only(request: Request, ctx: AuthContext) -> None:
    """A bootstrap key works only from the machine that minted it.

    Checked here, on every request, rather than at mint time: minting
    decides what a key *is*, and only the request knows where it came
    from. The address is the one the network policy already resolved, so
    this cannot disagree with the access decision that let the request in.

    The restriction is what makes printing an admin key on a terminal
    reasonable. Without it the key is an unauthenticated-until-copied
    admin credential with a three-day life, which is worse than making
    the operator run `gkey`.
    """
    from .bootstrap import is_bootstrap_key, is_loopback

    if not is_bootstrap_key(ctx.key_meta):
        return
    address = get_client_ip(request)
    if is_loopback(address):
        return
    raise T1APIError(
        T1ErrorCode.AUTH_INVALID_KEY,
        "This is a bootstrap key. It works only from the machine that "
        "created it, and this request did not come from there.",
        details={
            "reason": "bootstrap_key_is_local_only",
            "client_ip": address,
            "remedy": (
                "Run waiter on the server itself, or mint an ordinary key: "
                "gkey create --type admin --scopes admin,read,write"
            ),
        },
        http_status=403,
    )


def require_admin(ctx: AuthContext) -> AuthContext:
    if not ctx.is_admin:
        raise T1APIError(
            T1ErrorCode.AUTH_ADMIN_REQUIRED,
            "This operation requires an admin-scoped T1 key.",
            http_status=403,
        )
    return ctx


__all__ = [
    "new_request_id",
    "get_request_id",
    "get_auth_service",
    "get_registry",
    "get_usage_meter",
    "get_config",
    "get_auth_context",
    "require_admin",
    "get_routing_engine",
    "get_server_registry",
    "get_module_registry",
    "get_job_queue",
    "get_event_bus",
    "get_billing_ledger",
    "get_audit_log",
    "get_network_policy",
    "get_rate_limiter",
    "get_key_directory",
    "get_cost_calculator",
    "get_deployment_coordinator",
    "get_cert_verifier",
    "get_client_ip",
    "resolve_client_ip",
    "require_confirmation",
]


# --- T1 v1.0.26.8.0.1: HyperLink principals -----------------------------


def get_device_registry(request: Request):
    return request.app.state.t1_device_registry


def get_session_store(request: Request):
    return request.app.state.t1_session_store


def get_attachment_store(request: Request):
    return request.app.state.t1_attachment_store


@dataclass
class HyperLinkPrincipal:
    """Who is making a HyperLink request: a paired device, or a T1 key.

    Both are first-class. The phone holds a device token; ``waiter`` and
    ``hyped-pro`` hold a T1 key; both need to read the same chat
    sessions, because the whole point of server-side history is that the
    desktop and the phone see one conversation.

    ``owner`` is what makes that work, and it is deliberately *not* the
    device id. A device's owner is the key that paired it, so every
    device an operator enrols shares that operator's sessions and
    attachments, and unpairing a phone does not orphan the threads that
    were started on it.
    """

    owner: str
    scopes: tuple[str, ...]
    is_admin: bool = False
    device_id: str = ""
    device_name: str = ""
    auth_context: AuthContext | None = None

    @property
    def is_device(self) -> bool:
        return bool(self.device_id)

    @property
    def label(self) -> str:
        """What the audit log records. A device is named, not just hashed."""
        if self.is_device:
            return f"{self.device_name or 'device'} ({self.device_id[:8]}…)"
        return self.owner


def get_hyperlink_principal(
    request: Request,
    authorization: str | None = Header(default=None),
) -> HyperLinkPrincipal:
    """Accept a device token, a **T2S key**, or any normal T1 credential.

    Every branch is chosen by the credential's own shape rather than by a
    second header, so one ``Authorization: Bearer …`` works for every
    client and a client never has to know which kind of credential it is
    holding.

    The T2S branch (added in 0.72.1) is the fix for HyperLink refusing to
    connect. Pairing produces an ``HLNK_`` token, and a device that never
    completed pairing — or whose pairing code expired mid-setup — had no
    way in at all: the T1 keys it could have used are 48 characters of
    mixed symbols, which is not a thing anyone types into a phone twice.
    A T2S key is 26 body characters, deliberately limited to read and
    non-admin write outside HyperLink, and is now accepted here as a
    first-class way to reach a server.
    """
    credential = _extract_credential(authorization)

    if credential[:3] in ("T2_", "T2S"):
        return _principal_from_t2(request, credential)

    if credential.startswith("HLNK_"):
        registry = get_device_registry(request)
        record = registry.authenticate(credential, address=get_client_ip(request))
        return HyperLinkPrincipal(
            owner=record.paired_by,
            scopes=tuple(record.scopes),
            is_admin=False,          # a phone is never an admin, whatever paired it
            device_id=record.device_id,
            device_name=record.name,
        )
    ctx = get_auth_context(request, authorization)
    return HyperLinkPrincipal(
        owner=ctx.key_id,
        scopes=tuple(scope.value for scope in ctx.scopes),
        is_admin=ctx.is_admin,
        auth_context=ctx,
    )


def _principal_from_t2(request: Request, credential: str) -> HyperLinkPrincipal:
    """Resolve a T2 (or T2S) key into a HyperLink principal.

    The key authenticates through the ordinary T1 path — a T2 key is a
    T1 key with extra fields, and :meth:`T1AuthService.validate_key`
    already knows how to do the conversion — so a T2S key gets exactly
    the permissions its underlying T1 key has, narrowed by the T2S rule.

    Inside HyperLink a T2S key is a full client credential: this *is*
    HyperLink, which is the context the restriction carves out. It still
    never becomes an admin, because ``is_admin`` is carried by the
    password component and a T2S key cannot have one.
    """
    from ..security.t2keys import T2KeyGenerator, T2Type

    try:
        parsed = T2KeyGenerator.parse(credential)
    except ValueError as exc:
        raise T1APIError(T1ErrorCode.AUTH_INVALID_KEY, str(exc), http_status=401) from exc

    svc: T1AuthService = get_auth_service(request)
    ctx = svc.validate_key(credential)
    # HyperLink resolves T2 keys here rather than through
    # get_auth_context, so the loopback binding has to be applied on this
    # path too. A restriction enforced on one of two routes into the same
    # key store is not a restriction.
    _enforce_local_only(request, ctx)

    scopes = tuple(scope.value for scope in ctx.scopes)
    if parsed.family is T2Type.T2S:
        scopes = tuple(s for s in scopes if s in ("read", "write"))

    return HyperLinkPrincipal(
        owner=ctx.key_id,
        scopes=scopes,
        # A T2S key is never an admin — see t2keys.T2KeyGenerator.generate.
        is_admin=ctx.is_admin and parsed.family is not T2Type.T2S,
        auth_context=ctx,
    )


def require_hyperlink_admin(principal: HyperLinkPrincipal) -> HyperLinkPrincipal:
    """Pairing and device management are operator actions, not device ones.

    A stolen phone must not be able to enrol another phone, so this
    refuses device tokens outright rather than checking their scopes.
    """
    if principal.is_device:
        raise T1APIError(
            T1ErrorCode.AUTH_INSUFFICIENT_SCOPE,
            "Device tokens cannot manage pairing. Run this from the PC with `waiter`.",
            http_status=403,
        )
    if not principal.is_admin:
        # A T2S key is never an administrator, and never can be: admin is
        # carried by the password component in a T2 prefix, and the T2S
        # format has no room for one — it is short enough to type, which
        # is exactly why it must not carry administrative authority.
        #
        # Saying only "requires an admin key" sends that holder off to
        # widen their key's scopes, which cannot work however many times
        # they try. The property is in the format, not the grant.
        family = ""
        ctx = principal.auth_context
        if ctx is not None:
            family = ctx.t2_family
        if family == "T2S":
            raise T1APIError(
                T1ErrorCode.AUTH_ADMIN_REQUIRED,
                "A T2S key can never perform this operation. Pairing is admin-only, "
                "and a T2S key is never an administrator by design.",
                details={
                    "key_family": "T2S",
                    "reason": "t2s_is_never_admin",
                    "explanation": (
                        "Administrative authority rides on the password component of "
                        "a T2 prefix. A T2S key has no password component — it is "
                        "short enough to type by hand, which is why it must not carry "
                        "admin. Widening the underlying key's scopes will not change "
                        "this."
                    ),
                    "remedy": (
                        "Mint the pairing code on the PC with an admin key "
                        "(`waiter hyperlink pair`), then redeem the six-character "
                        "code on the phone. Use the T2S key for everything after "
                        "pairing."
                    ),
                },
                http_status=403,
            )
        raise T1APIError(
            T1ErrorCode.AUTH_ADMIN_REQUIRED,
            "This HyperLink operation requires an admin key.",
            details={
                "remedy": "gkey create --type admin --scopes admin,read,write",
            },
            http_status=403,
        )
    return principal
