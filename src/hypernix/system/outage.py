"""outage — turn the display off during training.

Long training runs don't need the panel lit up.  An ``outage``
blanks the display when the run starts, then *guarantees* the
display comes back on when training:

* finishes successfully,
* raises (KeyboardInterrupt / RuntimeError / OOM / anything),
* explicitly calls :meth:`Outage.restore`.

The restore-on-anything semantic comes from the context-manager
``__exit__`` so a crash mid-training still leaves you with a
working screen.

Quick use::

    from hypernix.outage import Outage

    with Outage():
        train_for_six_hours()       # screen off; comes back when done

Manual control::

    o = Outage().black_out()
    try:
        train_for_six_hours()
    finally:
        o.restore()

Backends, in order of preference:

* Linux X11: ``xset dpms force off`` / ``... force on``
* Linux Wayland: ``wlopm --off ALL`` / ``wlopm --on ALL``
  (when ``wlopm`` is on PATH)
* macOS: ``pmset displaysleepnow`` (auto-wake on input)
* Windows: ``SendMessageW(HWND_BROADCAST, WM_SYSCOMMAND,
  SC_MONITORPOWER, 2)`` via ``ctypes.windll``

Each call is wrapped so a missing tool / unsupported environment
just records the failure on the returned :class:`OutageResult`
without raising.  Set ``strict=True`` to escalate to an
exception instead.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any


@dataclass
class OutageResult:
    backend: str
    blanked: bool = False
    restored: bool = False
    notes: list[str] = field(default_factory=list)
    error: str | None = None


def _has(name: str) -> bool:
    return shutil.which(name) is not None


def _detect_backend() -> str:
    sys_p = sys.platform
    if sys_p.startswith("linux"):
        # Wayland session?  Prefer wlopm if available.
        import os
        if (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland") \
                and _has("wlopm"):
            return "wlopm"
        if _has("xset"):
            return "xset"
        return "linux-none"
    if sys_p == "darwin":
        return "pmset"
    if sys_p == "win32":
        return "windows"
    return "unknown"


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _windows_set_monitor(state: int) -> int:
    """state: 2 = off, -1 = on.  Returns rc-like int (0 == ok)."""
    try:
        import ctypes
        # SC_MONITORPOWER = 0xF170, WM_SYSCOMMAND = 0x0112
        # HWND_BROADCAST = 0xFFFF
        return ctypes.windll.user32.SendMessageW(
            0xFFFF, 0x0112, 0xF170, state,
        )
    except Exception:  # noqa: BLE001
        return -1


@dataclass
class Outage:
    """Display blanker / restorer.

    Args:
        backend: Force a specific backend; ``None`` (default) auto-
            detects.  Recognised: ``"xset"``, ``"wlopm"``,
            ``"pmset"``, ``"windows"``, ``"none"`` (no-op).
        strict: Raise ``RuntimeError`` if blanking or restoring
            fails.  Default is to record the failure on
            :attr:`last_result` and keep going.
        on_restore: Optional callable run after the display is
            woken up.
    """

    backend: str | None = None
    strict: bool = False
    on_restore: Callable[[], Any] | None = None
    last_result: OutageResult | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.backend is None:
            self.backend = _detect_backend()

    # ------------------------------------------------------------------
    # Core ops
    # ------------------------------------------------------------------

    def black_out(self) -> OutageResult:
        """Turn the display off."""
        result = OutageResult(backend=self.backend or "unknown")
        try:
            self._do_blank(result)
            result.blanked = True
        except Exception as exc:  # noqa: BLE001
            result.error = str(exc)
            if self.strict:
                self.last_result = result
                raise
        self.last_result = result
        return result

    def restore(self) -> OutageResult:
        """Turn the display back on.  Always callable, even if
        :meth:`black_out` failed — restore is a best-effort wake."""
        result = OutageResult(backend=self.backend or "unknown")
        try:
            self._do_restore(result)
            result.restored = True
        except Exception as exc:  # noqa: BLE001
            result.error = str(exc)
            if self.strict:
                self.last_result = result
                raise
        if self.on_restore is not None:
            try:
                self.on_restore()
            except Exception as exc:  # noqa: BLE001
                result.notes.append(f"on_restore raised: {exc}")
        self.last_result = result
        return result

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> Outage:
        self.black_out()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        # Always restore, even if the body raised.
        self.restore()
        return False  # never suppress the original exception

    # ------------------------------------------------------------------
    # Backend dispatch
    # ------------------------------------------------------------------

    def _do_blank(self, result: OutageResult) -> None:
        b = self.backend
        if b == "xset":
            r = _run(["xset", "dpms", "force", "off"])
            result.notes.append(f"xset dpms force off rc={r.returncode}")
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip() or "xset failed")
        elif b == "wlopm":
            r = _run(["wlopm", "--off", "*"])
            result.notes.append(f"wlopm --off * rc={r.returncode}")
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip() or "wlopm failed")
        elif b == "pmset":
            r = _run(["pmset", "displaysleepnow"])
            result.notes.append(f"pmset displaysleepnow rc={r.returncode}")
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip() or "pmset failed")
        elif b == "windows":
            rc = _windows_set_monitor(2)
            result.notes.append(f"windows monitor off rc={rc}")
        else:
            result.notes.append(
                f"no display-off backend available (backend={b!r}); skipping",
            )

    def _do_restore(self, result: OutageResult) -> None:
        b = self.backend
        if b == "xset":
            r = _run(["xset", "dpms", "force", "on"])
            result.notes.append(f"xset dpms force on rc={r.returncode}")
        elif b == "wlopm":
            r = _run(["wlopm", "--on", "*"])
            result.notes.append(f"wlopm --on * rc={r.returncode}")
        elif b == "pmset":
            # pmset has no explicit wake — input wakes it.  Best effort:
            # call ``caffeinate -u -t 1`` to nudge the display.
            r = _run(["caffeinate", "-u", "-t", "1"])
            result.notes.append(f"caffeinate -u rc={r.returncode}")
        elif b == "windows":
            rc = _windows_set_monitor(-1)
            result.notes.append(f"windows monitor on rc={rc}")
        else:
            result.notes.append(
                f"no display-on backend available (backend={b!r}); skipping",
            )


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def outage(*, backend: str | None = None, strict: bool = False) -> Outage:
    return Outage(backend=backend, strict=strict)


def black_out(*, backend: str | None = None) -> OutageResult:
    """One-shot blank.  Caller is responsible for restoring."""
    return Outage(backend=backend).black_out()


def restore_display(*, backend: str | None = None) -> OutageResult:
    """One-shot wake."""
    return Outage(backend=backend).restore()


def detect_backend() -> str:
    """Return the backend that would be used on this host."""
    return _detect_backend()


def platform_summary() -> dict[str, Any]:
    """Diagnostic helper for bug reports."""
    return {
        "platform": sys.platform,
        "system": platform.system(),
        "backend": _detect_backend(),
        "xset": _has("xset"),
        "wlopm": _has("wlopm"),
        "pmset": _has("pmset"),
    }


__all__ = [
    "Outage",
    "OutageResult",
    "black_out",
    "detect_backend",
    "outage",
    "platform_summary",
    "restore_display",
]
