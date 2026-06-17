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


def _enable_tailscale_funnel(port: int) -> bool:
    """Enable Tailscale funnel on the given port.
    
    Returns True if successful, False otherwise.
    """
    try:
        # Enable funnel for the specific port
        proc = subprocess.run(
            ["tailscale", "serve", "--funnel", f"https://{port}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode != 0:
            # Try alternative syntax for older tailscale versions
            proc = subprocess.run(
                ["tailscale", "funnel", str(port)],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        return proc.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


def _discover_modules() -> list[str]:
    """Dynamically discover all HyperNix modules from the package directory."""
    modules = []
    try:
        # Get all .py files in the hypernix package directory (excluding __* and utils)
        for file in PACKAGE_STATIC.parent.glob("*.py"):
            name = file.stem
            if not name.startswith("_") and name not in ("utils", "cli", "webui", "deps", "torch_compat"):
                modules.append(name)
    except Exception:
        # Fallback to known modules if discovery fails
        modules = [
            "pressure_cooker_v3", "stovetop_v3_cooker_plus", "abbicus",
            "compute_framework", "tupperware", "quantize", "workshop",
            "download", "sink", "blender", "cookbook", "countertop",
            "cutting_board", "deep_fryer", "dishwasher", "espresso_maker",
            "food_processor", "freezer", "generate", "hyped",
            "industrial_range", "injection", "instant_pot", "lazy_suzan",
            "lunchbox", "mediocre_fridge", "menu", "microwave",
            "new_fridge", "new_range", "old_fridge", "old_oven", "old_range",
            "outage", "pans", "plasma", "pressure_cooker", "recipe_book",
            "smoke_alarm", "smoker", "strainer", "table", "thermometer",
            "timer", "toaster", "train", "tv", "tvtop", "upload", "ups",
            "whisk", "workshop", "cake_pan", "coffee_maker", "compactor",
            "convert", "doctor", "ethanol", "fetcher", "flour", "nano_nano",
            "pepper_shaker", "salt_shaker"
        ]
    return sorted(modules)


def _get_tvtop_data() -> dict[str, Any]:
    """Get process list and GPU stats for tvtop monitor."""
    import psutil
    
    processes = []
    try:
        # Find python processes running hypernix commands
        for proc in psutil.process_iter(['pid', 'username', 'cmdline', 'memory_percent']):
            try:
                cmdline = ' '.join(proc.info['cmdline'] or []) if proc.info['cmdline'] else ''
                if 'hypernix' in cmdline.lower() or 'python' in cmdline.lower():
                    processes.append({
                        'pid': proc.info['pid'],
                        'user': proc.info['username'] or 'unknown',
                        'gpu_percent': 0,  # Would need nvidia-smi for real GPU usage
                        'ram_percent': round(proc.info['memory_percent'] or 0, 1),
                        'command': cmdline[:100]
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    
    # Try to get GPU info
    gpus = []
    try:
        result = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu', '--format=csv,noheader'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            for i, line in enumerate(result.stdout.strip().split('\n')):
                usage = int(line.replace('%', '').strip())
                gpus.append({'id': i, 'usage': usage})
    except Exception:
        pass
    
    # System stats
    cpu_load = round(psutil.cpu_percent(interval=0.1), 1) if psutil else 0
    ram_usage = round(psutil.virtual_memory().percent, 1) if psutil else 0
    
    return {
        'processes': processes,
        'gpus': gpus,
        'cpu_load': cpu_load,
        'ram_usage': ram_usage,
        'disk_io': 'N/A'
    }


def _get_network_data() -> dict[str, Any]:
    """Get network/Tailscale status."""
    import socket
    
    hostname = socket.gethostname()
    ts_info = _tailscale_info()
    
    interfaces = []
    try:
        import psutil
        addrs = psutil.net_if_addrs()
        for iface_name, addrs_list in addrs.items():
            for addr in addrs_list:
                if addr.family == socket.AF_INET:
                    interfaces.append({
                        'name': iface_name,
                        'ip': addr.address,
                        'up': True
                    })
    except Exception:
        pass
    
    return {
        'hostname': hostname,
        'tailscale_connected': ts_info.get('connected', False),
        'tailscale_ip': ts_info.get('ip', '--'),
        'funnel_enabled': ts_info.get('funnel', False),
        'share_url': ts_info.get('share_url', '--'),
        'interfaces': interfaces[:5]  # Limit to first 5
    }


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
        "modules": _discover_modules(),
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
            # Return list of actually loaded/active HyperNix modules (dynamic discovery)
            self._send_json({"modules": _discover_modules()})
            return

        if route == "/api/tvtop":
            # Return process list and GPU stats
            self._send_json(_get_tvtop_data())
            return

        if route == "/api/network":
            # Return network/Tailscale status
            self._send_json(_get_network_data())
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

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path
        
        # Handle kill process for tvtop
        if route.startswith("/api/tvtop/kill/"):
            try:
                pid = int(route.split("/")[-1])
                import os
                import signal
                os.kill(pid, signal.SIGTERM)
                self._send_json({"success": True, "killed": pid})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return
        
        # Handle funnel toggle
        if route == "/api/network/funnel":
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else '{}'
                data = json.loads(body)
                action = data.get('action', 'toggle')
                
                # Execute tailscale funnel command
                cmd = ["tailscale", "serve", "--funnel"] if action == 'enable' else ["tailscale", "serve", "--funnel=false"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                
                if result.returncode == 0:
                    self._send_json({"success": True, "action": action})
                else:
                    self._send_json({"success": False, "error": result.stderr or "Command failed"}, 500)
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
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
        
        # Enable Tailscale funnel if requested
        if self.enable_tailscale:
            if _enable_tailscale_funnel(self.port):
                print(f"✓ Tailscale funnel enabled on port {self.port}")
            else:
                print("  ⚠ Tailscale funnel could not be enabled (check tailscale status)")
        
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
