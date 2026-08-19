"""t1api.routers — one module per resource group, matching the spec's
'PRIMARY ENDPOINT SET'. Beta 1 wires: health, auth, models, usage, config.

Module/server/job/event/billing routers are Beta 2/3 scope — see
``wiki/T1-API.md#roadmap`` for exactly which endpoint from the spec's list
ships in which beta.
"""
from __future__ import annotations

from . import auth, config, health, models, usage

ALL_ROUTERS = (health.router, auth.router, models.router, usage.router, config.router)

__all__ = ["ALL_ROUTERS", "auth", "config", "health", "models", "usage"]
