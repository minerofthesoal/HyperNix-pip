#!/usr/bin/env python3
"""
Apply-script: fix Windows CI failures in tests/test_kitchen_v045.py

Root cause
----------
test_cli_brew_runs_from_json and test_cli_brew_rejects_bad_override both
spawn `python -m hypernix.cli brew ...` in a subprocess with a hand-rolled,
POSIX-only environment:

    env = {
        "PYTHONPATH": ...,
        "HYPERNIX_AUTO_INSTALL": "0",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": str(Path.home()),
    }

On Windows this strips out SystemRoot/windir. Winsock needs those to load
its service-provider table, so the *subprocess* dies with

    OSError: [WinError 10106] The requested service provider could not be
    loaded or initialized

as soon as it hits `import asyncio` (pulled in transitively by
`torch -> unittest.mock -> asyncio`), long before hypernix.cli's own code
ever runs. It happens identically on every Windows runner (3.11/3.12/3.14)
and is unrelated to hypernix's own logic.

Fix
---
Replace the two copy-pasted env dicts with a shared `_cli_subprocess_env()`
helper that stays minimal/hermetic on POSIX (unchanged behavior there) but,
on win32, carries over the handful of OS-level variables (SystemRoot,
windir, TEMP/TMP, USERPROFILE, COMSPEC, ...) needed for the interpreter and
its C-extension dependencies to boot, and points PATH at the interpreter's
own directory + System32 instead of a Linux path.

Usage
-----
    python fix_windows_cli_subprocess_env.py /path/to/HyperNix-pip

(defaults to the current directory if no path is given). Safe to re-run;
it's a no-op if the file has already been patched.
"""
from __future__ import annotations

import sys
from pathlib import Path

TARGET_REL = Path("tests") / "test_kitchen_v045.py"

OLD_IMPORTS = '''import json
import subprocess
import sys
from pathlib import Path

import pytest'''

NEW_IMPORTS = '''import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _cli_subprocess_env() -> dict[str, str]:
    """Near-hermetic environment for `hypernix.cli` subprocess tests.

    Deliberately minimal so these tests exercise the CLI's own env
    handling (e.g. HYPERNIX_AUTO_INSTALL=0) rather than whatever happens
    to be set in the surrounding shell/CI runner.

    On Windows, though, a handful of OS-level variables aren't optional:
    without SystemRoot (and friends) Winsock can't load its service
    provider table, so even `import asyncio` -- pulled in transitively by
    `torch` -> `unittest.mock` -> `asyncio` -- fails with
    "WinError 10106: The requested service provider could not be loaded
    or initialized" before any hypernix code runs. A hardcoded POSIX PATH
    also leaves Windows unable to resolve system DLLs. Carry over just
    enough of the real environment to let the interpreter and its
    dependencies boot on whatever platform we're on.
    """
    env = {
        "PYTHONPATH": str(Path(__file__).resolve().parent.parent / "src"),
        "HYPERNIX_AUTO_INSTALL": "0",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": str(Path.home()),
    }
    if sys.platform == "win32":
        for key in (
            "SystemRoot", "windir", "SystemDrive", "COMSPEC",
            "TEMP", "TMP", "USERPROFILE", "PATHEXT",
            "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
        ):
            if key in os.environ:
                env[key] = os.environ[key]
        system_root = env.get("SystemRoot", r"C:\\Windows")
        env["PATH"] = os.pathsep.join([
            str(Path(sys.executable).parent),
            str(Path(sys.executable).parent / "Scripts"),
            f"{system_root}\\\\System32",
            system_root,
            f"{system_root}\\\\System32\\\\Wbem",
        ])
        env.setdefault("USERPROFILE", str(Path.home()))
    return env'''

OLD_BLOCK_1 = '''    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(json.dumps(recipe), encoding="utf-8")

    env = {
        "PYTHONPATH": str(Path(__file__).resolve().parent.parent / "src"),
        "HYPERNIX_AUTO_INSTALL": "0",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": str(Path.home()),
    }
    cp = subprocess.run(
        [sys.executable, "-m", "hypernix.cli", "brew", str(recipe_path)],'''

NEW_BLOCK_1 = '''    recipe_path = tmp_path / "recipe.json"
    recipe_path.write_text(json.dumps(recipe), encoding="utf-8")

    env = _cli_subprocess_env()
    cp = subprocess.run(
        [sys.executable, "-m", "hypernix.cli", "brew", str(recipe_path)],'''

OLD_BLOCK_2 = '''    rp = tmp_path / "r.json"
    rp.write_text(json.dumps(recipe), encoding="utf-8")
    env = {
        "PYTHONPATH": str(Path(__file__).resolve().parent.parent / "src"),
        "HYPERNIX_AUTO_INSTALL": "0",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": str(Path.home()),
    }
    cp = subprocess.run(
        [sys.executable, "-m", "hypernix.cli", "brew", str(rp), "--set", "bad_format"],'''

NEW_BLOCK_2 = '''    rp = tmp_path / "r.json"
    rp.write_text(json.dumps(recipe), encoding="utf-8")
    env = _cli_subprocess_env()
    cp = subprocess.run(
        [sys.executable, "-m", "hypernix.cli", "brew", str(rp), "--set", "bad_format"],'''


def apply(repo_root: Path) -> None:
    target = repo_root / TARGET_REL
    if not target.is_file():
        sys.exit(f"error: {target} not found (pass the repo root as an argument)")

    text = target.read_text(encoding="utf-8")

    if "_cli_subprocess_env" in text:
        print(f"already patched: {target}")
        return

    missing = [
        name for name, needle in (
            ("imports block", OLD_IMPORTS),
            ("first env block (test_cli_brew_runs_from_json)", OLD_BLOCK_1),
            ("second env block (test_cli_brew_rejects_bad_override)", OLD_BLOCK_2),
        )
        if needle not in text
    ]
    if missing:
        sys.exit(
            "error: file doesn't match expected content, refusing to guess.\n"
            "Couldn't find: " + ", ".join(missing) + "\n"
            "The file may have changed since this script was written -- "
            "apply the fix by hand instead."
        )

    text = text.replace(OLD_IMPORTS, NEW_IMPORTS, 1)
    text = text.replace(OLD_BLOCK_1, NEW_BLOCK_1, 1)
    text = text.replace(OLD_BLOCK_2, NEW_BLOCK_2, 1)

    target.write_text(text, encoding="utf-8")
    print(f"patched: {target}")


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    apply(root.resolve())
