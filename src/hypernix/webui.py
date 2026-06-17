"""hypernix Web UI — local training dashboard (v0.70.3b2).

Serves a static dashboard from ``webui_static/``. Tailscale integration is
**opt-in only** — pass ``-T`` / ``--tailscale`` on ``hypernix webui``.
"""
from __future__ import annotations

import json
import mimetypes
import os
import signal
import socket
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import __version__

PACKAGE_STATIC = Path(__file__).parent / "webui_static"


def _find_and_kill_webui_on_port(port: int) -> bool:
    """Check if a hypernix webui process is running on the given port and kill it.
    
    Returns True if we found and killed a hypernix webui process.
    Returns False if port is free or occupied by non-hypernix process.
    """
    try:
        # Use lsof to find process using this port
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return False
        
        pids = [int(pid.strip()) for pid in result.stdout.strip().split("\n") if pid.strip()]
        
        for pid in pids:
            try:
                # Check if this is a hypernix webui process
                proc_result = subprocess.run(
                    ["ps", "-p", str(pid), "-o", "cmd="],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    check=False,
                )
                cmd = proc_result.stdout.strip() if proc_result.returncode == 0 else ""
                
                if "hypernix" in cmd.lower() and "webui" in cmd.lower():
                    # This is our webui, kill it
                    os.kill(pid, signal.SIGTERM)
                    print(f"  → Terminated existing hypernix webui (PID {pid}) on port {port}")
                    return True
            except (OSError, ValueError, subprocess.TimeoutExpired):
                continue
        
        # Port is occupied by non-hypernix process
        return False
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _is_port_available(port: int) -> bool:
    """Check if a port is available for binding."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


def _find_available_port(start_ports: list[int]) -> int:
    """Find an available port, cycling through the list and killing existing hypernix webui instances.
    
    Args:
        start_ports: List of ports to try in order
        
    Returns:
        An available port number
        
    Raises:
        OSError: If no ports are available after exhausting all options
    """
    tried_ports = set()
    port_index = 0
    
    while True:
        port = start_ports[port_index % len(start_ports)]
        
        # If we've cycled through all ports and they're all occupied by non-hypernix processes
        if port in tried_ports:
            # Try incrementing from the last port
            port = max(start_ports) + 1 + len(tried_ports) - len(start_ports)
        
        tried_ports.add(port)
        
        if _is_port_available(port):
            return port
        
        # Port is occupied, check if it's a hypernix webui
        if _find_and_kill_webui_on_port(port):
            # Wait a moment for the port to be released
            import time
            time.sleep(0.3)
            if _is_port_available(port):
                return port
            # If still not available, continue to next port
        
        # Move to next port in cycle
        port_index += 1
        
        # Safety limit to prevent infinite loop
        if len(tried_ports) > 20:
            raise OSError(f"Could not find an available port after trying {len(tried_ports)} ports")


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
    # Use display host (127.0.0.1) for local URLs when bound to 0.0.0.0
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    url = f"http://{display_host}:{port}"
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
            # Return list of actually loaded/active HyperNix modules
            self._send_json(
                {
                    "modules": [
                        "pressure_cooker_v3",
                        "stovetop_v3_cooker_plus", 
                        "abbicus",
                        "compute_framework",
                        "tupperware",
                        "quantize",
                        "workshop",
                        "download",
                        "sink",
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
        # Determine actual bind address for display/API purposes
        # If host is 0.0.0.0, use localhost for local access URLs
        self._display_host = "127.0.0.1" if host == "0.0.0.0" else host

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
        url = f"http://{self._display_host}:{self.port}"
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
    port: int | None = None,
    enable_tailscale: bool = False,
    static_dir: str | None = None,
) -> int:
    """CLI entry: run until interrupted with automatic port cycling."""
    # Default ports to try in order
    default_ports = [8080, 9090, 1010]
    
    # Determine starting port
    if port is not None:
        # User specified a port, try it first then cycle
        start_ports = [port] + [p for p in default_ports if p != port]
    else:
        start_ports = default_ports
    
    try:
        # Find an available port
        actual_port = _find_available_port(start_ports)
        
        if port is not None and actual_port != port:
            print(f"  → Port {port} was occupied, using {actual_port} instead")
        
        server = WebUIServer(
            host,
            actual_port,
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
