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
]
