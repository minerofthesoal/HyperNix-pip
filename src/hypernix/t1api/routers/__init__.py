"""t1api.routers — one module per resource group, matching the spec's
'PRIMARY ENDPOINT SET'.

Beta 1 wired: health, auth, models, usage, config.
Beta 2 adds: servers, modules, jobs, events, billing — plus one addition
beyond the spec's literal endpoint list, POST /models/route (see
routers/models.py), to give the routing/quota-cascade engine an HTTP
surface.
"""
from __future__ import annotations

from . import auth, billing, config, events, health, jobs, models, modules, servers, usage

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
)

__all__ = [
    "ALL_ROUTERS",
    "auth",
    "billing",
    "config",
    "events",
    "health",
    "jobs",
    "models",
    "modules",
    "servers",
    "usage",
]
