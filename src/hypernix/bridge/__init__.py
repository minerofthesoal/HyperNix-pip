"""hypernix.bridge — outward connections to model servers HyperNix does not run.

A *bridge* is the opposite of a backend. A backend (``hypernix.models``,
``neo_oven``, llama.cpp via ``multilama``) is inference HyperNix owns and
can start, stop, and account for. A bridge is inference somebody else's
process already has loaded, which HyperNix borrows: it does not manage
the model's lifetime, it cannot make it appear, and it must degrade
clearly when the far side is simply not running.

Added in **T1 v1.0.26.8.0.1**:

* :mod:`hypernix.bridge.lmstudio` — LM Studio's OpenAI-compatible server,
  on localhost or across the LAN/Tailscale.

Everything here is standard library only. A bridge is a client, and the
machines that most want one (a laptop talking to the desktop with the
GPU) are exactly the machines that will not have the ``hypernix[t1api]``
server extra installed.
"""
from __future__ import annotations

from .lmstudio import (
    LMStudioBridge,
    LMStudioError,
    LMStudioModel,
    LMStudioProbe,
    default_endpoints,
    discover,
)

__all__ = [
    "LMStudioBridge",
    "LMStudioError",
    "LMStudioModel",
    "LMStudioProbe",
    "default_endpoints",
    "discover",
]
