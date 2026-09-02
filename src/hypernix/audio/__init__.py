"""hypernix.audio — audio subsystems.

Currently one: :mod:`hypernix.audio.wakeup`, the wake-word trainer and
streaming detector. Submodules are imported lazily so importing this
package costs nothing until you touch one.
"""
from __future__ import annotations

import importlib
from typing import Any

__all__ = ["wakeup"]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{name}", __name__)
    globals()[name] = module
    return module
