"""Python wrapper for the C++ cctvtop dashboard."""
import sys
from pathlib import Path


def cli_main() -> None:
    try:
        from hypernix import cctvtop_ext
    except ImportError:
        print("cctvtop_ext C++ module not found. Did you compile the package?")
        print("Run `pip install -e .` or `python setup.py build_ext --inplace`")
        sys.exit(1)
        
    # Find the most recently modified .log file in the current directory or subdirectories
    cwd = Path.cwd()
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
