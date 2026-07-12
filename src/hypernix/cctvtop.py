"""Python wrapper for the C++ cctvtop dashboard (upgraded)."""
from __future__ import annotations

import sys
import time
import subprocess
from pathlib import Path

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from .tvtop_plus_plus import TVTopPlusPlus, Frame, SPINNERS

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
        # cctvtop forces hardcoded log path
        self.log_path = Path.cwd() / "checkpoints" / "train.log"
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
            "usage: hnx cctvtop [--help]\n\n"
            "A pure-Python training dashboard that hardcodes its log path to\n"
            "./checkpoints/train.log and provides hardware metrics and VNC capabilities."
        )
        return 0

    log_file = Path.cwd() / "checkpoints" / "train.log"
    if not log_file.exists():
        print(f"Error: Hardcoded log file '{log_file}' does not exist.")
        print("cctvtop is hardcoded to only log from ./checkpoints/train.log")
        return 1
        
    app = CCTVTop(log_path=log_file, refresh_seconds=1.0)
    app.run()
    return 0

if __name__ == "__main__":
    sys.exit(cli_main())
