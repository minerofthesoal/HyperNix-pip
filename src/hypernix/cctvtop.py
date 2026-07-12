"""cctvtop — Python rewrite of the C++ cctvtop dashboard.

This replaces the old cctvtop_ext C++ wrapper with a pure Python rich dashboard
that locks the terminal (using screen=True) and reliably tails the latest .log
file in the current directory tree without scrolling artifacts or duplicate text.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def cli_main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])

    if "--help" in args or "-h" in args:
        print(
            "usage: hnx cctvtop [--help]\n\n"
            "A pure-Python training dashboard (formerly C++).\n"
            "Searches the current directory recursively for the most recently\n"
            "modified *.log file and renders a live, locking 2D view of it."
        )
        return

    try:
        from rich.console import Console
        from rich.layout import Layout
        from rich.live import Live
        from rich.panel import Panel
        from rich.text import Text
    except ImportError:
        print("Error: 'rich' library is required for cctvtop.")
        sys.exit(1)

    cwd = Path.cwd()
    logs = list(cwd.glob("**/*.log"))
    
    # Filter out chromium/chrome logs automatically just like tv.py
    logs = [p for p in logs if "chromium" not in p.name.lower() and "chrome" not in p.name.lower()]

    if not logs:
        print(f"No valid .log files found in {cwd}")
        sys.exit(1)

    # Sort by modification time, newest first
    logs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    latest_log = logs[0]
    
    console = Console()
    
    def read_tail(path: Path, lines: int = 40) -> str:
        """Read the last N lines of a file quickly."""
        try:
            with open(path, 'rb') as f:
                f.seek(0, os.SEEK_END)
                buffer = bytearray()
                pointer_location = f.tell()
                while pointer_location >= 0 and lines > 0:
                    f.seek(pointer_location)
                    pointer_location -= 1
                    char = f.read(1)
                    if char == b'\n':
                        lines -= 1
                    buffer.extend(char)
                return buffer[::-1].decode('utf-8', errors='replace').lstrip()
        except Exception as e:
            return f"Error reading log: {e}"

    # Build static layout structure once
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body")
    )

    header_text = Text()
    header_text.append(" 🎥 CCTVTop ", style="bold white on red")
    header_text.append(f" Tailing: {latest_log.relative_to(cwd) if cwd in latest_log.parents else latest_log}", style="bold cyan")

    layout["header"].update(Panel(header_text, style="white on black"))

    try:
        # screen=True locks the terminal screen
        with Live(layout, console=console, refresh_per_second=4, screen=True):
            while True:
                term_height = console.height
                # leave room for header (3) and panel borders (2)
                tail_lines = max(5, term_height - 5)
                
                content = read_tail(latest_log, lines=tail_lines)
                
                body_panel = Panel(
                    Text(content, style="green"),
                    title="[bold]Live Log Feed[/bold]",
                    border_style="cyan"
                )
                
                layout["body"].update(body_panel)
                time.sleep(0.25)
    except KeyboardInterrupt:
        # Exits cleanly and restores the original terminal screen thanks to screen=True
        pass

if __name__ == "__main__":
    cli_main()
