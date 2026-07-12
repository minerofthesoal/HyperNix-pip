"""Python wrapper for the C++ cctvtop dashboard (upgraded)."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text

from .tv import LogTail, _autodetect_log
from .tvtop_plus_plus import SPINNERS, Frame, TVTopPlusPlus


def _resolve_cctvtop_log(explicit: Path | str | None = None) -> Path | None:
    """Resolve the training log cctvtop should tail.

    No longer hardcoded to a single path -- this checks, in order:

    1. An explicit path (``--log`` flag / constructor argument).
    2. ``~/checkpoints/train.log`` -- cctvtop's preferred, prioritized
       convention (matches tvtop's autodetect priority).
    3. ``./checkpoints/train.log`` -- the legacy cwd-relative location
       cctvtop used to hardcode unconditionally.
    4. Whatever :func:`hypernix.tv._autodetect_log` finds by scanning
       the current directory for a training-shaped log.

    Returns ``None`` if nothing is found anywhere.
    """
    if explicit is not None:
        return Path(explicit)

    home_default = Path.home() / "checkpoints" / "train.log"
    if home_default.exists():
        return home_default

    cwd_default = Path.cwd() / "checkpoints" / "train.log"
    if cwd_default.exists():
        return cwd_default

    return _autodetect_log()


def ensure_vnc() -> dict[str, str]:
    """Ensure a VNC server is running and return its info."""
    try:
        # Check if x11vnc is running
        res = subprocess.run(["pgrep", "-x", "x11vnc"], capture_output=True, text=True)
        if res.returncode != 0:
            # Not running, try to start it
            try:
                subprocess.Popen(["x11vnc", "-display", ":0", "-nopw", "-bg", "-forever", "-q"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(0.5)
            except FileNotFoundError:
                return {"status": "Not Installed (x11vnc missing)", "ip": "Unknown"}
                
        # Get tailscale IP
        ip_res = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True)
        ip = ip_res.stdout.strip() if ip_res.returncode == 0 else "localhost"
        
        return {"status": "Running", "ip": f"{ip}:5900"}
    except Exception as e:
        return {"status": f"Error: {e}", "ip": "Unknown"}


class CCTVTop(TVTopPlusPlus):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # cctvtop no longer forces a hardcoded log path: if the caller
        # already supplied one (e.g. via cli_main's --log handling) it is
        # respected as-is; otherwise it's resolved through the same
        # priority chain as tvtop (~/checkpoints/train.log first).
        if self.log_path is None:
            resolved = _resolve_cctvtop_log(None)
            if resolved is not None:
                self.log_path = resolved
                self.log_tail = LogTail(Path(self.log_path), history_size=8)
        self.vnc_info = ensure_vnc()

    def _init_layout(self) -> Layout:
        layout = super()._init_layout()
        # Replace the right column to include VNC
        layout["right"].split_column(
            Layout(name="hardware", ratio=4),
            Layout(name="gpu", ratio=2),
            Layout(name="vnc", ratio=1)
        )
        return layout

    def _update_layout(self, f: Frame, console: Console, layout: Layout) -> None:
        # Let the parent update training, process, hardware, gpu, loss, log
        super()._update_layout(f, console, layout)
        
        # Override header text for CCTVTop
        spinner_char = SPINNERS[self.tick % len(SPINNERS)] if not self.ascii_only else "*"
        title_text = Text.assemble(
            (" ", "default"),
            (spinner_char, "bright_cyan"),
            ("  ✦ HYPERNIX CCTVTop (VNC+PRO) ✦  ", "bold bright_red"),
            (time.strftime(" %Y-%m-%d %H:%M:%S "), "dim"),
        )
        layout["header"].update(Panel(title_text, style="bold red", padding=(0, 2)))
        
        # Add VNC panel
        vnc_text = Text()
        if self.vnc_info["status"] == "Running":
            vnc_text.append("VNC Server: ", style="bold white")
            vnc_text.append("RUNNING\n", style="bold green")
            vnc_text.append(f"Connect to: {self.vnc_info['ip']}", style="cyan")
        else:
            vnc_text.append("VNC Server: ", style="bold white")
            vnc_text.append(f"{self.vnc_info['status']}\n", style="bold red")
            vnc_text.append("(Please install x11vnc)", style="dim")
            
        layout["vnc"].update(Panel(vnc_text, title="Remote Desktop", border_style="blue"))


def cli_main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])

    if "--help" in args or "-h" in args:
        print(
            "usage: hnx cctvtop [--log path] [--help]\n\n"
            "A pure-Python training dashboard with hardware metrics and VNC\n"
            "capabilities. Prioritizes ~/checkpoints/train.log, then falls back to\n"
            "./checkpoints/train.log, then auto-detects a training-shaped log under\n"
            "the current directory. Pass --log <path> to point at something else."
        )
        return 0

    explicit_log: Path | None = None
    if "--log" in args:
        i = args.index("--log")
        if i + 1 < len(args):
            explicit_log = Path(args[i + 1])
            del args[i : i + 2]

    log_file = _resolve_cctvtop_log(explicit_log)
    if log_file is None or not log_file.exists():
        home_default = Path.home() / "checkpoints" / "train.log"
        cwd_default = Path.cwd() / "checkpoints" / "train.log"
        print(
            f"Error: no training log found.\n"
            f"Looked for: {explicit_log or '(no --log given)'}, {home_default}, "
            f"{cwd_default}, and an auto-detected *.log under {Path.cwd()}.\n"
            "Pass --log <path> for an explicit location.",
            file=sys.stderr,
        )
        return 1

    app = CCTVTop(log_path=log_file, refresh_seconds=1.0)
    app.run()
    return 0

if __name__ == "__main__":
    sys.exit(cli_main())
