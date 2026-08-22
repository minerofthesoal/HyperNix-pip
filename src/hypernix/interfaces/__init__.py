"""hypernix.interfaces — Human-facing front ends: CLIs, TUIs, GUIs and launchers.

Modules: ``assistant``, ``cli``, ``hyped``, ``hyped_pro``,
``hyped_pro_bridge``, ``hyped_pro_core``, ``hyped_pro_gui``,
``hyped_pro_tools``, ``version_launcher``, ``websearch``, ``wiki_cli``.

Every module here is also reachable under its historical flat name
(``hypernix.assistant``); see the alias finder in ``hypernix/__init__.py``.
Submodules are imported lazily, so importing this package costs nothing
until you touch one of them.
"""
from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "assistant",
    "cli",
    "hyped",
    "hyped_pro",
    "hyped_pro_bridge",
    "hyped_pro_core",
    "hyped_pro_gui",
    "hyped_pro_tools",
    "version_launcher",
    "websearch",
    "wiki_cli",
]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{name}", __name__)
    globals()[name] = module
    return module


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
