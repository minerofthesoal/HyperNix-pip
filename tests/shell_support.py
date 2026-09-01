"""Is there a bash here that actually runs a script?

``shutil.which("bash")`` is not the question. On a GitHub Windows runner
it finds ``C:\\Windows\\System32\\bash.exe`` — the WSL launcher stub,
which exists on every Windows install, exits non-zero, and prints
UTF-16LE text saying no distribution is installed. Tests gated on
``which`` therefore ran there and failed on output that was never a
shell's.

So this asks the only question that matters: does running a trivial
script through it produce the script's output?
"""
from __future__ import annotations

import shutil
import subprocess

_MARKER = "hypernix-bash-ok"


def _probe() -> str | None:
    path = shutil.which("bash")
    if path is None:
        return None
    try:
        result = subprocess.run(
            [path, "-c", f"echo {_MARKER}"],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    # Bytes, not text: the WSL stub answers in UTF-16LE, and decoding that
    # as UTF-8 either raises or produces NUL-separated characters that no
    # substring check would match anyway.
    if result.returncode != 0 or _MARKER.encode() not in result.stdout:
        return None
    return path


#: The bash to run scripts with, or None when there is no usable one.
BASH: str | None = _probe()

#: Reason string for a skip marker, so every gated module says the same thing.
NO_BASH_REASON = "no working bash on this machine (a WSL stub does not count)"
