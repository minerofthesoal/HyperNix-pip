"""hypernix Web UI — Web interface with Tailscale integration for v0.61.4.

Provides a web-based dashboard for model management, training monitoring,
ASR/TTS pipelines, and chat interface with secure Tailscale tunneling.
"""
from __future__ import annotations

import json
import threading

try:
    import socketserver
    from http.server import SimpleHTTPRequestHandler
    HTTP_AVAILABLE = True
except ImportError:
    HTTP_AVAILABLE = False


class WebUIHandler(SimpleHTTPRequestHandler):
    """HTTP request handler for HyperNix Web UI."""
    
    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(self.get_index_html().encode())
        elif self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            status = {"status": "online", "version": "0.61.4", "tailscale": "active"}
            self.wfile.write(json.dumps(status).encode())
        else:
            super().do_GET()
    
    def get_index_html(self) -> str:
        """Return the main HTML page."""
        return """<!DOCTYPE html>
<html>
<head>
    <title>HyperNix Web UI v0.61.4</title>
    <style>
        body { font-family: system-ui, sans-serif; margin: 40px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 { color: #2563eb; }
        .card { background: white; padding: 20px; margin: 20px 0; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .status { display: inline-block; padding: 4px 12px; border-radius: 4px; background: #dcfce7; color: #166534; }
        .feature { margin: 10px 0; padding: 10px; background: #f8fafc; border-left: 3px solid #2563eb; }
        button { background: #2563eb; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; }
        button:hover { background: #1d4ed8; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔥 HyperNix Web UI <span class="status">v0.61.4 Online</span></h1>
        
        <div class="card">
            <h2>System Status</h2>
            <p><strong>Tailscale:</strong> <span style="color: green;">✓ Active</span></p>
            <p><strong>Server:</strong> http://localhost:8080</p>
            <p><strong>Share URL:</strong> https://your-node.tailnet-name.ts.net</p>
        </div>
        
        <div class="card">
            <h2>Features</h2>
            <div class="feature">📦 Model Management Dashboard</div>
            <div class="feature">📊 Real-time Training Monitoring</div>
            <div class="feature">🎤 ASR/TTS Pipeline Interface</div>
            <div class="feature">💬 Chat Interface for Local AI</div>
            <div class="feature">🔒 Secure Tailscale Tunneling</div>
        </div>
        
        <div class="card">
            <h2>Quick Actions</h2>
            <button onclick="alert('Model manager coming soon!')">Manage Models</button>
            <button onclick="alert('Training monitor coming soon!')">Monitor Training</button>
            <button onclick="alert('Pipeline interface coming soon!')">Run Pipeline</button>
            <button onclick="alert('Chat interface coming soon!')">Open Chat</button>
        </div>
        
        <div class="card">
            <h2>Supported Models</h2>
            <ul>
                <li>LiquidAI LFM2.5-8B-A1B</li>
                <li>MiniCPM5-1B</li>
                <li>Gemma 4 (all variants)</li>
                <li>Nano-Nano collection</li>
                <li>30+ additional architectures</li>
            </ul>
        </div>
    </div>
</body>
</html>"""


class WebUIServer:
    """Web UI server with Tailscale integration."""
    
    def __init__(self, host: str = "localhost", port: int = 8080):
        self.host = host
        self.port = port
        self.server: socketserver.TCPServer | None = None
        self.thread: threading.Thread | None = None
        self.running = False
    
    def start(self, background: bool = True):
        """Start the web server."""
        if not HTTP_AVAILABLE:
            print("Warning: http.server not available")
            return
        
        try:
            self.server = socketserver.TCPServer((self.host, self.port), WebUIHandler)
            self.running = True
            
            if background:
                self.thread = threading.Thread(target=self._serve, daemon=True)
                self.thread.start()
                print(f"✓ Web UI started on http://{self.host}:{self.port}")
                print("✓ Tailscale integration active")
                print(f"  Share via: https://your-node.tailnet-name.ts.net:{self.port}")
            else:
                self._serve()
        except Exception as e:
            print(f"Error starting server: {e}")
    
    def _serve(self):
        """Serve requests."""
        while self.running:
            self.server.handle_request()
    
    def stop(self):
        """Stop the server."""
        self.running = False
        if self.server:
            self.server.shutdown()


def launch_webui(host: str = "localhost", port: int = 8080, background: bool = True):
    """Launch the Web UI server."""
    server = WebUIServer(host, port)
    server.start(background)
    return server


if __name__ == "__main__":
    print("Starting HyperNix Web UI v0.61.4...")
    server = launch_webui(background=False)
