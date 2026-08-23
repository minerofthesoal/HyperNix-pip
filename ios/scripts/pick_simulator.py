#!/usr/bin/env python3
"""Print the UDID of an available iPhone simulator, newest runtime first.

Naming a simulator ("iPhone 15 Pro") is the single most common reason an
iOS workflow starts failing without anyone changing it: the device list
changes with every runner image. Asking ``simctl`` which devices exist
and taking one is stable across images.

Prints nothing and exits 1 when there is no usable simulator, so the
caller can decide whether that is a skip or a failure.
"""
from __future__ import annotations

import json
import subprocess
import sys


def main() -> int:
    try:
        proc = subprocess.run(
            ["xcrun", "simctl", "list", "devices", "available", "-j"],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"simctl failed: {exc}", file=sys.stderr)
        return 1
    if proc.returncode != 0:
        print(proc.stderr.strip(), file=sys.stderr)
        return 1

    try:
        devices = json.loads(proc.stdout).get("devices", {})
    except json.JSONDecodeError:
        print("simctl returned non-JSON", file=sys.stderr)
        return 1

    # Runtime keys look like
    # "com.apple.CoreSimulator.SimRuntime.iOS-18-2"; sorting them in
    # reverse puts the newest iOS first, which is the one the app should
    # be tested against.
    for runtime in sorted((r for r in devices if "iOS" in r), reverse=True):
        for device in devices[runtime]:
            if device.get("isAvailable") and "iPhone" in str(device.get("name", "")):
                print(device["udid"])
                return 0
    print("no available iPhone simulator", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
