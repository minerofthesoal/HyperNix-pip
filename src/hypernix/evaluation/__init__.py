"""hypernix.evaluation — Scoring, rubric labelling, judging and module verification.

Modules: ``espresso_maker``, ``industrial_range``, ``new_fridge``,
``new_range``, ``old_range``, ``vera``.

Every module here is also reachable under its historical flat name
(``hypernix.espresso_maker``); see the alias finder in ``hypernix/__init__.py``.
Submodules are imported lazily, so importing this package costs nothing
until you touch one of them.
"""
from __future__ import annotations

import importlib
from typing import Any

__all__ = [
    "espresso_maker",
    "industrial_range",
    "new_fridge",
    "new_range",
    "old_range",
    "vera",
]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{name}", __name__)
    globals()[name] = module
    return module


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
