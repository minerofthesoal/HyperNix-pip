"""hyped_pro: Python entry point and launcher for hyped+ (hyped-pro) Node.js TUI.

Launches ``src/hypernix/hyped_pro.js`` via Node.js if present, or falls back to
the Python TUI engine in ``hypernix.hyped``.

NOTE: hyped_pro.js is a *compiled build artifact*, generated from
hyped_pro.ts via `npm run build` (tsc). Edit hyped_pro.ts, not hyped_pro.js —
changes made directly to the .js will be overwritten on the next build.

Debug logging: set HYPED_PRO_DEBUG=1 (or pass --debug) to print launcher
diagnostics (node/js path resolution) to stderr before handing off to Node.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _debug_enabled(argv: list[str]) -> bool:
    return bool(os.environ.get("HYPED_PRO_DEBUG")) or "--debug" in argv


def _debug(msg: str) -> None:
    print(f"[hyped-pro launcher] DEBUG: {msg}", file=sys.stderr)


def cli_main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    debug = _debug_enabled(argv)
    # --debug is consumed here (it's a launcher flag, not a hyped_pro.ts flag)
    # so it doesn't get forwarded and rejected as an unknown argument.
    forward_argv = [a for a in argv if a != "--debug"]

    js_path = Path(__file__).parent / "hyped_pro.js"
    node_bin = shutil.which("node")

    if debug:
        _debug(f"node binary: {node_bin or 'NOT FOUND on PATH'}")
        _debug(f"hyped_pro.js: {js_path} (exists={js_path.exists()})")
        _debug(f"HYPED_PRO_PYTHON={os.environ.get('HYPED_PRO_PYTHON', sys.executable)} "
               f"(used by hyped_pro.js to spawn the bridge/GUI)")

    if node_bin and js_path.exists():
        cmd = [node_bin, str(js_path)] + forward_argv
        try:
            return subprocess.call(cmd)
        except Exception as exc:  # noqa: BLE001
            print(f"[hyped-pro launcher] WARNING HPL-001: node launcher failed ({exc}); "
                  f"falling back to the Python TUI (hypernix.hyped).", file=sys.stderr)
    elif debug:
        reason = "node not found on PATH" if not node_bin else f"{js_path} missing (run `npm run build` in src/hypernix)"
        _debug(f"skipping Node TUI: {reason}")

    from .hyped import cli_main as python_hyped_main
    return python_hyped_main(forward_argv)


if __name__ == "__main__":
    sys.exit(cli_main())
