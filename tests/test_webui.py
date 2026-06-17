"""Tests for hypernix.webui (v0.70.3b2 rebuild)."""
from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from hypernix.webui import WebUIServer, _status_payload


def test_status_payload_tailscale_off() -> None:
    data = _status_payload(host="127.0.0.1", port=8765, tailscale=False)
    assert data["version"]
    assert data["tailscale"]["enabled"] is False
    assert "tupperware" in data["modules"]


def test_status_payload_tailscale_on() -> None:
    data = _status_payload(host="127.0.0.1", port=8765, tailscale=True)
    assert data["tailscale"]["enabled"] is True


def test_server_serves_index() -> None:
    server = WebUIServer("127.0.0.1", 0, enable_tailscale=False)
    handler = server._make_handler()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as resp:
            html = resp.read().decode()
        assert "HyperNix" in html
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=3) as resp:
            data = json.loads(resp.read().decode())
        assert data["status"] == "online"
        assert data["tailscale"]["enabled"] is False
    finally:
        httpd.shutdown()
        httpd.server_close()
