#!/usr/bin/env python3
"""A model that answers, without a model.

The T1 API reaches an inference backend through the LM Studio bridge,
which speaks the OpenAI shape. So the cheapest honest way to exercise the
whole chat path in CI is to put something at the other end that speaks
that shape and returns a canned answer: no GPU, no download, and every
layer between the phone and the backend is the real one.

Deliberately not a mock inside the test process. A stub reached over HTTP
goes through the actual bridge, the actual routing engine and the actual
serialisation, which is where the interesting failures live — a mock
patched into the bridge would prove only that the mock works.

    python3 scripts/ci/fake_model_server.py --port 1234 &
    T1_LMSTUDIO_URL=http://127.0.0.1:1234 ...
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL_ID = "hypernix-ci-echo"

#: What the fake model says. Distinctive on purpose: a test that asserts
#: on "hello" can pass against a server that echoed the prompt back, and
#: this string can only have come from here.
REPLY = "CI-ECHO-OK"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") in ("/v1/models", "/api/v0/models"):
            self._send({
                "object": "list",
                "data": [{
                    "id": MODEL_ID,
                    "object": "model",
                    "owned_by": "hypernix-ci",
                    "publisher": "hypernix",
                    "state": "loaded",
                }],
            })
            return
        if self.path.rstrip("/") in ("/health", "/v1/health"):
            self._send({"status": "ok"})
            return
        self._send({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            request = json.loads(raw or b"{}")
        except ValueError:
            request = {}

        if self.path.rstrip("/") not in ("/v1/chat/completions", "/v1/completions"):
            self._send({"error": "not found"}, 404)
            return

        # Echo back something derived from the prompt as well as the
        # marker, so a test can prove the request body actually arrived
        # rather than just that *a* response came back.
        messages = request.get("messages") or []
        last = ""
        for message in reversed(messages):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                last = content.strip()
                break
            if isinstance(content, list):  # vision-style parts
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        last = str(part.get("text", "")).strip()
                        break
                if last:
                    break

        self._send({
            "id": "chatcmpl-ci",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request.get("model") or MODEL_ID,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": f"{REPLY} heard:{last[:64]}"},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": max(1, len(last) // 4),
                "completion_tokens": 8,
                "total_tokens": max(1, len(last) // 4) + 8,
            },
        })

    def log_message(self, *args) -> None:
        """Quiet. CI logs are read by people looking for a failure."""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A fake OpenAI-compatible model.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1234)
    args = parser.parse_args(argv)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"fake model {MODEL_ID} listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
