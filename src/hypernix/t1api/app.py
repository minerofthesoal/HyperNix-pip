"""t1api.app — ``create_app()``, the T1 API's FastAPI factory.

Designed to be "easy to mount into an existing Python server" (spec, HARD
REQUIREMENTS):

    from hypernix.t1api import create_app
    app = create_app()                     # standalone
    uvicorn.run(app, host="0.0.0.0", port=8000)

    # OR mount into an existing FastAPI app:
    from hypernix.t1api import create_app
    existing_app.mount("/t1", create_app(mount_prefix="/t1"))

    # OR include just the routers into an existing app's own router tree:
    from hypernix.t1api import create_app
    t1 = create_app()
    for route in t1.routes:
        existing_app.router.routes.append(route)

Everything the routers need (auth service, registry, usage meter, config)
lives on ``app.state`` — see ``t1api/deps.py``.
"""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..gatekeeper import Gatekeeper
from ..keymaster import Keymaster
from . import __t1api_version__
from .auth import T1AuthService
from .billing import BillingLedger
from .config import T1APIConfig
from .db import SQLiteBackend
from .errors import T1APIError, T1ErrorCode
from .events import EventBus
from .jobs import JobQueue
from .modules import ModuleRegistry
from .registry import ModelRegistry
from .routers import ALL_ROUTERS
from .routing import RoutingEngine, RoutingTable
from .servers import ServerRegistry
from .storage import UsageStore
from .usage import UsageMeter

logger = logging.getLogger(__name__)

# Default HTTP status for each error code when the raiser didn't specify one.
_STATUS_FOR_CODE: dict[T1ErrorCode, int] = {
    T1ErrorCode.MODEL_NOT_SUPPORTED: 404,
    T1ErrorCode.MODEL_QUOTA_EXHAUSTED: 429,
    T1ErrorCode.MODEL_UNAVAILABLE: 503,
    T1ErrorCode.AUTH_MISSING_CREDENTIALS: 401,
    T1ErrorCode.AUTH_INVALID_KEY: 401,
    T1ErrorCode.AUTH_EXPIRED_KEY: 401,
    T1ErrorCode.AUTH_REVOKED_KEY: 401,
    T1ErrorCode.AUTH_INVALID_TOKEN: 401,
    T1ErrorCode.AUTH_EXPIRED_TOKEN: 401,
    T1ErrorCode.AUTH_INSUFFICIENT_SCOPE: 403,
    T1ErrorCode.AUTH_ADMIN_REQUIRED: 403,
    T1ErrorCode.RATE_LIMITED: 429,
    T1ErrorCode.QUOTA_EXCEEDED: 429,
    T1ErrorCode.NOT_SUPPORTED: 501,
    T1ErrorCode.NOT_FOUND: 404,
    T1ErrorCode.VALIDATION_ERROR: 422,
    T1ErrorCode.CONFLICT: 409,
    T1ErrorCode.INTERNAL_ERROR: 500,
    T1ErrorCode.MODULE_NOT_FOUND: 404,
    T1ErrorCode.MODULE_ALREADY_EXISTS: 409,
    T1ErrorCode.MODULE_UPLOAD_REJECTED: 400,
    T1ErrorCode.SERVER_NOT_FOUND: 404,
    T1ErrorCode.SERVER_UNTRUSTED: 403,
    T1ErrorCode.JOB_NOT_FOUND: 404,
    T1ErrorCode.JOB_NOT_CANCELLABLE: 409,
    T1ErrorCode.PATH_TRAVERSAL_REJECTED: 400,
    T1ErrorCode.SSRF_BLOCKED: 400,
    T1ErrorCode.PAYMENT_TOKEN_INVALID: 400,
    T1ErrorCode.PAYMENT_TOKEN_ALREADY_REDEEMED: 409,
    T1ErrorCode.INSUFFICIENT_BALANCE: 402,
    T1ErrorCode.ROUTING_EXHAUSTED: 429,
}


def _make_module_sync_handler(module_registry: ModuleRegistry, server_registry: ServerRegistry):
    """Composes ModuleRegistry + ServerRegistry into the ``module_sync``
    job handler. Lives here (not in t1api.modules or t1api.jobs) because
    it's the one place that's allowed to depend on both — keeping that
    coupling out of the core modules themselves. See the worked example
    in wiki/T1-API.md#modules for exactly what this does and doesn't do
    (trust-gates and records the sync; no real byte transport)."""

    def handler(payload: dict, cancel_event) -> dict:
        module_id = payload["module_id"]
        server_id = payload["server_id"]
        server_registry.require_trusted(server_id)
        entry = module_registry.mark_synced(module_id, server_id)
        return {
            "module_id": module_id,
            "server_id": server_id,
            "deployed_servers": entry.deployed_servers,
        }

    return handler


def create_app(
    *,
    config: T1APIConfig | None = None,
    keymaster: Keymaster | None = None,
    gatekeeper: Gatekeeper | None = None,
    registry: ModelRegistry | None = None,
    usage_store: UsageStore | None = None,
    routing_table: RoutingTable | None = None,
    server_registry: ServerRegistry | None = None,
    module_registry: ModuleRegistry | None = None,
    job_queue: JobQueue | None = None,
    event_bus: EventBus | None = None,
    billing_ledger: BillingLedger | None = None,
    mount_prefix: str | None = None,
) -> FastAPI:
    """Build a fully-wired T1 API FastAPI app.

    Every dependency is injectable so tests (and Rayla's own server) can
    swap in an in-memory Keymaster/Gatekeeper or a pre-populated registry
    without monkeypatching. Omit everything and you get a sane
    local/dev-ready default: SQLite storage under ``~/.hypernix/t1api/``
    and the example model registry (invisible by default — see
    ``T1_ENABLE_EXAMPLE_MODELS``).
    """
    cfg = config or T1APIConfig.from_env()
    prefix = mount_prefix if mount_prefix is not None else cfg.mount_prefix

    km = keymaster or Keymaster()
    gk = gatekeeper or Gatekeeper(keymaster=km)
    reg = registry or ModelRegistry.load(
        cfg.registry_path, include_examples=cfg.enable_example_models
    )
    store = usage_store or UsageStore(cfg.db_path)
    meter = UsageMeter(store, reg, reset_period_seconds=cfg.usage_reset_period_seconds)
    auth_service = T1AuthService(
        km, gk, token_secret=cfg.token_secret, default_ttl_seconds=cfg.scoped_token_default_ttl_seconds
    )

    # Beta 2 subsystems. All share one SQLite file by default (same file
    # UsageStore already writes to) — different tables, one db_path, one
    # "SQLite for development" story. Pass explicit instances to split
    # them across files/backends if you'd rather.
    backend = SQLiteBackend(cfg.db_path)
    table = routing_table or RoutingTable.load(cfg.routing_policy_path)
    routing_engine = RoutingEngine(table, reg, meter)
    servers = server_registry or ServerRegistry(backend)
    modules = module_registry or ModuleRegistry(backend)
    bus = event_bus or EventBus()
    jobs = job_queue or JobQueue(backend, event_bus=bus)
    jobs.register_handler("module_sync", _make_module_sync_handler(modules, servers))
    billing = billing_ledger or BillingLedger(backend)

    app = FastAPI(
        title="HyperNix T1 API",
        version=__t1api_version__,
        description=(
            "Controlled gateway into HyperNix-pip. The client requests an "
            "operation; the server decides what exists, what's available, "
            "and how much is left. See wiki/T1-API.md for the full contract."
        ),
        docs_url=f"{prefix}/docs",
        redoc_url=f"{prefix}/redoc",
        openapi_url=f"{prefix}/openapi.json",
    )

    # Dependency wiring lives on app.state so t1api/deps.py never touches a
    # module-level global — this is what makes create_app() safe to call
    # more than once (e.g. once per test) without cross-talk.
    app.state.t1_config = cfg
    app.state.t1_keymaster = km
    app.state.t1_gatekeeper = gk
    app.state.t1_registry = reg
    app.state.t1_usage_store = store
    app.state.t1_usage_meter = meter
    app.state.t1_auth_service = auth_service
    app.state.t1_routing_engine = routing_engine
    app.state.t1_server_registry = servers
    app.state.t1_module_registry = modules
    app.state.t1_job_queue = jobs
    app.state.t1_event_bus = bus
    app.state.t1_billing_ledger = billing

    @app.middleware("http")
    async def _request_id_and_timing(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        start = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Response-Time-Ms"] = f"{(time.monotonic() - start) * 1000:.1f}"
        return response

    @app.exception_handler(T1APIError)
    async def _t1_error_handler(request: Request, exc: T1APIError) -> JSONResponse:
        status_code = exc.http_status or _STATUS_FOR_CODE.get(exc.code, 500)
        request_id = getattr(request.state, "request_id", uuid.uuid4().hex)
        # Audit-log security-relevant failures. Never log the credential
        # itself — only the (already-safe) error code/message/request id.
        logger.info(
            "t1api.error code=%s status=%s path=%s request_id=%s",
            exc.code.value,
            status_code,
            request.url.path,
            request_id,
        )
        return JSONResponse(
            status_code=status_code,
            content={
                "error": {"code": exc.code.value, "message": exc.message, "details": exc.details},
                "request_id": request_id,
            },
        )

    for router in ALL_ROUTERS:
        app.include_router(router, prefix=prefix)

    return app


__all__ = ["create_app"]
