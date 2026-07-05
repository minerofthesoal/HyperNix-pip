"""spinner — Terminal loading animations for HyperNix CLI.

Provides a lightweight spinner/progress animation that works without
any external dependencies (pure stdlib + ANSI), with a rich fallback
for a richer experience when available.

Usage:
    from hypernix.spinner import Spinner, anime_print

    with Spinner("Loading model..."):
        load_heavy_stuff()

    anime_print("HyperNix", style="banner")
"""
from __future__ import annotations

import sys
import threading
import time

# ANSI helpers
_CSI = "\x1b["
_HIDE = f"{_CSI}?25l"
_SHOW = f"{_CSI}?25h"
_CYAN = f"{_CSI}96m"
_RESET = f"{_CSI}0m"
_GREEN = f"{_CSI}92m"
_YELLOW = f"{_CSI}93m"
_BOLD = f"{_CSI}1m"
_DIM = f"{_CSI}2m"


def _is_tty() -> bool:
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


# ---------------------------------------------------------------------------
# Spinner frames — several beautiful animation styles
# ---------------------------------------------------------------------------

SPINNERS: dict[str, list[str]] = {
    "dots":    ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"],
    "arc":     ["◜", "◠", "◝", "◞", "◡", "◟"],
    "bounce":  ["⠁", "⠂", "⠄", "⠂"],
    "pulse":   ["█", "▓", "▒", "░", "▒", "▓"],
    "bar":     ["[    ]", "[=   ]", "[==  ]", "[=== ]", "[====]", "[ ===]", "[  ==]", "[   =]"],
    "moon":    ["🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘"],
    "clock":   ["🕐", "🕑", "🕒", "🕓", "🕔", "🕕", "🕖", "🕗", "🕘", "🕙", "🕚", "🕛"],
    "fire":    ["🔥", "💥", "✨", "💫", "⚡"],
    "star":    ["✶", "✸", "✹", "✺", "✹", "✷"],
    "line":    ["─", "╲", "│", "╱"],
    "grow":    ["▏", "▎", "▍", "▌", "▋", "▊", "▉", "█", "▉", "▊", "▋", "▌", "▍", "▎"],
    "arrows":  ["←", "↖", "↑", "↗", "→", "↘", "↓", "↙"],
    "matrix":  ["0", "1", "0", "1", "0", "1"],
}

BANNER_FRAMES = [
    "H Y P E R N I X",
    "H·Y·P·E·R·N·I·X",
    "HYPERNIX",
    "⚡HYPERNIX⚡",
    "▓HYPERNIX▓",
    "█HYPERNIX█",
]


# ---------------------------------------------------------------------------
# Spinner context manager
# ---------------------------------------------------------------------------

class Spinner:
    """Thread-based terminal spinner.

    Works with or without rich. Falls back to simple print on non-TTY.

    Example::

        with Spinner("Downloading model") as sp:
            do_work()
            sp.update("Still downloading...")
        # On exit, prints ✓ Done (or ✗ on exception)
    """

    def __init__(
        self,
        text: str = "Loading",
        *,
        style: str = "dots",
        fps: float = 10,
        color: bool = True,
    ) -> None:
        self.text = text
        self._frames = SPINNERS.get(style, SPINNERS["dots"])
        self._interval = 1.0 / max(fps, 1)
        self._color = color and _is_tty()
        self._tty = _is_tty()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._succeeded: bool = True

    def update(self, text: str) -> None:
        with self._lock:
            self.text = text

    def _spin(self) -> None:
        idx = 0
        if self._tty:
            sys.stdout.write(_HIDE)
            sys.stdout.flush()
        try:
            while not self._stop.is_set():
                frame = self._frames[idx % len(self._frames)]
                with self._lock:
                    msg = self.text
                if self._tty:
                    if self._color:
                        line = f"\r{_CYAN}{frame}{_RESET}  {_BOLD}{msg}{_RESET}  "
                    else:
                        line = f"\r{frame}  {msg}  "
                    sys.stdout.write(line)
                    sys.stdout.flush()
                idx += 1
                time.sleep(self._interval)
        finally:
            pass

    def start(self) -> Spinner:
        self._stop.clear()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()
        return self

    def stop(self, succeeded: bool = True) -> None:
        self._succeeded = succeeded
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        if self._tty:
            sys.stdout.write(_SHOW)
            icon = f"{_GREEN}✓{_RESET}" if succeeded else f"\x1b[91m✗{_RESET}"
            sys.stdout.write(f"\r{icon}  {_BOLD}{self.text}{_RESET}  \n")
            sys.stdout.flush()
        else:
            status = "✓" if succeeded else "✗"
            print(f"{status}  {self.text}")

    def __enter__(self) -> Spinner:
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop(succeeded=exc_type is None)
        return False


# ---------------------------------------------------------------------------
# Animated banner / intro print
# ---------------------------------------------------------------------------

def anime_print(
    text: str = "HyperNix",
    *,
    style: str = "banner",
    color: bool = True,
    delay: float = 0.05,
) -> None:
    """Print an animated banner or text effect to the terminal.

    Styles:
      ``banner``  — slide in letter by letter then flash
      ``glitch``  — glitch effect (randomised chars) then settle
      ``typewriter`` — typewriter character reveal
      ``fade``    — fade in using block characters
    """
    if not _is_tty() or not color:
        print(text)
        return

    if style == "typewriter":
        sys.stdout.write(_HIDE)
        sys.stdout.flush()
        try:
            for i in range(1, len(text) + 1):
                sys.stdout.write(f"\r{_BOLD}{_CYAN}{text[:i]}{_RESET}{'▌' if i < len(text) else '  '}")
                sys.stdout.flush()
                time.sleep(delay)
        finally:
            sys.stdout.write(_SHOW + "\n")
            sys.stdout.flush()

    elif style == "glitch":
        import random
        chars = "!@#$%^&*<>?/\\|0123456789"
        sys.stdout.write(_HIDE)
        sys.stdout.flush()
        try:
            for step in range(12):
                glitched = ""
                for i, ch in enumerate(text):
                    if i < (step / 12) * len(text):
                        glitched += ch
                    elif ch == " ":
                        glitched += " "
                    else:
                        glitched += random.choice(chars)
                sys.stdout.write(f"\r{_BOLD}\x1b[95m{glitched}{_RESET}   ")
                sys.stdout.flush()
                time.sleep(delay * 1.5)
            sys.stdout.write(f"\r{_BOLD}{_CYAN}{text}{_RESET}   \n")
            sys.stdout.flush()
        finally:
            sys.stdout.write(_SHOW)
            sys.stdout.flush()

    elif style == "fade":
        blocks = ["░", "▒", "▓", "█"]
        sys.stdout.write(_HIDE)
        sys.stdout.flush()
        try:
            for block in blocks:
                sys.stdout.write(f"\r{_BOLD}{_CYAN}{block * len(text)}{_RESET}")
                sys.stdout.flush()
                time.sleep(delay * 2)
            sys.stdout.write(f"\r{_BOLD}{_CYAN}{text}{_RESET}   \n")
            sys.stdout.flush()
        finally:
            sys.stdout.write(_SHOW)
            sys.stdout.flush()

    else:  # banner (default): slide-in then flash
        sys.stdout.write(_HIDE)
        sys.stdout.flush()
        try:
            padded = " " * len(text) + text
            for i in range(len(text) + 1):
                shown = padded[i:i + len(text)]
                sys.stdout.write(f"\r{_BOLD}{_CYAN}{shown}{_RESET}")
                sys.stdout.flush()
                time.sleep(delay)
            # Flash effect
            for flash_color in ["\x1b[97m", _CYAN, "\x1b[97m", _CYAN]:
                sys.stdout.write(f"\r{_BOLD}{flash_color}{text}{_RESET}")
                sys.stdout.flush()
                time.sleep(delay * 2)
            sys.stdout.write(f"\r{_BOLD}{_CYAN}{text}{_RESET}   \n")
            sys.stdout.flush()
        finally:
            sys.stdout.write(_SHOW)
            sys.stdout.flush()


# ---------------------------------------------------------------------------
# Convenience: print a styled startup header
# ---------------------------------------------------------------------------

def print_startup_header(version: str = "") -> None:
    """Print the HyperNix startup banner with version and animation."""
    if not _is_tty():
        print(f"HyperNix {version}")
        return

    logo = r"""
  ██╗  ██╗██╗   ██╗██████╗ ███████╗██████╗ ███╗   ██╗██╗██╗  ██╗
  ██║  ██║╚██╗ ██╔╝██╔══██╗██╔════╝██╔══██╗████╗  ██║██║╚██╗██╔╝
  ███████║ ╚████╔╝ ██████╔╝█████╗  ██████╔╝██╔██╗ ██║██║ ╚███╔╝ 
  ██╔══██║  ╚██╔╝  ██╔═══╝ ██╔══╝  ██╔══██╗██║╚██╗██║██║ ██╔██╗ 
  ██║  ██║   ██║   ██║     ███████╗██║  ██║██║ ╚████║██║██╔╝ ██╗
  ╚═╝  ╚═╝   ╚═╝   ╚═╝     ╚══════╝╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝╚═╝  ╚═╝
"""

    sys.stdout.write(_HIDE)
    sys.stdout.flush()
    try:
        lines = logo.strip("\n").split("\n")
        for i, line in enumerate(lines):
            # Animate each line sliding in from the left
            for end in range(0, len(line) + 1, 3):
                sys.stdout.write(f"\x1b[{i + 1};1H{_CYAN}{line[:end]}{_RESET}")
                sys.stdout.flush()
                time.sleep(0.003)
            sys.stdout.write(f"\x1b[{i + 1};1H{_CYAN}{line}{_RESET}")
            sys.stdout.flush()

        # Print version below logo
        ver_line = f"  {_DIM}v{version}{_RESET}" if version else ""
        sys.stdout.write(f"\n{ver_line}\n\n")
        sys.stdout.flush()
        time.sleep(0.1)
    finally:
        sys.stdout.write(_SHOW)
        sys.stdout.flush()
