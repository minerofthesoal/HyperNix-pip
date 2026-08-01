"""hyped_pro_bridge — stdio JSON worker used by the Node ``hyped_pro.ts`` TUI.

hyped-pro's TUI (hyped_pro.ts, run under Node) has no Python runtime of its
own, so every operation that needs real inference, a real HuggingFace
download, or the real T1 Gatekeeper — everything in
:mod:`hypernix.hyped_pro_core` — is delegated here over stdio.

Protocol
--------
One JSON object per line on stdin, one JSON object per line on stdout::

    -> {"id": 1, "cmd": "ping"}
    <- {"id": 1, "ok": true, "data": {"pong": true}}

    -> {"id": 2, "cmd": "chat", "model": "claude-sonnet-5",
        "messages": [{"role": "user", "content": "hi"}]}
    <- {"id": 2, "ok": true, "data": {"reply": "..."}}

    -> {"id": 3, "cmd": "download", "repo": "org/model"}
    <- {"id": 3, "ok": true, "data": {"path": "/home/user/.hypernix/models/model"}}

On failure: ``{"id": N, "ok": false, "code": "HPC-...", "error": "..."}``.

stderr is left connected to the parent's real terminal (Node spawns this
process with stdio ``["pipe", "pipe", "inherit"]``) so every
``huggingface_hub`` progress bar, ``[hypernix] ...`` download log line, and
Python traceback shows up live and unmodified — that's the "logs shown to
the user's terminal" requirement; stdout is reserved for the JSON protocol
and must never carry anything else.

The worker is a single Python process kept alive for the life of the TUI
session, not spawned per turn, so a local model loaded via
:func:`hypernix.hyped_pro_core.send_local_chat` stays resident in VRAM
across turns instead of reloading every message.
"""
from __future__ import annotations

import json
import sys
import traceback
from typing import Any

from . import hyped_pro_core as core

BRIDGE_VERSION = "0.71.4b8"


def _err(id_: Any, code: str, message: str) -> dict[str, Any]:
    return {"id": id_, "ok": False, "code": code, "error": message}


def _ok(id_: Any, data: Any) -> dict[str, Any]:
    return {"id": id_, "ok": True, "data": data}


def dispatch(req: dict[str, Any]) -> dict[str, Any]:
    id_ = req.get("id")
    cmd = req.get("cmd")

    try:
        if cmd == "ping":
            return _ok(id_, {"pong": True, "version": BRIDGE_VERSION})

        if cmd == "catalog":
            return _ok(id_, core.catalog_json())

        if cmd == "is_downloaded":
            model = core.get_model(req["model"])
            downloaded, path = core.is_downloaded(model)
            return _ok(id_, {"downloaded": downloaded, "path": str(path)})

        if cmd == "download":
            model = core.get_model(req["model"])
            print(f"[hyped-pro-bridge] fetching {model.repo} for {model.short} ...", file=sys.stderr)
            path = core.ensure_downloaded(model, quiet=False)
            print(f"[hyped-pro-bridge] {model.short} ready at {path}", file=sys.stderr)
            return _ok(id_, {"path": str(path)})

        if cmd == "chat":
            reply = core.send_chat_message(
                model_short=req["model"],
                messages=req["messages"],
                system=req.get("system"),
                api_key=req.get("api_key"),
                max_tokens=req.get("max_tokens"),
                max_thinking_tokens=req.get("max_thinking_tokens"),
                hide_thinking=req.get("hide_thinking", True),
                enable_tools=req.get("enable_tools", True),
            )
            return _ok(id_, {"reply": reply})

        if cmd == "key_get":
            from .config import get_provider_key
            key = get_provider_key(req["vendor"])
            masked = (key[:6] + "..." + key[-4:]) if key and len(key) > 12 else ("set" if key else None)
            return _ok(id_, {"set": bool(key), "masked": masked})

        if cmd == "key_set":
            from .config import set_provider_key
            set_provider_key(req["vendor"], req["key"])
            return _ok(id_, {"saved": True})

        if cmd == "key_clear":
            from .config import clear_provider_key
            clear_provider_key(req["vendor"])
            return _ok(id_, {"cleared": True})

        return _err(id_, "HPB-PROTO-001", f"unknown command {cmd!r}")

    except core.HypedProError as exc:
        print(f"[hyped-pro-bridge] ERROR {exc.code}: {exc.message}", file=sys.stderr)
        return _err(id_, exc.code, exc.message)
    except KeyError as exc:
        msg = f"missing required field {exc}"
        print(f"[hyped-pro-bridge] ERROR HPB-PROTO-001: {msg}", file=sys.stderr)
        return _err(id_, "HPB-PROTO-001", msg)
    except Exception as exc:  # noqa: BLE001 — must always return JSON, never crash silently
        print("[hyped-pro-bridge] ERROR HPB-INTERNAL-001: unhandled exception", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return _err(id_, "HPB-INTERNAL-001", f"{type(exc).__name__}: {exc}")


def serve() -> int:
    """Read JSON requests from stdin, write JSON responses to stdout, forever."""
    print(f"[hyped-pro-bridge] ready (v{BRIDGE_VERSION}), waiting for requests on stdin", file=sys.stderr)
    try:
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"[hyped-pro-bridge] ERROR HPB-PROTO-001: bad JSON line: {exc}", file=sys.stderr)
                sys.stdout.write(json.dumps(_err(None, "HPB-PROTO-001", f"invalid JSON: {exc}")) + "\n")
                sys.stdout.flush()
                continue
            resp = dispatch(req)
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
    except (BrokenPipeError, OSError):
        # The parent (hyped_pro.ts) exited and closed its end of the pipe
        # while we were mid-write — it's gone, there's no one left to
        # report an error to, so exit quietly rather than dump a traceback.
        pass
    print("[hyped-pro-bridge] stdin closed, exiting", file=sys.stderr)
    return 0


def cli_main(argv: list[str] | None = None) -> int:
    """One-shot mode for scripting/debugging: build a single request from
    argv and print the response, instead of entering the stdio loop.

    Usage: python3 -m hypernix.hyped_pro_bridge <cmd> [key=value ...]
    Example: python3 -m hypernix.hyped_pro_bridge download model=deepseek-r1
    """
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] in ("serve", "--serve"):
        return serve()

    cmd, *rest = argv
    req: dict[str, Any] = {"id": 1, "cmd": cmd}
    for arg in rest:
        if "=" not in arg:
            print(f"usage: hyped_pro_bridge <cmd> [key=value ...] — bad arg {arg!r}", file=sys.stderr)
            return 2
        k, v = arg.split("=", 1)
        req[k] = v
    resp = dispatch(req)
    # Compact, single-line JSON — same wire format as serve()'s stdout, so
    # callers that read "the last line of stdout" (hyped_pro.ts's
    # synchronous catalog fetch) get one parseable object either way.
    print(json.dumps(resp))
    return 0 if resp.get("ok") else 1


if __name__ == "__main__":
    sys.exit(cli_main())
