"""hypernix.waiter — the "waiter" TUI/CLI, the official T1 API client.

Console script: ``waiter`` (see ``pyproject.toml``). Talks to a T1 API
server (``hypernix.t1api``) over plain HTTP using only the standard
library (``urllib``) — the waiter client has no hard dependency on
FastAPI/Pydantic, since it's a *client*, not a server; it can run on a
machine that never installs the ``hypernix[t1api]`` extra.

The TUI obtains model information from the API's ``GET /models`` at
runtime rather than maintaining its own hard-coded model list, per the
spec's "WAITER TUI" requirement.
"""
from __future__ import annotations

__waiter_version__ = "0.1.0b1"

__all__ = ["__waiter_version__"]
