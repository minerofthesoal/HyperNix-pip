"""hypernix.t1api — the HyperNix T1 API, a controlled gateway into HyperNix.

Complete through **Beta 3** (see ``wiki/T1-API.md`` for the full
contract):

* **Beta 1** — core FastAPI server, T1 authentication + scoped tokens,
  the model registry, per-key/per-model usage tracking, ``/health``,
  ``/status``, ``/models``, SQLite storage, OpenAPI docs.
* **Beta 2** — module registry and upload/sync, server registry, async
  jobs, event streaming, the quota-cascade routing engine, billing and
  payment tokens, encrypted secrets, Tailscale/local deployment.
* **Beta 3** — production hardening: PostgreSQL, a durable audit log,
  mTLS, advanced rate limiting, IP allow/blocklists, real remote
  multi-server module transport, the key directory (``/keys``), usage
  history/cost/estimate, and production configuration validation.

Two import surfaces, on purpose:

* ``.registry`` / ``.storage`` / ``.usage`` / ``.errors`` / ``.auth`` /
  ``.config`` / ``.routing`` / ``.audit`` / ``.ratelimit`` /
  ``.netpolicy`` / ``.mtls`` / ``.transport`` / ``.cost`` / ``.keys`` —
  pure Python + stdlib (+ the already-required ``cryptography`` extra via
  Keymaster, and psycopg only when PostgreSQL is actually configured).
  Importable and fully testable without FastAPI/Pydantic installed, same
  as the rest of hypernix.
* ``.app`` / ``.schemas`` / ``.deps`` / ``.routers`` / ``create_app`` —
  the HTTP layer. Requires the optional ``hypernix[t1api]`` extra
  (``fastapi``, ``uvicorn``, ``pydantic``, ``python-dotenv``). Importing
  ``create_app`` without that extra raises a clear ``ImportError`` rather
  than a confusing traceback deep inside FastAPI.

That split is what lets the enforcement logic — registry gating, quota
math, cascade routing, the network-policy decision, signature
verification — be tested directly, with no HTTP layer in the way.
"""
from __future__ import annotations

from typing import Any

__t1api_version__ = "0.71.5b3"

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
    # Beta 3
    "AuditLog",
    "AuditCategory",
    "AuditOutcome",
    "NetworkPolicy",
    "RateLimiter",
    "RateRule",
    "TLSSettings",
    "ClientCertVerifier",
    "ModuleTransport",
    "DeploymentCoordinator",
    "KeyDirectory",
    "CostCalculator",
    "PostgresBackend",
    "make_backend",
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
    if name in ("AuditLog", "AuditCategory", "AuditOutcome", "AuditRecord"):
        from . import audit as _audit

        return getattr(_audit, name)
    if name in ("NetworkPolicy", "PolicyEntry", "ForcedLimit", "EntryKind", "Decision"):
        from . import netpolicy as _netpolicy

        return getattr(_netpolicy, name)
    if name in ("RateLimiter", "RateRule", "Subject"):
        from . import ratelimit as _ratelimit

        return getattr(_ratelimit, name)
    if name in ("TLSSettings", "ClientCertVerifier", "ClientCertificate"):
        from . import mtls as _mtls

        return getattr(_mtls, name)
    if name in ("ModuleTransport", "TransferResult"):
        from . import transport as _transport

        return getattr(_transport, name)
    if name == "DeploymentCoordinator":
        from .deploy import DeploymentCoordinator as _coordinator

        return _coordinator
    if name in ("KeyDirectory", "KeyAssignment", "KeySummary"):
        from . import keys as _keys

        return getattr(_keys, name)
    if name in ("CostCalculator", "CostReport", "CostLine", "Forecast"):
        from . import cost as _cost

        return getattr(_cost, name)
    if name in ("PostgresBackend", "SQLBackend", "make_backend"):
        from . import db as _db

        return getattr(_db, name)

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
