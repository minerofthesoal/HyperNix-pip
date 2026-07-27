"""hyped_pro: Python entry point and launcher for hyped+ (hyped-pro) Node.js TUI.

Launches ``src/hypernix/hyped_pro.js`` via Node.js if present, or falls back to
the Python TUI engine in ``hypernix.hyped``.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def cli_main(argv: list[str] | None = None) -> int:
    js_path = Path(__file__).parent / "hyped_pro.js"
    node_bin = shutil.which("node")
#DEBUGGER 
    print(f"DEBUG:CHECKING FOR NODE.JS... found at: {node_bin}", file=sys.stderr)
    print(f"DEBUG: CHECKING FOR JS FILE at: {js_path}... exists {js_path.exists()}", file=sys.stderr)
    #PLEASE FOR the love of god work collen_3 cant spell sorry anyway end of debugger
    if node_bin and js_path.exists():
        cmd = [node_bin, str(js_path)] + (argv if argv is not None else sys.argv[1:])
        try:
            return subprocess.call(cmd)
        except Exception as exc:  # noqa: BLE001
            print(f"[hyped+] Warning: node launcher error ({exc}); falling back to python hyped...", file=sys.stderr)

    from .hyped import cli_main as python_hyped_main
    return python_hyped_main(argv)


if __name__ == "__main__":
    sys.exit(cli_main())
