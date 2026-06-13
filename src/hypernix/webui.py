"""hypernix Web UI — local training dashboard (v0.70.3b2).

Serves a static dashboard from ``webui_static/``. Tailscale integration is
**opt-in only** — pass ``-T`` / ``--tailscale`` on ``hypernix webui``.
"""
from __future__ import annotations

import json
import mimetypes
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import __version__

PACKAGE_STATIC = Path(__file__).parent / "webui_static"


def _tailscale_info() -> dict[str, Any]:
    """Best-effort Tailscale hostname lookup; never raises."""
    try:
        proc = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return {"enabled": True, "hostname": None}
        data = json.loads(proc.stdout)
        self_info = data.get("Self", {})
        dns = self_info.get("DNSName") or self_info.get("HostName")
        hostname = dns.rstrip(".") if isinstance(dns, str) else None
        return {"enabled": True, "hostname": hostname}
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return {"enabled": True, "hostname": None}


def _status_payload(
    *,
    host: str,
    port: int,
    tailscale: bool,
) -> dict[str, Any]:
    url = f"http://{host}:{port}"
    payload: dict[str, Any] = {
        "status": "online",
        "version": __version__,
        "url": url,
        "modules": [
            "PressureCookerV3",
            "StovetopV3CookerPlus",
            "Abbicus",
            "ComputeFramework",
            "Tupperware",
            "HyperNixQuantizer",
        ],
        "tailscale": _tailscale_info() if tailscale else {"enabled": False},
    }
    if tailscale and payload["tailscale"].get("hostname"):
        ts_host = payload["tailscale"]["hostname"]
        payload["tailscale"]["share_url"] = f"https://{ts_host}:{port}"
    return payload


class WebUIHandler(BaseHTTPRequestHandler):
    """HTTP handler for the HyperNix dashboard."""

    static_dir: Path = PACKAGE_STATIC
    enable_tailscale: bool = False
    bind_host: str = "127.0.0.1"
    bind_port: int = 8080

    def log_message(self, fmt: str, *args: Any) -> None:
        # Quieter default logging
        if args and str(args[0]).startswith("GET /api/"):
            return
        super().log_message(fmt, *args)

    def _send_json(self, data: dict[str, Any], code: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, data: bytes, content_type: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_static(self, rel: str) -> tuple[bytes, str] | None:
        rel = rel.lstrip("/")
        if rel.startswith("static/"):
            rel = rel[len("static/") :]
        path = (self.static_dir / rel).resolve()
        root = self.static_dir.resolve()
        if not str(path).startswith(str(root)) or not path.is_file():
            return None
        ctype, _ = mimetypes.guess_type(str(path))
        return path.read_bytes(), ctype or "application/octet-stream"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path

        if route in ("/", "/index.html"):
            page = self.static_dir / "index.html"
            if page.is_file():
                self._send_bytes(page.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send_bytes(b"<h1>HyperNix Web UI</h1><p>index.html missing</p>", "text/html")
            return

        if route == "/api/status":
            self._send_json(
                _status_payload(
                    host=self.bind_host,
                    port=self.bind_port,
                    tailscale=self.enable_tailscale,
                )
            )
            return

        if route == "/api/modules":
            self._send_json(
                {
                    "modules": [
                        "pressure_cooker_v3",
                        "abbicus",
                        "compute_framework",
                        "tupperware",
                        "quantize",
                        "workshop",
                    ]
                }
            )
            return

        if route.startswith("/static/"):
            loaded = self._read_static(route)
            if loaded is None:
                self.send_error(404)
                return
            data, ctype = loaded
            self._send_bytes(data, ctype)
            return

        self.send_error(404)


class WebUIServer:
    """Threaded HTTP server for the HyperNix dashboard."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8080,
        *,
        enable_tailscale: bool = False,
        static_dir: str | Path | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.enable_tailscale = enable_tailscale
        self.static_dir = Path(static_dir) if static_dir else PACKAGE_STATIC
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def _make_handler(self) -> type[WebUIHandler]:
        sd = self.static_dir
        ts = self.enable_tailscale
        host = self.host
        port = self.port

        class BoundHandler(WebUIHandler):
            static_dir = sd
            enable_tailscale = ts
            bind_host = host
            bind_port = port

        return BoundHandler

    def start(self, background: bool = False) -> None:
        handler = self._make_handler()
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler)
        url = f"http://{self.host}:{self.port}"
        print(f"✓ HyperNix Web UI at {url}")
        if self.enable_tailscale:
            ts = _tailscale_info()
            if ts.get("hostname"):
                print(f"✓ Tailscale share: https://{ts['hostname']}:{self.port}")
            else:
                print("✓ Tailscale enabled (run `tailscale up` to expose remotely)")
        else:
            print("  Local only — pass -T / --tailscale for remote access")

        if background:
            self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
            self._thread.start()
        else:
            try:
                self._httpd.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                self.stop()

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None


def launch_webui(
    host: str = "127.0.0.1",
    port: int = 8080,
    *,
    enable_tailscale: bool = False,
    background: bool = True,
) -> WebUIServer:
    server = WebUIServer(host, port, enable_tailscale=enable_tailscale)
    server.start(background=background)
    return server


def run_webui(
    host: str = "127.0.0.1",
    port: int = 8080,
    enable_tailscale: bool = False,
    static_dir: str | None = None,
) -> int:
    """CLI entry: run until interrupted."""
    try:
        server = WebUIServer(
            host,
            port,
            enable_tailscale=enable_tailscale,
            static_dir=static_dir,
        )
        server.start(background=False)
        return 0
    except OSError as exc:
        print(f"Error running Web UI: {exc}")
        return 1


if __name__ == "__main__":
    launch_webui(background=False)
