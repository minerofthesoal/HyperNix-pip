#!/usr/bin/env python3
"""Print the marketing version to stamp into the HyperLink build.

The app's version tracks the T1 API's own (``1.0.26.8.0.1``) rather than
having a life of its own: the server reports that string in ``/status``
and it is what a support question will quote, so an app that calls
itself something else makes the two impossible to line up.

Reads ``src/hypernix/t1api/version.py`` rather than importing it, so this
runs on a CI machine with nothing installed. Falls back to a sane
constant rather than failing the build — a version string is not worth
a red run.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

FALLBACK = "1.0.26"
SOURCE = Path(__file__).resolve().parents[2] / "src" / "hypernix" / "t1api" / "version.py"
PATTERN = re.compile(
    r"T1_VERSION\s*=\s*T1Version\(\s*api=(\d+),\s*major=(\d+),\s*year=(\d+),"
    r"\s*month=(\d+),\s*feature=(\d+),\s*fix=(\d+)\s*\)"
)


def main() -> int:
    try:
        text = SOURCE.read_text(encoding="utf-8")
    except OSError:
        print(FALLBACK)
        return 0
    match = PATTERN.search(text)
    if not match:
        print(FALLBACK)
        return 0
    api, major, year, month, feature, fix = (int(g) for g in match.groups())
    # The short spelling, same as the wire form: two-digit year.
    print(f"{api}.{major}.{year % 100}.{month}.{feature}.{fix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
