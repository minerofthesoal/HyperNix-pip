"""hypernix.monitoring.tvtoppro — tvtop++'s numbers, btop++'s presentation.

    tvtoppro
    tvtoppro --theme gruvbox-dark
    tvtoppro --theme ~/.config/btop/themes/nord.theme
    tvtoppro --list-themes

Not built on cctvtop
--------------------
``cctvtop`` wraps a compiled C++ dashboard and shells out to it; when the
extension is not built for the running Python it falls back to importing
``tvtop_plus_plus`` and rendering that instead. So "run cctvtop" means
one of two different programs depending on how the wheel was built, and
the fallback is the one most people see.

This takes the other half: :class:`~hypernix.monitoring.tvtop_plus_plus.TVTopPlusPlus`
is used purely as a *stat source* — its ``latest_frame`` already collects
per-core CPU, the /proc/meminfo breakdown, the full ``nvidia-smi`` row
and the training-log tail — and everything drawn is new.

What "presented exactly like btop++" means here
-----------------------------------------------
btop++'s look is four specific things, and skipping any of them gives
something that is merely a boxed TUI:

1. **Boxes titled in the border.** ``┌─┤ cpu ├───────┐``, not a heading
   inside the box. The title sits in the rule with a bracket either side
   and the box number in the opposite corner.
2. **Braille graphs.** Two samples per character cell horizontally, four
   per cell vertically, so a 60x4 graph plots 120 points across 16
   levels. Block characters give 60 points across 4.
3. **Gradient meters.** A bar is not one colour that changes with the
   value — each *cell* takes its colour from its own position along a
   start/mid/end ramp, so a full bar shows the whole ramp and a quarter
   bar shows only the cool end. Getting this wrong is what makes a
   btop-alike look like a progress bar.
4. **Themes as data.** btop's ``.theme`` files are ``theme[key]="#hex"``
   lines, and this reads them directly — so a theme someone already has
   in ``~/.config/btop/themes`` works here without conversion. Six are
   built in.

Colour customization
--------------------
``--theme`` takes a built-in name, a path to a btop ``.theme`` file, or a
JSON file of the same keys. ``--dump-theme`` writes the active one out in
btop's format, which is the quickest way to start editing one. Unknown
keys are kept and unset ones inherit from the default, so a partial theme
is a valid theme rather than a crash.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "Theme",
    "THEMES",
    "load_theme",
    "parse_btop_theme",
    "gradient",
    "braille_graph",
    "meter",
    "box_top",
    "box_bottom",
    "TvTopPro",
    "cli_main",
    "main",
]

# ---------------------------------------------------------------------------
# Colour
# ---------------------------------------------------------------------------

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{2}|[0-9a-fA-F]{6})$")


def _rgb(value: str) -> tuple[int, int, int]:
    """A btop theme colour to ``(r, g, b)``.

    btop accepts ``#RRGGBB`` and a two-digit greyscale shorthand
    ``#XX``. The shorthand is not a truncated hex triplet — it is a grey
    level — and reading it as one turns every neutral in a real theme
    into a dark red.
    """
    text = str(value).strip().strip('"').strip("'")
    if not _HEX.match(text):
        raise ValueError(f"{value!r} is not a btop theme colour (#RRGGBB or #XX)")
    digits = text[1:]
    if len(digits) == 2:
        level = int(digits, 16)
        return (level, level, level)
    return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16))


def _hex(rgb: tuple[int, int, int]) -> str:
    red, green, blue = (max(0, min(255, int(c))) for c in rgb)
    return f"#{red:02x}{green:02x}{blue:02x}"


def gradient(start: str, mid: str, end: str, steps: int) -> list[str]:
    """``steps`` colours ramping start -> mid -> end.

    Two linear segments rather than one, because btop's ramps are not
    monotonic in any channel: the cyan-yellow-red CPU ramp passes
    *through* yellow, and interpolating cyan straight to red gives a
    muddy purple that looks nothing like it.
    """
    if steps <= 0:
        return []
    if steps == 1:
        return [_hex(_rgb(start))]
    first, middle, last = _rgb(start), _rgb(mid), _rgb(end)
    out: list[str] = []
    half = (steps - 1) / 2
    for index in range(steps):
        if index <= half:
            fraction = index / half if half else 0.0
            low, high = first, middle
        else:
            fraction = (index - half) / (steps - 1 - half)
            low, high = middle, last
        out.append(_hex(tuple(
            low[channel] + (high[channel] - low[channel]) * fraction
            for channel in range(3)
        )))
    return out


#: Every key a theme can set. The names are btop's, so its own theme
#: files load unchanged.
_THEME_KEYS = (
    "main_bg", "main_fg", "title", "hi_fg", "selected_bg", "selected_fg",
    "inactive_fg", "graph_text", "meter_bg", "proc_misc", "div_line",
    "cpu_box", "mem_box", "net_box", "proc_box",
    "cpu_start", "cpu_mid", "cpu_end",
    "free_start", "free_mid", "free_end",
    "used_start", "used_mid", "used_end",
    "available_start", "available_mid", "available_end",
    "temp_start", "temp_mid", "temp_end",
    "download_start", "download_mid", "download_end",
    "upload_start", "upload_mid", "upload_end",
)


@dataclass
class Theme:
    """A btop-compatible palette.

    Every field defaults, so a theme file that sets three keys is a valid
    theme with three keys changed. btop behaves the same way and the
    alternative — refusing a partial file — makes hand-editing one a
    guessing game about which keys are mandatory.
    """

    name: str = "hypernix"
    colors: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        merged = dict(_DEFAULT_COLORS)
        merged.update({k: v for k, v in self.colors.items() if v})
        self.colors = merged

    def __getitem__(self, key: str) -> str:
        return self.colors.get(key, _DEFAULT_COLORS.get(key, "#cccccc"))

    def ramp(self, prefix: str, steps: int) -> list[str]:
        """The ``<prefix>_start/_mid/_end`` gradient, ``steps`` long."""
        return gradient(
            self[f"{prefix}_start"], self[f"{prefix}_mid"], self[f"{prefix}_end"],
            steps,
        )

    def to_btop(self) -> str:
        """This theme as a btop ``.theme`` file."""
        lines = [f'# {self.name} — written by hypernix tvtoppro']
        lines += [f'theme[{key}]="{self.colors[key]}"' for key in _THEME_KEYS
                  if key in self.colors]
        return "\n".join(lines) + "\n"


_DEFAULT_COLORS: dict[str, str] = {
    "main_bg": "#00", "main_fg": "#cc", "title": "#ee", "hi_fg": "#7bd88f",
    "selected_bg": "#2f3b47", "selected_fg": "#ffffff", "inactive_fg": "#40",
    "graph_text": "#60", "meter_bg": "#40", "proc_misc": "#7bd88f",
    "div_line": "#30",
    "cpu_box": "#3d7b46", "mem_box": "#8a882e", "net_box": "#423ba5",
    "proc_box": "#923535",
    "cpu_start": "#50f0ff", "cpu_mid": "#f2e266", "cpu_end": "#fc2929",
    "free_start": "#223014", "free_mid": "#b5e685", "free_end": "#dcff85",
    "used_start": "#0b1a29", "used_mid": "#4c7cb0", "used_end": "#74e6fc",
    "available_start": "#292107", "available_mid": "#a3a10a",
    "available_end": "#fffa50",
    "temp_start": "#4897d4", "temp_mid": "#5474e8", "temp_end": "#ff40b6",
    "download_start": "#de6e6e", "download_mid": "#c72e2e", "download_end": "#ff0000",
    "upload_start": "#63c5b7", "upload_mid": "#26c9b0", "upload_end": "#00ffd0",
}


THEMES: dict[str, Theme] = {
    "hypernix": Theme("hypernix", {}),
    "gruvbox-dark": Theme("gruvbox-dark", {
        "main_bg": "#282828", "main_fg": "#ebdbb2", "title": "#fbf1c7",
        "hi_fg": "#fabd2f", "selected_bg": "#3c3836", "selected_fg": "#fbf1c7",
        "inactive_fg": "#665c54", "graph_text": "#a89984", "meter_bg": "#504945",
        "proc_misc": "#8ec07c", "div_line": "#504945",
        "cpu_box": "#98971a", "mem_box": "#d79921", "net_box": "#458588",
        "proc_box": "#cc241d",
        "cpu_start": "#83a598", "cpu_mid": "#fabd2f", "cpu_end": "#fb4934",
        "free_start": "#427b58", "free_mid": "#8ec07c", "free_end": "#b8bb26",
        "used_start": "#458588", "used_mid": "#83a598", "used_end": "#d3869b",
        "available_start": "#79740e", "available_mid": "#b57614",
        "available_end": "#fabd2f",
        "temp_start": "#458588", "temp_mid": "#d79921", "temp_end": "#fb4934",
    }),
    "nord": Theme("nord", {
        "main_bg": "#2e3440", "main_fg": "#d8dee9", "title": "#eceff4",
        "hi_fg": "#88c0d0", "selected_bg": "#434c5e", "selected_fg": "#eceff4",
        "inactive_fg": "#4c566a", "graph_text": "#7b88a1", "meter_bg": "#3b4252",
        "proc_misc": "#a3be8c", "div_line": "#434c5e",
        "cpu_box": "#81a1c1", "mem_box": "#8fbcbb", "net_box": "#b48ead",
        "proc_box": "#bf616a",
        "cpu_start": "#8fbcbb", "cpu_mid": "#ebcb8b", "cpu_end": "#bf616a",
        "free_start": "#4c566a", "free_mid": "#a3be8c", "free_end": "#d8dee9",
        "used_start": "#5e81ac", "used_mid": "#81a1c1", "used_end": "#88c0d0",
        "available_start": "#5e5b3a", "available_mid": "#d08770",
        "available_end": "#ebcb8b",
        "temp_start": "#5e81ac", "temp_mid": "#d08770", "temp_end": "#bf616a",
    }),
    "dracula": Theme("dracula", {
        "main_bg": "#282a36", "main_fg": "#f8f8f2", "title": "#ffffff",
        "hi_fg": "#bd93f9", "selected_bg": "#44475a", "selected_fg": "#f8f8f2",
        "inactive_fg": "#6272a4", "graph_text": "#8be9fd", "meter_bg": "#44475a",
        "proc_misc": "#50fa7b", "div_line": "#44475a",
        "cpu_box": "#bd93f9", "mem_box": "#50fa7b", "net_box": "#8be9fd",
        "proc_box": "#ff79c6",
        "cpu_start": "#8be9fd", "cpu_mid": "#f1fa8c", "cpu_end": "#ff5555",
        "free_start": "#2d4a35", "free_mid": "#50fa7b", "free_end": "#f8f8f2",
        "used_start": "#44475a", "used_mid": "#bd93f9", "used_end": "#ff79c6",
        "available_start": "#4a4a2d", "available_mid": "#ffb86c",
        "available_end": "#f1fa8c",
        "temp_start": "#8be9fd", "temp_mid": "#ffb86c", "temp_end": "#ff5555",
    }),
    "tokyo-night": Theme("tokyo-night", {
        "main_bg": "#1a1b26", "main_fg": "#c0caf5", "title": "#c0caf5",
        "hi_fg": "#7aa2f7", "selected_bg": "#33467c", "selected_fg": "#c0caf5",
        "inactive_fg": "#565f89", "graph_text": "#737aa2", "meter_bg": "#292e42",
        "proc_misc": "#9ece6a", "div_line": "#292e42",
        "cpu_box": "#7aa2f7", "mem_box": "#9ece6a", "net_box": "#bb9af7",
        "proc_box": "#f7768e",
        "cpu_start": "#7dcfff", "cpu_mid": "#e0af68", "cpu_end": "#f7768e",
        "free_start": "#2c3b2c", "free_mid": "#9ece6a", "free_end": "#c0caf5",
        "used_start": "#3d59a1", "used_mid": "#7aa2f7", "used_end": "#7dcfff",
        "available_start": "#4a3d2c", "available_mid": "#ff9e64",
        "available_end": "#e0af68",
        "temp_start": "#7dcfff", "temp_mid": "#ff9e64", "temp_end": "#f7768e",
    }),
    "monokai": Theme("monokai", {
        "main_bg": "#272822", "main_fg": "#f8f8f2", "title": "#f9f8f5",
        "hi_fg": "#a6e22e", "selected_bg": "#49483e", "selected_fg": "#f8f8f2",
        "inactive_fg": "#75715e", "graph_text": "#a59f85", "meter_bg": "#3e3d32",
        "proc_misc": "#a6e22e", "div_line": "#49483e",
        "cpu_box": "#a6e22e", "mem_box": "#e6db74", "net_box": "#66d9ef",
        "proc_box": "#f92672",
        "cpu_start": "#66d9ef", "cpu_mid": "#e6db74", "cpu_end": "#f92672",
        "free_start": "#2d3a1e", "free_mid": "#a6e22e", "free_end": "#e6db74",
        "used_start": "#1e3a3a", "used_mid": "#66d9ef", "used_end": "#ae81ff",
        "available_start": "#3a341e", "available_mid": "#fd971f",
        "available_end": "#e6db74",
        "temp_start": "#66d9ef", "temp_mid": "#fd971f", "temp_end": "#f92672",
    }),
    "mono": Theme("mono", {
        # For a terminal without truecolor, and for a screenshot that has
        # to survive being printed. Every ramp is grey.
        "main_bg": "#00", "main_fg": "#cc", "title": "#ff", "hi_fg": "#ee",
        "selected_bg": "#40", "selected_fg": "#ff", "inactive_fg": "#50",
        "graph_text": "#88", "meter_bg": "#30", "proc_misc": "#bb",
        "div_line": "#40",
        "cpu_box": "#88", "mem_box": "#88", "net_box": "#88", "proc_box": "#88",
        "cpu_start": "#55", "cpu_mid": "#aa", "cpu_end": "#ff",
        "free_start": "#33", "free_mid": "#88", "free_end": "#dd",
        "used_start": "#33", "used_mid": "#88", "used_end": "#dd",
        "available_start": "#33", "available_mid": "#88", "available_end": "#dd",
        "temp_start": "#55", "temp_mid": "#aa", "temp_end": "#ff",
    }),
}

_BTOP_LINE = re.compile(r'^\s*theme\[(?P<key>[a-z_]+)\]\s*=\s*"?(?P<value>#[0-9a-fA-F]+)"?')


def parse_btop_theme(text: str, *, name: str = "custom") -> Theme:
    """A btop ``.theme`` file's contents to a :class:`Theme`.

    Lines that are not ``theme[key]="#colour"`` are ignored rather than
    refused: real theme files carry comments and the occasional setting
    this does not use, and rejecting the file over one of them would
    mean none of them load.
    """
    colors: dict[str, str] = {}
    for line in text.splitlines():
        found = _BTOP_LINE.match(line)
        if not found:
            continue
        try:
            _rgb(found.group("value"))
        except ValueError:
            continue
        colors[found.group("key")] = found.group("value")
    if not colors:
        raise ValueError("no theme[...] lines found; is this a btop theme file?")
    return Theme(name, colors)


def load_theme(name_or_path: str | None) -> Theme:
    """A built-in theme by name, or a ``.theme``/``.json`` file by path."""
    if not name_or_path:
        return THEMES[os.environ.get("TVTOPPRO_THEME", "hypernix")] \
            if os.environ.get("TVTOPPRO_THEME") in THEMES else THEMES["hypernix"]
    key = str(name_or_path).strip()
    if key in THEMES:
        return THEMES[key]

    path = Path(key).expanduser()
    if not path.is_file():
        raise ValueError(
            f"Unknown theme {key!r}. Built in: {', '.join(sorted(THEMES))}. "
            f"Or give a path to a btop .theme or a JSON file."
        )
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".json":
        payload = json.loads(text)
        colors = payload.get("colors", payload)
        return Theme(payload.get("name", path.stem), dict(colors))
    return parse_btop_theme(text, name=path.stem)


# ---------------------------------------------------------------------------
# btop's drawing primitives
# ---------------------------------------------------------------------------

#: Braille dot bit for ``(x, y)`` within a 2x4 cell, y counted from the
#: top. The fourth row is 0x40/0x80 rather than continuing the pattern,
#: which is the detail that makes hand-written braille graphs come out
#: with a gap in the bottom row.
_DOTS = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))


def braille_graph(values: list[float], width: int, height: int) -> list[str]:
    """A history as braille rows, newest on the right.

    Two samples per cell across and four levels per cell down, so a
    ``60 x 4`` graph plots 120 points over 16 levels. Values are
    fractions in ``[0, 1]``; anything outside is clamped rather than
    refused, because a percentage that briefly reads 100.4 is not worth
    ending a dashboard over.

    Returns ``height`` strings of exactly ``width`` characters, top row
    first, so a caller can colour each row from a gradient.
    """
    if width <= 0 or height <= 0:
        return []
    samples = width * 2
    tail = [max(0.0, min(1.0, float(v))) for v in values[-samples:]]
    tail = [0.0] * (samples - len(tail)) + tail

    levels = height * 4
    cells = [[0] * width for _ in range(height)]
    for index, value in enumerate(tail):
        filled = int(round(value * levels))
        if filled <= 0:
            continue
        column, half = divmod(index, 2)
        for level in range(filled):
            # level 0 is the bottom of the graph.
            from_top = levels - 1 - level
            row, within = divmod(from_top, 4)
            cells[row][column] |= _DOTS[half][within]
    return ["".join(chr(0x2800 + cell) for cell in row) for row in cells]


def meter(fraction: float, width: int, ramp: list[str], *,
          empty: str = "#404040") -> str:
    """A btop-style gradient meter as Rich markup.

    Each cell takes its colour from *its own* position along the ramp,
    not from the value — so a full bar shows the whole ramp and a quarter
    bar shows only its cool end. A bar that is one colour chosen by the
    value is a progress bar, and it is the single thing that most makes a
    btop-alike look like something else.
    """
    if width <= 0:
        return ""
    fraction = max(0.0, min(1.0, float(fraction)))
    filled = int(round(fraction * width))
    colours = ramp if len(ramp) == width else gradient(
        ramp[0] if ramp else "#50f0ff",
        ramp[len(ramp) // 2] if ramp else "#f2e266",
        ramp[-1] if ramp else "#fc2929",
        width,
    )
    parts = [
        f"[{colours[i]}]█[/]" if i < filled else f"[{empty}]─[/]"
        for i in range(width)
    ]
    return "".join(parts)


def box_top(title: str, width: int, *, line: str, accent: str,
            number: str = "") -> str:
    """btop's top border: the title sits *in* the rule, bracketed.

    ``┌─┤ cpu ├────────────────────────────┤1├─┐``. A heading inside the
    box is the ordinary way to do this and it is the wrong look.
    """
    if width < 8:
        return f"[{line}]{'─' * max(0, width)}[/]"
    left = f"[{line}]┌─┤[/][{accent}]{title}[/][{line}]├[/]"
    if number:
        right = f"[{line}]┤[/][{accent}]{number}[/][{line}]├─┐[/]"
        used = (4 + len(title)) + (4 + len(number))
    else:
        right = f"[{line}]─┐[/]"
        used = (4 + len(title)) + 2
    return left + f"[{line}]{'─' * max(0, width - used)}[/]" + right


def box_bottom(width: int, *, line: str) -> str:
    return f"[{line}]└{'─' * max(0, width - 2)}┘[/]"


def _fmt_bytes(value: float | int | None) -> str:
    if value is None:
        return "  --  "
    size = float(value)
    for unit in ("B", "K", "M", "G", "T"):
        if size < 1024 or unit == "T":
            return f"{size:5.1f}{unit}"
        size /= 1024
    return f"{size:5.1f}T"


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "--:--:--"
    seconds = int(max(0, seconds))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


# ---------------------------------------------------------------------------
# The dashboard
# ---------------------------------------------------------------------------


@dataclass
class TvTopPro:
    """tvtop++'s frame, drawn the way btop++ draws.

    Composition rather than inheritance: the stat source is a
    :class:`~hypernix.monitoring.tvtop_plus_plus.TVTopPlusPlus` held as an
    attribute, so the two can diverge without either dragging the other.
    Every method below is presentation.
    """

    log_path: Path | str | None = None
    refresh_seconds: float = 1.0
    theme: Theme = field(default_factory=lambda: THEMES["hypernix"])
    width: int | None = None
    show_processes: bool = True
    source: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.source is None:
            from .tvtop_plus_plus import TVTopPlusPlus

            self.source = TVTopPlusPlus(
                log_path=self.log_path, refresh_seconds=self.refresh_seconds
            )

    # -- pieces ---------------------------------------------------------

    def latest_frame(self):
        return self.source.latest_frame()

    @staticmethod
    def _cells(markup: str) -> int:
        """Printed width of some Rich markup.

        Measured rather than counted. The strings here carry colour tags
        that print as nothing and braille that prints as one cell each,
        so ``len()`` is wrong in both directions and a right border
        placed by ``len()`` lands in a different column on every row --
        which is exactly what a btop-alike must not look like.
        """
        from rich.text import Text

        return Text.from_markup(markup).cell_len

    def _row(self, markup: str, width: int) -> str:
        """One bordered line, padded *or truncated* so the edge lines up.

        Truncation is not the unlikely half. Every label here fits at
        100 columns and several do not at 60 -- and an over-long row does
        not wrap tidily, it pushes the right border onto the next line
        and every box below it looks broken. Rich does the cutting,
        because a naive slice of markup can cut a colour tag in two.
        """
        from rich.text import Text

        line = self.theme["div_line"]
        inner = max(0, width - 4)
        text = Text.from_markup(markup)
        if text.cell_len > inner:
            text.truncate(inner, overflow="ellipsis")
            markup = text.markup
        pad = max(0, inner - text.cell_len)
        return f"[{line}]│[/] {markup}{' ' * pad} [{line}]│[/]"

    def _graph_rows(self, history: list[float], width: int, height: int,
                    prefix: str) -> list[str]:
        """A braille graph, each row coloured by its own height.

        btop's graphs ramp bottom-to-top, so the ramp is indexed by row
        rather than by value — the top of a busy graph is red because it
        is the top, not because the latest sample was high.
        """
        rows = braille_graph(history, width, height)
        ramp = self.theme.ramp(prefix, max(height, 1))
        # ramp[0] is the cool end and row 0 is the top of the graph.
        return [f"[{ramp[height - 1 - i]}]{row}[/]" for i, row in enumerate(rows)]

    def _core_grid(self, per_core: list[float], width: int) -> list[str]:
        """Per-core meters, in as many columns as fit.

        btop lays cores out in columns and so does this; a 64-core
        machine in one column is a dashboard nobody can read.
        """
        if not per_core:
            return []
        cell = 20
        columns = max(1, min(4, width // cell))
        rows: list[str] = []
        ramp = self.theme.ramp("cpu", 8)
        per_row = -(-len(per_core) // columns)
        for row in range(per_row):
            parts = []
            for column in range(columns):
                index = column * per_row + row
                if index >= len(per_core):
                    continue
                value = per_core[index] or 0.0
                parts.append(
                    f"[{self.theme['inactive_fg']}]{index:>3}[/] "
                    f"{meter(value / 100.0, 8, ramp, empty=self.theme['meter_bg'])} "
                    f"[{self.theme['main_fg']}]{value:3.0f}%[/]"
                )
            rows.append("  ".join(parts))
        return rows

    def render(self, frame=None, width: int | None = None) -> str:
        """One whole screen as Rich markup.

        Returned as a string rather than printed so it can be diffed in a
        test, which is the only way a TUI's layout gets checked at all.
        """
        frame = frame if frame is not None else self.latest_frame()
        width = max(40, width or self.width or 100)
        theme = self.theme
        title = theme["title"]
        inner = width - 4          # what fits between "│ " and " │"
        graph_w = inner
        out: list[str] = []

        # -- cpu ---------------------------------------------------------
        out.append(box_top("cpu", width, line=theme["cpu_box"], accent=title,
                           number="1"))
        cpu = frame.cpu_percent or 0.0
        bar = max(8, inner - 22)
        out.append(self._row(
            f"[{theme['hi_fg']}]CPU[/] "
            f"{meter(cpu / 100.0, bar, theme.ramp('cpu', bar), empty=theme['meter_bg'])} "
            f"[{theme['main_fg']}]{cpu:5.1f}%[/] "
            f"[{theme['graph_text']}]{len(frame.cpu_per_core) or '?'}c[/]",
            width,
        ))
        for row in self._graph_rows(
            [v / 100.0 for v in frame.cpu_history], graph_w, 3, "cpu"
        ):
            out.append(self._row(row, width))
        for row in self._core_grid(frame.cpu_per_core, inner)[:4]:
            out.append(self._row(row, width))
        out.append(box_bottom(width, line=theme["cpu_box"]))

        # -- mem ---------------------------------------------------------
        out.append(box_top("mem", width, line=theme["mem_box"], accent=title,
                           number="2"))
        memory = frame.memory or {}
        ram = frame.ram_percent or 0.0
        bar = max(8, inner - 32)
        out.append(self._row(
            f"[{theme['hi_fg']}]RAM[/] "
            f"{meter(ram / 100.0, bar, theme.ramp('used', bar), empty=theme['meter_bg'])} "
            f"[{theme['main_fg']}]{ram:5.1f}%[/] "
            f"[{theme['graph_text']}]{_fmt_bytes(memory.get('used_bytes'))}/"
            f"{_fmt_bytes(memory.get('total_bytes'))}[/]",
            width,
        ))
        for label, key, prefix in (
            ("available", "available_bytes", "available"),
            ("cached", "cached_bytes", "free"),
        ):
            value = memory.get(key)
            total = memory.get("total_bytes") or 0
            fraction = (value / total) if (value and total) else 0.0
            out.append(self._row(
                f"[{theme['inactive_fg']}]{label:>9}[/] "
                f"{meter(fraction, bar - 6, theme.ramp(prefix, bar - 6), empty=theme['meter_bg'])} "
                f"[{theme['main_fg']}]{_fmt_bytes(value)}[/]",
                width,
            ))
        out.append(box_bottom(width, line=theme["mem_box"]))

        # -- gpu ---------------------------------------------------------
        out.append(box_top("gpu", width, line=theme["net_box"], accent=title,
                           number="3"))
        if frame.gpu_util_percent is None and not frame.gpu_name:
            out.append(self._row(
                f"[{theme['inactive_fg']}]no nvidia-smi here — nothing rather "
                f"than zeroes, which read as an idle GPU[/]",
                width,
            ))
        else:
            util = frame.gpu_util_percent or 0.0
            bar = max(8, inner - 32)
            out.append(self._row(
                f"[{theme['hi_fg']}]GPU[/] "
                f"{meter(util / 100.0, bar, theme.ramp('cpu', bar), empty=theme['meter_bg'])} "
                f"[{theme['main_fg']}]{util:5.1f}%[/] "
                f"[{theme['graph_text']}]{(frame.gpu_name or '')[:16]}[/]",
                width,
            ))
            used, total = frame.gpu_mem_used_mib, frame.gpu_mem_total_mib
            fraction = (used / total) if (used and total) else 0.0
            out.append(self._row(
                f"[{theme['inactive_fg']}]     vram[/] "
                f"{meter(fraction, bar - 6, theme.ramp('used', bar - 6), empty=theme['meter_bg'])} "
                f"[{theme['main_fg']}]{used or 0}/{total or 0} MiB[/]",
                width,
            ))
            if frame.gpu_temp_c is not None:
                temp = frame.gpu_temp_c
                out.append(self._row(
                    f"[{theme['inactive_fg']}]     temp[/] "
                    f"{meter(min(temp, 100) / 100.0, bar - 6, theme.ramp('temp', bar - 6), empty=theme['meter_bg'])} "
                    f"[{theme['main_fg']}]{temp:.0f}°C[/] "
                    f"[{theme['graph_text']}]{frame.gpu_power_w or 0:.0f}/"
                    f"{frame.gpu_power_limit_w or 0:.0f}W[/]",
                    width,
                ))
            for row in self._graph_rows(
                [v / 100.0 for v in frame.gpu_util_history], graph_w, 2, "cpu"
            ):
                out.append(self._row(row, width))
        out.append(box_bottom(width, line=theme["net_box"]))

        # -- training ----------------------------------------------------
        out.append(box_top("training", width, line=theme["proc_box"],
                           accent=title, number="4"))
        if not frame.has_training_data:
            out.append(self._row(
                f"[{theme['inactive_fg']}]no training log found — pass --log, "
                f"or start a run[/]",
                width,
            ))
        else:
            bar = max(8, inner - 26)
            out.append(self._row(
                f"[{theme['hi_fg']}]step[/] "
                f"{meter(frame.progress, bar, theme.ramp('free', bar), empty=theme['meter_bg'])} "
                f"[{theme['main_fg']}]{frame.step}/{frame.total_steps or '?'}[/]",
                width,
            ))
            loss = frame.loss if frame.loss is not None else float("nan")
            out.append(self._row(
                f"[{theme['inactive_fg']}]loss[/] "
                f"[{theme['main_fg']}]{loss:.4f}[/]  "
                f"[{theme['inactive_fg']}]lr[/] "
                f"[{theme['main_fg']}]{frame.lr or 0:.2e}[/]  "
                f"[{theme['inactive_fg']}]tput[/] "
                f"[{theme['main_fg']}]{frame.throughput or 0:.2f}/s[/]  "
                f"[{theme['inactive_fg']}]eta[/] "
                f"[{theme['main_fg']}]{_fmt_duration(frame.eta_seconds)}[/]",
                width,
            ))
            if frame.recent_losses:
                span = max(frame.recent_losses) - min(frame.recent_losses) or 1.0
                floor = min(frame.recent_losses)
                normalised = [(v - floor) / span for v in frame.recent_losses]
                for row in self._graph_rows(normalised, graph_w, 3, "free"):
                    out.append(self._row(row, width))
        out.append(box_bottom(width, line=theme["proc_box"]))

        # -- processes ---------------------------------------------------
        if self.show_processes:
            out.append(box_top("proc", width, line=theme["proc_box"],
                               accent=title, number="5"))
            out.append(self._row(
                f"[{theme['title']}]{'pid':>7} {'user':<10} {'cpu%':>6} "
                f"{'mem%':>6}  command[/]",
                width,
            ))
            for process in self.source._get_active_processes():  # noqa: SLF001
                command = str(process["cmd"])[:max(0, inner - 34)]
                out.append(self._row(
                    f"[{theme['main_fg']}]{process['pid']:>7}[/] "
                    f"[{theme['inactive_fg']}]{str(process['user'])[:10]:<10}[/] "
                    f"[{theme['hi_fg']}]{process['cpu']:>6.1f}[/] "
                    f"[{theme['proc_misc']}]{process['mem']:>6.1f}[/]  "
                    f"[{theme['graph_text']}]{command}[/]",
                    width,
                ))
            out.append(box_bottom(width, line=theme["proc_box"]))

        out.append(
            f"[{theme['inactive_fg']}]tvtoppro[/] "
            f"[{theme['graph_text']}]theme {theme.name} · "
            f"up {_fmt_duration(frame.elapsed_seconds)} · ctrl-c to quit[/]"
        )
        return "\n".join(out)

    def run(self) -> None:
        """Draw until interrupted."""
        from rich.console import Console
        from rich.live import Live
        from rich.text import Text

        console = Console(force_terminal=True, width=self.width)
        try:
            with Live(console=console, refresh_per_second=max(1, int(1 / self.refresh_seconds)),
                      screen=True) as live:
                import time

                while True:
                    markup = self.render(width=self.width or console.width)
                    live.update(Text.from_markup(markup))
                    time.sleep(self.refresh_seconds)
        except KeyboardInterrupt:
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="tvtoppro",
        description=(
            "tvtop++'s stats, presented like btop++, with themes. "
            "Not built on cctvtop."
        ),
    )
    parser.add_argument("--log", default=None,
                        help="Training log to tail. Autodetected when omitted.")
    parser.add_argument("--theme", default=None,
                        help="Built-in name, or a path to a btop .theme or JSON file.")
    parser.add_argument("--list-themes", action="store_true")
    parser.add_argument("--dump-theme", action="store_true",
                        help="Print the active theme as a btop .theme file.")
    parser.add_argument("--refresh", type=float, default=1.0,
                        help="Seconds between frames.")
    parser.add_argument("--width", type=int, default=None)
    parser.add_argument("--no-processes", dest="processes",
                        action="store_false", default=True)
    parser.add_argument("--once", action="store_true",
                        help="Draw one frame and exit. For scripts and screenshots.")
    parser.add_argument("--json", dest="as_json", action="store_true",
                        help="With --once, emit the frame's numbers instead.")
    args = parser.parse_args(argv)

    if args.list_themes:
        for name, theme in sorted(THEMES.items()):
            print(f"  {name:14} {theme['cpu_start']} -> {theme['cpu_mid']} "
                  f"-> {theme['cpu_end']}")
        print()
        print("  Any btop .theme file works too: --theme ~/.config/btop/themes/x.theme")
        return 0

    try:
        theme = load_theme(args.theme)
    except (ValueError, OSError) as exc:
        print(f"tvtoppro: {exc}", file=__import__("sys").stderr)
        return 2

    if args.dump_theme:
        print(theme.to_btop(), end="")
        return 0

    from .tv import _autodetect_log

    log = Path(args.log) if args.log else _autodetect_log()
    dashboard = TvTopPro(
        log_path=log, refresh_seconds=args.refresh, theme=theme,
        width=args.width, show_processes=args.processes,
    )

    if args.once:
        frame = dashboard.latest_frame()
        if args.as_json:
            from dataclasses import asdict

            print(json.dumps(asdict(frame), indent=2, default=str))
            return 0
        from rich.console import Console
        from rich.text import Text

        console = Console(width=args.width)
        console.print(Text.from_markup(
            dashboard.render(frame, width=args.width or console.width)
        ))
        return 0

    dashboard.run()
    return 0


def cli_main() -> None:
    """Console-script entry point.

    Without the ``__main__`` guard below, ``python -m`` on this module
    imports it, runs nothing and exits 0 — which looks exactly like a
    dashboard that drew an empty screen.
    """
    raise SystemExit(main())


if __name__ == "__main__":
    cli_main()
