"""hypernix.t1api — the HyperNix T1 API, a controlled gateway into HyperNix.

Beta 1 scope (see ``wiki/T1-API.md`` for the full roadmap): core FastAPI
server, T1 authentication + scoped tokens, the model registry, basic
per-key/per-model usage tracking, ``/health``, ``/status``, ``/models``
and friends, SQLite storage, OpenAPI docs. Module/server/job/event/billing
management and the quota-cascade routing engine land in Beta 2 and 3.

Two import surfaces, on purpose:

* ``hypernix.t1api.registry`` / ``.storage`` / ``.usage`` / ``.errors`` /
  ``.auth`` / ``.config`` — pure Python + stdlib (+ the already-required
  ``cryptography`` extra via Keymaster). Importable and fully testable
  without FastAPI/Pydantic installed, same as the rest of hypernix.
* ``hypernix.t1api.app`` / ``.schemas`` / ``.deps`` / ``.routers`` /
  ``create_app`` — the HTTP layer. Requires the optional
  ``hypernix[t1api]`` extra (``fastapi``, ``uvicorn``, ``pydantic``,
  ``python-dotenv``). Importing ``hypernix.t1api.create_app`` without that
  extra installed raises a clear ``ImportError`` rather than a confusing
  traceback deep in FastAPI.
"""
from __future__ import annotations

from typing import Any

__t1api_version__ = "0.71.5b2"

__all__ = [
    "__t1api_version__",
    "create_app",
    "ModelRegistry",
    "ModelEntry",
    "ModelStatus",
    "T1APIError",
    "T1ErrorCode",
    "T1APIConfig",
    "UsageStore",
    "UsageMeter",
    "T1AuthService",
    "SQLiteBackend",
    "RoutingTable",
    "RoutingEngine",
    "RoutingPolicy",
    "ServerRegistry",
    "TrustLevel",
    "ServerStatus",
    "ModuleRegistry",
    "ModuleStatus",
    "JobQueue",
    "JobStatus",
    "EventBus",
    "BillingLedger",
]


def __getattr__(name: str) -> Any:
    # Pure-core names: always available.
    if name in ("ModelRegistry", "ModelEntry", "ModelStatus"):
        from . import registry as _registry

        return getattr(_registry, name)
    if name in ("T1APIError", "T1ErrorCode"):
        from . import errors as _errors

        return getattr(_errors, name)
    if name == "T1APIConfig":
        from .config import T1APIConfig as _cfg

        return _cfg
    if name == "UsageStore":
        from .storage import UsageStore as _store

        return _store
    if name == "UsageMeter":
        from .usage import UsageMeter as _meter

        return _meter
    if name == "T1AuthService":
        from .auth import T1AuthService as _svc

        return _svc
    if name == "SQLiteBackend":
        from .db import SQLiteBackend as _backend

        return _backend
    if name in ("RoutingTable", "RoutingEngine", "RoutingPolicy", "CascadeStep", "RoutingDecision"):
        from . import routing as _routing

        return getattr(_routing, name)
    if name in ("ServerRegistry", "TrustLevel", "ServerStatus", "ServerEntry"):
        from . import servers as _servers

        return getattr(_servers, name)
    if name in ("ModuleRegistry", "ModuleStatus", "ModuleEntry", "SourceType"):
        from . import modules as _modules

        return getattr(_modules, name)
    if name in ("JobQueue", "JobStatus", "JobEntry"):
        from . import jobs as _jobs

        return getattr(_jobs, name)
    if name in ("EventBus", "Event", "Subscriber"):
        from . import events as _events

        return getattr(_events, name)
    if name in ("BillingLedger", "TransactionKind", "Transaction", "PaymentTokenRecord"):
        from . import billing as _billing

        return getattr(_billing, name)

    # HTTP-layer names: require the optional [t1api] extra.
    if name == "create_app":
        try:
            from .app import create_app as _create_app
        except ImportError as exc:  # pragma: no cover - exercised only w/o extra installed
            raise ImportError(
                "hypernix.t1api.create_app requires the 'hypernix[t1api]' extra "
                "(fastapi, uvicorn, pydantic, python-dotenv). Install with:\n"
                "    pip install 'hypernix[t1api]'"
            ) from exc
        return _create_app

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
