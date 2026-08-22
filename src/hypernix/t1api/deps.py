"""t1api.deps — FastAPI ``Depends()`` wiring.

Everything a route needs (auth service, registry, usage meter, config) is
attached to ``app.state`` in :func:`t1api.app.create_app` and pulled back
out here via ``Request.app.state``. This keeps the app embeddable — a
caller mounting the T1 router into an existing FastAPI app just needs to
set the same ``app.state`` attributes, no global singletons involved.
"""
from __future__ import annotations

import uuid

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
        return svc.verify_scoped_token(credential)
    return svc.validate_key(credential)


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
