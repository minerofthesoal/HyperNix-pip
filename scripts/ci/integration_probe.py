#!/usr/bin/env python3
"""Drive a running T1 API the way a client does, then clean up after itself.

Run against a server that is already up. Mints its own T2 key, authorises
it, sends a chat through the fake model, and then deletes every key it
created — including on failure, because a CI job that leaves credentials
behind in a shared key store is worse than one that fails.

    python3 scripts/ci/integration_probe.py --url http://127.0.0.1:8000

Exits non-zero with the failing step named. Every check is a real HTTP
round trip: the point is to catch the wiring, and a probe that imported
the app and called it in-process would not have caught the advertised-port
bug that made HyperLink time out.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

# Diagnostics talk to one named host; a proxy in between answers a
# different question, and CI runners set HTTP_PROXY more often than not.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ProbeFailure(RuntimeError):
    pass


def call(
    url: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    key: str | None = None,
    timeout: float = 30.0,
) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if key:
        request.add_header("Authorization", f"Bearer {key}")
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            return response.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"raw": raw}


def wait_for(url: str, *, seconds: float = 60.0) -> None:
    """Block until the server answers, or say how long we waited.

    A fixed sleep is the usual way this is written and the usual reason
    CI is flaky: it is either too short on a loaded runner or wasted time
    on a fast one.
    """
    deadline = time.time() + seconds
    last = ""
    while time.time() < deadline:
        try:
            status, _ = call(f"{url}/health", timeout=5.0)
            if status == 200:
                return
            last = f"HTTP {status}"
        except OSError as exc:
            last = str(exc)
        time.sleep(0.5)
    raise ProbeFailure(f"server never became healthy in {seconds:.0f}s (last: {last})")


def step(name: str) -> None:
    print(f"  → {name}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--model", default="hypernix-ci-echo")
    parser.add_argument("--expect", default="CI-ECHO-OK")
    args = parser.parse_args(argv)
    url = args.url.rstrip("/")

    minted: list[str] = []
    try:
        step("waiting for the server")
        wait_for(url)

        step("the server reports its version")
        status, body = call(f"{url}/status")
        if status != 200 or not body.get("t1_api_version"):
            raise ProbeFailure(f"/status returned {status}: {body}")
        print(f"     t1 v{body['t1_api_version']} — {body.get('server_name') or 'unnamed'}")

        step("minting a T2 key with gkey")
        raw_key, key_id = mint_key()
        minted.append(key_id)
        if not raw_key.startswith("T2"):
            raise ProbeFailure(f"gkey did not return a T2 key: {raw_key[:12]}…")
        print(f"     {raw_key[:14]}… ({key_id[:8]}…)")

        step("the server accepts it")
        status, body = call(f"{url}/auth/t1/validate", method="POST", body={"key": raw_key})
        if status != 200:
            raise ProbeFailure(f"the minted key was refused: HTTP {status} {body}")

        step("the fake model is visible through the bridge")
        status, body = call(f"{url}/bridge/lmstudio/models", key=raw_key)
        names = [
            m.get("model_id") or m.get("id") or m.get("name")
            for m in (body.get("models") or body.get("data") or [])
        ]
        if status != 200 or args.model not in names:
            raise ProbeFailure(
                f"{args.model!r} not visible: HTTP {status} {names or body}"
            )

        step("a chat goes all the way to the fake model and back")
        status, body = call(
            f"{url}/bridge/lmstudio/chat",
            method="POST",
            key=raw_key,
            body={
                "model": args.model,
                "messages": [{"role": "user", "content": "ping from CI"}],
            },
            timeout=60.0,
        )
        text = json.dumps(body)
        if status != 200 or args.expect not in text:
            raise ProbeFailure(
                f"chat did not reach the fake model: HTTP {status} {text[:300]}"
            )
        if "heard:ping from CI" not in text:
            raise ProbeFailure(
                "the model answered but did not receive the prompt — the request "
                f"body did not survive the bridge: {text[:300]}"
            )
        print(f"     model said: {args.expect}, and echoed the prompt back")

        print("\n  all integration checks passed", flush=True)
        return 0
    except ProbeFailure as exc:
        print(f"\n  FAILED: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        # Always, including on failure. A CI job that leaves credentials
        # behind is worse than one that fails.
        for key_id in minted:
            revoked = revoke_key(key_id)
            print(f"  → deleted key {key_id[:8]}… ({revoked})", flush=True)


def _gkey(*argv: str) -> str:
    """Run gkey and return its plain output.

    NO_COLOR so the panel does not arrive wrapped in escape codes, which
    is the difference between a parse and a support ticket.
    """
    import os
    import subprocess

    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "hypernix.security.gkey_cli", *argv],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "NO_COLOR": "1"},
        check=False,
    )
    if result.returncode != 0:
        raise ProbeFailure(f"gkey {' '.join(argv)} failed: {result.stderr.strip()[:300]}")
    return _strip_ansi(result.stdout)


def _strip_ansi(text: str) -> str:
    import re

    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _field(text: str, label: str) -> str:
    import re

    pattern = re.compile(rf"\b{re.escape(label)}:\s*(.+)")
    for line in text.splitlines():
        match = pattern.search(line)
        if match:
            return match.group(1).strip().rstrip("│").strip()
    raise ProbeFailure(f"gkey output had no {label!r}:\n{text[:400]}")


def mint_key() -> tuple[str, str]:
    """A fresh T2 key, as (raw key, key id)."""
    output = _gkey("create", "-v", "v2", "--scopes", "read,write", "--prefix", "ci-probe")
    return _field(output, "Key"), _field(output, "Key ID")


def revoke_key(key_id: str) -> str:
    try:
        _gkey("revoke", key_id, "--reason", "CI integration probe teardown")
        return "revoked"
    except ProbeFailure as exc:
        return f"NOT REVOKED: {exc}"


if __name__ == "__main__":
    sys.exit(main())
