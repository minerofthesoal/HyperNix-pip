"""t1api.routers — one module per resource group, matching the spec's
'PRIMARY ENDPOINT SET'.

Beta 1 wired: health, auth, models, usage, config.
Beta 2 added: servers, modules, jobs, events, billing.
Beta 3 adds: keys (the spec's 28–30, previously unimplemented), audit,
and security (network policy + forced limits).

Three routers expose endpoints beyond the spec's literal list, each for
a stated reason rather than by accident:

* ``POST /models/route`` — the spec describes the routing engine in
  detail but names no endpoint for it (routers/models.py).
* ``GET /events/stream`` — "event streaming" reads as a live tail, and
  ``GET /events`` alone can only poll (routers/events.py).
* ``GET /audit`` and ``/security/*`` — "complete audit logging" and the
  IP allowlist/blocklist requirements need a read and a write surface
  respectively (routers/audit.py, routers/security.py).
"""
from __future__ import annotations

from . import (
    audit,
    auth,
    billing,
    config,
    events,
    health,
    jobs,
    keys,
    models,
    modules,
    security,
    servers,
    usage,
)

ALL_ROUTERS = (
    health.router,
    auth.router,
    models.router,
    usage.router,
    config.router,
    servers.router,
    modules.router,
    jobs.router,
    events.router,
    billing.router,
    keys.router,
    audit.router,
    security.router,
)

__all__ = [
    "ALL_ROUTERS",
    "audit",
    "auth",
    "billing",
    "config",
    "events",
    "health",
    "jobs",
    "keys",
    "models",
    "modules",
    "security",
    "servers",
    "usage",
]
