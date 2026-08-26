"""scriptgen.widgets — the controls Tkinter does not have.

Three of them, all drawn on a ``Canvas`` because Tk's built-in widgets
cannot be themed dark on every platform (``ttk.Scale`` on macOS ignores
almost everything you tell it) and two of these do not exist at all:

* :class:`DualSlider` — a range with two handles. Tk has no such widget,
  and two ``Scale``s side by side lets the low handle pass the high one.
* :class:`ToggleSwitch` — an on/off switch. ``Checkbutton`` works, and
  looks like 1998 on three platforms in three different ways.
* :class:`LogSlider` — a slider that moves in decades, for learning rate
  and weight decay. A linear slider over [1e-6, 1e-3] spends 90% of its
  travel above 1e-4, which makes the interesting region untouchable.

All three are plain ``Frame`` subclasses with a ``command`` callback and
a ``get``/``set`` pair, so they drop into the same layout code as a
built-in widget.

Importing this module does not require a display. The Tk import happens
at class definition time, which means a headless machine can still
import :mod:`hypernix.scriptgen.params` and generate a script — the CLI
path does exactly that, and a GUI module that breaks the CLI on a server
is a GUI module nobody can use.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from .theme import FONTS, PALETTE

__all__ = ["DualSlider", "ToggleSwitch", "LogSlider", "tk_available"]


def tk_available() -> tuple[bool, str]:
    """``(ok, reason)`` — is there a usable Tk with a display?

    Checked rather than assumed because the two failure modes are
    different and the fixes are different: Tk missing is an apt-get,
    ``$DISPLAY`` missing is an X forwarding problem, and telling someone
    the wrong one wastes their afternoon.
    """
    try:
        import tkinter
    except ImportError as exc:
        return False, (
            f"Tkinter is not installed ({exc}). On Debian/Ubuntu: "
            "sudo apt install python3-tk. On macOS it ships with python.org builds; "
            "Homebrew Python needs `brew install python-tk`."
        )
    try:
        root = tkinter.Tk()
        root.withdraw()
        root.destroy()
    except Exception as exc:  # noqa: BLE001 - TclError and friends
        return False, (
            f"Tkinter is installed but cannot open a display ({exc}). Over SSH, use "
            "`ssh -X`; in a container, pass the host's X socket. `hnx scriptgen --cli` "
            "generates a script without a GUI."
        )
    return True, ""


try:  # pragma: no cover - exercised only where Tk exists
    import tkinter as tk

    _BASE = tk.Frame
except ImportError:  # pragma: no cover
    tk = None  # type: ignore[assignment]
    _BASE = object  # type: ignore[misc,assignment]


class _CanvasControl(_BASE):  # type: ignore[misc,valid-type]
    """Shared drawing helpers for the three controls."""

    def __init__(self, master: Any, *, width: int, height: int, **kwargs: Any) -> None:
        if tk is None:  # pragma: no cover
            raise RuntimeError("Tkinter is not available")
        super().__init__(master, bg=kwargs.pop("bg", PALETTE.charcoal), **kwargs)
        self.canvas = tk.Canvas(
            self, width=width, height=height,
            bg=PALETTE.charcoal, highlightthickness=0, bd=0,
        )
        self.canvas.pack(fill="both", expand=True)


class DualSlider(_CanvasControl):
    """A range with two handles that cannot cross.

    "Cannot cross" is the whole reason this exists rather than two
    ``Scale``s: a range widget whose low handle can be dragged past its
    high one produces an inverted range, and every consumer then has to
    remember to sort it. Clamping here means nothing downstream has to.
    """

    def __init__(
        self,
        master: Any,
        *,
        minimum: float = 0.0,
        maximum: float = 1.0,
        low: float | None = None,
        high: float | None = None,
        logarithmic: bool = False,
        width: int = 260,
        height: int = 34,
        command: Callable[[float, float], None] | None = None,
        fmt: str = "{:.4g}",
    ) -> None:
        super().__init__(master, width=width, height=height)
        if minimum >= maximum:
            raise ValueError("minimum must be below maximum")
        if logarithmic and minimum <= 0:
            raise ValueError("a logarithmic range needs a positive minimum")
        self.minimum, self.maximum = float(minimum), float(maximum)
        self.logarithmic = logarithmic
        self.command = command
        self.fmt = fmt
        self._width, self._height = width, height
        self._pad = 10
        self._low = float(low if low is not None else minimum)
        self._high = float(high if high is not None else maximum)
        self._dragging: str | None = None

        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", lambda _e: setattr(self, "_dragging", None))
        self._redraw()

    # -- value <-> pixel ----------------------------------------------

    def _to_fraction(self, value: float) -> float:
        if self.logarithmic:
            lo, hi = math.log(self.minimum), math.log(self.maximum)
            return (math.log(max(value, self.minimum)) - lo) / (hi - lo)
        return (value - self.minimum) / (self.maximum - self.minimum)

    def _from_fraction(self, fraction: float) -> float:
        fraction = min(1.0, max(0.0, fraction))
        if self.logarithmic:
            lo, hi = math.log(self.minimum), math.log(self.maximum)
            return math.exp(lo + fraction * (hi - lo))
        return self.minimum + fraction * (self.maximum - self.minimum)

    def _x(self, value: float) -> float:
        span = self._width - 2 * self._pad
        return self._pad + self._to_fraction(value) * span

    def _value_at(self, x: float) -> float:
        span = self._width - 2 * self._pad
        return self._from_fraction((x - self._pad) / span)

    # -- interaction ---------------------------------------------------

    def _on_press(self, event: Any) -> None:
        # Nearest handle wins, so a click anywhere on the track grabs the
        # one the user meant rather than always the low one.
        self._dragging = (
            "low"
            if abs(event.x - self._x(self._low)) <= abs(event.x - self._x(self._high))
            else "high"
        )
        self._on_drag(event)

    def _on_drag(self, event: Any) -> None:
        if self._dragging is None:
            return
        value = self._value_at(event.x)
        if self._dragging == "low":
            self._low = min(value, self._high)
        else:
            self._high = max(value, self._low)
        self._redraw()
        if self.command is not None:
            self.command(self._low, self._high)

    # -- drawing -------------------------------------------------------

    def _redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        mid = self._height // 2
        c.create_line(self._pad, mid, self._width - self._pad, mid,
                      fill=PALETTE.edge, width=3, capstyle="round")
        c.create_line(self._x(self._low), mid, self._x(self._high), mid,
                      fill=PALETTE.red, width=3, capstyle="round")
        for value in (self._low, self._high):
            x = self._x(value)
            c.create_oval(x - 6, mid - 6, x + 6, mid + 6,
                          fill=PALETTE.red_bright, outline=PALETTE.obsidian, width=2)
        c.create_text(self._pad, mid - 13, anchor="w", text=self.fmt.format(self._low),
                      fill=PALETTE.text_dim, font=FONTS["tiny"])
        c.create_text(self._width - self._pad, mid - 13, anchor="e",
                      text=self.fmt.format(self._high),
                      fill=PALETTE.text_dim, font=FONTS["tiny"])

    # -- api -----------------------------------------------------------

    def get(self) -> tuple[float, float]:
        return self._low, self._high

    def set(self, low: float, high: float) -> None:
        self._low = max(self.minimum, min(float(low), self.maximum))
        self._high = max(self._low, min(float(high), self.maximum))
        self._redraw()


class LogSlider(_CanvasControl):
    """A single slider that moves in decades.

    For learning rate and weight decay. A linear slider over
    [1e-6, 1e-3] puts 90% of its travel above 1e-4 — the region people
    care about is a few pixels wide, which is not a control, it is a
    dare.
    """

    def __init__(
        self,
        master: Any,
        *,
        minimum: float = 1e-6,
        maximum: float = 1e-2,
        value: float | None = None,
        width: int = 260,
        height: int = 34,
        command: Callable[[float], None] | None = None,
        fmt: str = "{:.3g}",
    ) -> None:
        super().__init__(master, width=width, height=height)
        if minimum <= 0:
            raise ValueError("a logarithmic slider needs a positive minimum")
        if minimum >= maximum:
            raise ValueError("minimum must be below maximum")
        self.minimum, self.maximum = float(minimum), float(maximum)
        self.command = command
        self.fmt = fmt
        self._width, self._height = width, height
        self._pad = 10
        self._value = float(value if value is not None else minimum)

        self.canvas.bind("<Button-1>", self._on_drag)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self._redraw()

    def _x(self, value: float) -> float:
        lo, hi = math.log(self.minimum), math.log(self.maximum)
        fraction = (math.log(max(value, self.minimum)) - lo) / (hi - lo)
        return self._pad + fraction * (self._width - 2 * self._pad)

    def _on_drag(self, event: Any) -> None:
        span = self._width - 2 * self._pad
        fraction = min(1.0, max(0.0, (event.x - self._pad) / span))
        lo, hi = math.log(self.minimum), math.log(self.maximum)
        self._value = math.exp(lo + fraction * (hi - lo))
        self._redraw()
        if self.command is not None:
            self.command(self._value)

    def _redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        mid = self._height // 2
        c.create_line(self._pad, mid, self._width - self._pad, mid,
                      fill=PALETTE.edge, width=3, capstyle="round")
        # A tick per decade: the scale is meaningless without them.
        decade = math.ceil(math.log10(self.minimum))
        while 10 ** decade <= self.maximum:
            x = self._x(10 ** decade)
            c.create_line(x, mid - 5, x, mid + 5, fill=PALETTE.edge, width=1)
            decade += 1
        c.create_line(self._pad, mid, self._x(self._value), mid,
                      fill=PALETTE.red, width=3, capstyle="round")
        x = self._x(self._value)
        c.create_oval(x - 6, mid - 6, x + 6, mid + 6,
                      fill=PALETTE.red_bright, outline=PALETTE.obsidian, width=2)
        c.create_text(self._width - self._pad, mid - 13, anchor="e",
                      text=self.fmt.format(self._value),
                      fill=PALETTE.text, font=FONTS["tiny"])

    def get(self) -> float:
        return self._value

    def set(self, value: float) -> None:
        self._value = max(self.minimum, min(float(value), self.maximum))
        self._redraw()


class ToggleSwitch(_CanvasControl):
    """An on/off switch that looks the same on every platform."""

    def __init__(
        self,
        master: Any,
        *,
        value: bool = False,
        width: int = 46,
        height: int = 24,
        command: Callable[[bool], None] | None = None,
    ) -> None:
        super().__init__(master, width=width, height=height)
        self._value = bool(value)
        self.command = command
        self._width, self._height = width, height
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.configure(cursor="hand2")
        self._redraw()

    def _on_click(self, _event: Any) -> None:
        self._value = not self._value
        self._redraw()
        if self.command is not None:
            self.command(self._value)

    def _redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        radius = self._height // 2
        track = PALETTE.red if self._value else PALETTE.slate_high
        # A rounded track from two circles and a rectangle: Tk has no
        # rounded-rectangle primitive.
        c.create_oval(0, 0, self._height, self._height, fill=track, outline=track)
        c.create_oval(self._width - self._height, 0, self._width, self._height,
                      fill=track, outline=track)
        c.create_rectangle(radius, 0, self._width - radius, self._height,
                           fill=track, outline=track)
        knob_x = self._width - radius if self._value else radius
        c.create_oval(knob_x - radius + 3, 3, knob_x + radius - 3, self._height - 3,
                      fill=PALETTE.text if self._value else PALETTE.text_faint,
                      outline="")

    def get(self) -> bool:
        return self._value

    def set(self, value: bool) -> None:
        self._value = bool(value)
        self._redraw()
