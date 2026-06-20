#!/usr/bin/env python3
"""HyperNix multi-version launcher.

This launcher checks for hypernix installation across Python versions
in priority order: 3.12 → 3.13 → 3.14.

If hypernix is installed on 3.12, it runs there. Otherwise, it falls back
to the first version (3.13 or 3.14) where hypernix is installed.

This ensures consistent behavior regardless of which Python version was
used to install the package, while preferring 3.12 when available.
"""
from __future__ import annotations

import subprocess
import sys
from typing import NamedTuple


class PythonVersion(NamedTuple):
    """Represents a Python version to check."""
    major: int
    minor: int
    
    @property
    def exe_name(self) -> str:
        return f"python{self.major}.{self.minor}"
    
    @property
    def version_tuple(self) -> tuple[int, int]:
        return (self.major, self.minor)


# Priority order: prefer 3.12, then 3.13, then 3.14
VERSION_PRIORITY = [
    PythonVersion(3, 12),
    PythonVersion(3, 13),
    PythonVersion(3, 14),
]


def check_hypernix_installed(py_exe: str) -> bool:
    """Check if hypernix is installed for the given Python executable."""
    try:
        result = subprocess.run(
            [py_exe, "-c", "import hypernix; print(hypernix.__version__)"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def find_best_python() -> str | None:
    """Find the best Python executable with hypernix installed.
    
    Returns:
        Path to Python executable, or None if no suitable version found.
    """
    for version in VERSION_PRIORITY:
        # Try the versioned executable name first
        if check_hypernix_installed(version.exe_name):
            return version.exe_name
        
        # Also try 'pythonX.Y' format on Windows
        if sys.platform == "win32":
            win_exe = f"python{version.major}{version.minor}"
            if check_hypernix_installed(win_exe):
                return win_exe
    
    # Fallback: check if current Python has hypernix
    try:
        import hypernix  # noqa: F401
        return sys.executable
    except ImportError:
        pass
    
    return None


def run_with_selected_python(args: list[str]) -> int:
    """Run hypernix.cli:main with the selected Python version."""
    selected = find_best_python()
    
    if selected is None:
        # No Python version with hypernix found, fall back to current
        from hypernix.cli import main
        return main(args)
    
    # Re-invoke with the selected Python version
    cmd = [selected, "-m", "hypernix"] + args
    try:
        result = subprocess.run(cmd, check=False)
        return result.returncode
    except FileNotFoundError:
        # Selected executable not found, fall back to current
        from hypernix.cli import main
        return main(args)


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the multi-version launcher."""
    import os
    
    raw = list(sys.argv[1:] if argv is None else argv)
    
    # Check if we should use the launcher logic
    # Skip if HYPERNOX_NO_VERSION_CHECK is set (for development)
    if os.environ.get("HYPERNIX_NO_VERSION_CHECK"):
        from hypernix.cli import main as cli_main
        return cli_main(raw)
    
    # If running as module directly, just use current Python
    if "__main__.py" in sys.argv[0]:
        from hypernix.cli import main as cli_main
        return cli_main(raw)
    
    # For console script entry points, check and potentially re-exec
    return run_with_selected_python(raw)


if __name__ == "__main__":
    raise SystemExit(main())
