"""Python wrapper for the C++ cctvtop dashboard."""
from __future__ import annotations

import sys
from pathlib import Path


def cli_main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])

    if "--help" in args or "-h" in args:
        print(
            "usage: cctvtop [--help]\n"
            "A C++-accelerated training dashboard. Searches the current\n"
            "directory (recursively) for the most recently modified *.log\n"
            "file and renders a live view of it.\n"
            "\n"
            "Requires the optional cctvtop_ext C++ extension, which is not\n"
            "built by default. Install it with:\n"
            "  pip install -e . (with BUILD_CCTVTOP=1 set), or\n"
            "  python setup.py build_ext --inplace"
        )
        return

    try:
        from hypernix import cctvtop_ext
    except ImportError:
        print("cctvtop_ext C++ module not found. Did you compile the package?")
        print("Run `pip install -e .` or `python setup.py build_ext --inplace`")
        sys.exit(1)
        
    # Find the most recently modified .log file in the current directory or subdirectories
    cwd = Path.cwd()
    try:
        from hypernix.spinner import Spinner
        with Spinner("Searching for .log files...", style="dots"):
            logs = list(cwd.glob("**/*.log"))
    except Exception:
        logs = list(cwd.glob("**/*.log"))
    if not logs:
        print(f"No .log files found in {cwd}")
        sys.exit(1)
        
    # Sort by modification time, newest first
    logs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    latest_log = logs[0]
    
    print(f"Starting cctvtop for {latest_log} ...")
    
    # Run the C++ dashboard
    try:
        cctvtop_ext.run_dashboard(str(latest_log))
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    cli_main()
