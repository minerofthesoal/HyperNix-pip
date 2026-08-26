"""hypernix.waiter — the "waiter" TUI/CLI, the official T1 API client.

Console script: ``waiter`` (see ``pyproject.toml``). Talks to a T1 API
server (``hypernix.t1api``) over plain HTTP using only the standard
library (``urllib``) — the waiter client has no hard dependency on
FastAPI/Pydantic, since it's a *client*, not a server; it can run on a
machine that never installs the ``hypernix[t1api]`` extra.

The TUI obtains model information from the API's ``GET /models`` at
runtime rather than maintaining its own hard-coded model list, per the
spec's "WAITER TUI" requirement.

As of Beta 3 the client is a thin layer over :mod:`hypernix.t1sdk` (see
``waiter/client.py``) and the full curses dashboard lives in
``waiter/tui.py``. The version now tracks the T1 API's own, since the two
ship together and a client that says 0.1.0 against a 1.0.26.8.0.1 server
is a support question nobody needs.

As of **T1 v1.0.26.8.0.1** that shared version is the T1 API's own
six-part scheme (see :mod:`hypernix.t1api.version`) rather than the
hypernix package's, and waiter grew three subcommands for the release's
new surfaces: ``waiter lmstudio`` (the LM Studio bridge),
``waiter hyperlink`` (pairing, devices, sessions), and ``waiter fetch``
(Hugging Face link resolution).
"""
from __future__ import annotations

__waiter_version__ = "1.0.26.8.1.0"

__all__ = ["__waiter_version__"]
