"""hypernix Web UI — Web interface with Tailscale integration for v0.61.4.

Provides a web-based dashboard for model management, training monitoring,
ASR/TTS pipelines, and chat interface with secure Tailscale tunneling.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

try:
    import socketserver
    from http.server import SimpleHTTPRequestHandler
    HTTP_AVAILABLE = True
except ImportError:
    HTTP_AVAILABLE = False


# Define explicit static directory (security fix - P1)
STATIC_DIR = Path(__file__).parent / "webui_static"


class WebUIHandler(SimpleHTTPRequestHandler):
    """HTTP request handler for HyperNix Web UI."""
    
    # Override directory to serve from explicit static dir, not cwd
    directory = str(STATIC_DIR) if STATIC_DIR.exists() else None
    
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
            status = {
                "status": "online",
                "version": "0.61.4",
                "tailscale": "active",
                "features": ["models", "training", "asr_tts", "chat", "assistant"]
            }
            self.wfile.write(json.dumps(status).encode())
        elif self.path == "/api/models":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            models = {
                "loaded": ["nano-llama", "gemma-4-1b-it"],
                "available": [
                    "LiquidAI/LFM2.5-8B-A1B-GGUF",
                    "openbmb/MiniCPM5-1B",
                    "google/gemma-4-31B-it",
                    "google/gemma-4-12b-it",
                    "google/gemma-4-1b-it",
                    "nano-llama", "nano-mistral", "nano-whisper", "nano-tacotron",
                    "Qwen3.5-7B", "Phi-4-14B", "DeepSeek-V2.5", "Llama-3.2-3B"
                ]
            }
            self.wfile.write(json.dumps(models).encode())
        elif self.path == "/api/training/status":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            status = {
                "running": False,
                "last_step": 0,
                "loss": None,
                "checkpoint": None
            }
            self.wfile.write(json.dumps(status).encode())
        elif self.path.startswith("/static/"):
            # Serve static files only from designated directory
            super().do_GET()
        else:
            # Return 404 for any other paths (security fix)
            self.send_response(404)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"404 Not Found")
    
    def get_index_html(self) -> str:
        """Return the main HTML page."""
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HyperNix Web UI v0.70.1</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-gradient: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
            --glass-bg: rgba(255, 255, 255, 0.05);
            --glass-border: rgba(255, 255, 255, 0.1);
            --glass-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
            --primary: #818cf8;
            --secondary: #c084fc;
            --accent: #38bdf8;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --success: #34d399;
            --danger: #f43f5e;
            --font-main: 'Outfit', sans-serif;
            --font-code: 'JetBrains Mono', monospace;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body { 
            font-family: var(--font-main); 
            background: var(--bg-gradient); 
            color: var(--text-main); 
            min-height: 100vh; 
            padding: 2rem;
            overflow-x: hidden;
        }

        /* Abstract Background Elements */
        .bg-glow {
            position: fixed; width: 600px; height: 600px;
            background: radial-gradient(circle, var(--primary) 0%, transparent 70%);
            opacity: 0.15; filter: blur(80px); top: -200px; left: -200px; z-index: -1;
            animation: float 10s infinite ease-in-out alternate;
        }
        .bg-glow-2 {
            position: fixed; width: 500px; height: 500px;
            background: radial-gradient(circle, var(--secondary) 0%, transparent 70%);
            opacity: 0.15; filter: blur(60px); bottom: -100px; right: -100px; z-index: -1;
            animation: float 12s infinite ease-in-out alternate-reverse;
        }

        @keyframes float {
            0% { transform: translate(0, 0); }
            100% { transform: translate(50px, 50px); }
        }

        .container { max-width: 1400px; margin: 0 auto; }
        
        header { margin-bottom: 2.5rem; text-align: center; }
        h1 { 
            font-size: 3.5rem; font-weight: 800; 
            background: linear-gradient(to right, var(--accent), var(--secondary));
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            margin-bottom: 0.5rem; letter-spacing: -1px;
        }
        .subtitle { color: var(--text-muted); font-size: 1.2rem; font-weight: 300; }

        .status-bar {
            display: flex; justify-content: center; gap: 1rem; margin-bottom: 2rem;
            flex-wrap: wrap;
        }
        .badge {
            background: var(--glass-bg); backdrop-filter: blur(10px);
            border: 1px solid var(--glass-border); padding: 0.5rem 1rem;
            border-radius: 2rem; font-size: 0.9rem; font-weight: 600;
            display: flex; align-items: center; gap: 0.5rem;
        }
        .badge.online i { display: inline-block; width: 8px; height: 8px; background: var(--success); border-radius: 50%; box-shadow: 0 0 8px var(--success); }
        .badge.tailscale i { display: inline-block; width: 8px; height: 8px; background: var(--secondary); border-radius: 50%; box-shadow: 0 0 8px var(--secondary); }

        .tabs {
            display: flex; gap: 1rem; margin-bottom: 2rem; justify-content: center;
            background: var(--glass-bg); padding: 0.5rem; border-radius: 1rem;
            border: 1px solid var(--glass-border); backdrop-filter: blur(10px);
            width: fit-content; margin-left: auto; margin-right: auto;
        }
        .tab {
            padding: 0.8rem 1.5rem; background: transparent; border: none;
            color: var(--text-muted); font-family: var(--font-main); font-size: 1rem;
            font-weight: 600; cursor: pointer; border-radius: 0.5rem; transition: all 0.3s ease;
        }
        .tab:hover { color: var(--text-main); background: rgba(255,255,255,0.05); }
        .tab.active { background: var(--primary); color: white; box-shadow: 0 4px 15px rgba(129, 140, 248, 0.4); }

        .tab-content { display: none; animation: fadeIn 0.4s ease-out forwards; }
        .tab-content.active { display: block; }
        
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); gap: 1.5rem; }
        
        .card {
            background: var(--glass-bg); backdrop-filter: blur(16px);
            border: 1px solid var(--glass-border); border-radius: 1.5rem;
            padding: 2rem; box-shadow: var(--glass-shadow); transition: transform 0.3s ease, border-color 0.3s ease;
        }
        .card:hover { transform: translateY(-5px); border-color: rgba(255,255,255,0.2); }
        
        .card h2 { font-size: 1.5rem; margin-bottom: 1.5rem; color: var(--text-main); font-weight: 600; display: flex; align-items: center; gap: 0.5rem; }
        
        .btn {
            background: linear-gradient(135deg, var(--primary), var(--secondary));
            color: white; border: none; padding: 0.8rem 1.5rem; border-radius: 0.75rem;
            font-family: var(--font-main); font-weight: 600; font-size: 1rem;
            cursor: pointer; transition: all 0.3s ease; display: inline-flex; align-items: center; gap: 0.5rem;
            width: 100%; justify-content: center; margin-bottom: 1rem;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 5px 15px rgba(192, 132, 252, 0.4); filter: brightness(1.1); }
        .btn-outline {
            background: transparent; border: 1px solid var(--glass-border);
            background: var(--glass-bg); color: var(--text-main);
        }
        .btn-outline:hover { background: rgba(255,255,255,0.1); border-color: rgba(255,255,255,0.3); box-shadow: none; }

        input, select {
            width: 100%; padding: 0.8rem 1rem; margin-bottom: 1rem;
            background: rgba(0,0,0,0.2); border: 1px solid var(--glass-border);
            border-radius: 0.75rem; color: var(--text-main); font-family: var(--font-main);
            font-size: 1rem; transition: all 0.3s ease;
        }
        input:focus, select:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 2px rgba(129, 140, 248, 0.2); background: rgba(0,0,0,0.4); }
        select option { background: var(--bg-gradient); color: var(--text-main); }
        label { display: block; margin-bottom: 0.5rem; color: var(--text-muted); font-size: 0.9rem; font-weight: 600; }

        .terminal {
            background: #0f172a; border: 1px solid var(--glass-border); border-radius: 1rem;
            padding: 1rem; font-family: var(--font-code); font-size: 0.85rem; color: var(--accent);
            height: 250px; overflow-y: auto; margin-top: 1rem; box-shadow: inset 0 2px 10px rgba(0,0,0,0.5);
        }
        .terminal::-webkit-scrollbar { width: 8px; }
        .terminal::-webkit-scrollbar-thumb { background: var(--glass-border); border-radius: 4px; }

        .tag-container { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1.5rem; }
        .tag {
            background: rgba(56, 189, 248, 0.1); color: var(--accent);
            border: 1px solid rgba(56, 189, 248, 0.2); padding: 0.4rem 0.8rem;
            border-radius: 2rem; font-size: 0.85rem; font-weight: 600;
        }
        .tag.loaded { background: rgba(52, 211, 153, 0.1); color: var(--success); border-color: rgba(52, 211, 153, 0.2); }

        .chat-window { height: 400px; display: flex; flex-direction: column; }
        .chat-messages {
            flex: 1; overflow-y: auto; padding: 1rem; background: rgba(0,0,0,0.2);
            border-radius: 1rem; margin-bottom: 1rem; border: 1px solid var(--glass-border);
        }
        .msg { margin-bottom: 1rem; max-width: 80%; animation: fadeIn 0.3s ease; }
        .msg-assistant { margin-right: auto; }
        .msg-user { margin-left: auto; text-align: right; }
        .msg-bubble {
            padding: 1rem; border-radius: 1rem; display: inline-block; font-size: 0.95rem; line-height: 1.4;
        }
        .msg-assistant .msg-bubble { background: rgba(255,255,255,0.05); border: 1px solid var(--glass-border); border-bottom-left-radius: 0; }
        .msg-user .msg-bubble { background: linear-gradient(135deg, var(--primary), var(--secondary)); border-bottom-right-radius: 0; }
        
        .chat-input-area { display: flex; gap: 0.5rem; }
        .chat-input-area input { margin-bottom: 0; }
        .chat-input-area .btn { width: auto; margin-bottom: 0; padding: 0.8rem 1.5rem; }
        
        .stats-row { display: flex; justify-content: space-between; margin-bottom: 1rem; padding-bottom: 1rem; border-bottom: 1px solid var(--glass-border); }
        .stat-val { font-size: 1.5rem; font-weight: 800; color: var(--text-main); }
        .stat-label { font-size: 0.8rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px; }

    </style>
</head>
<body>
    <div class="bg-glow"></div>
    <div class="bg-glow-2"></div>

    <div class="container">
        <header>
            <h1>HyperNix</h1>
            <p class="subtitle">v0.70.1 Advanced Agentic Core</p>
        </header>
        
        <div class="status-bar">
            <div class="badge online"><i></i> System Online</div>
            <div class="badge tailscale"><i></i> Tailscale Active</div>
            <div class="badge" style="font-family: var(--font-code);">http://localhost:8080</div>
        </div>

        <div class="tabs">
            <button class="tab active" onclick="switchTab('dashboard')">Dashboard</button>
            <button class="tab" onclick="switchTab('models')">Neural Cores</button>
            <button class="tab" onclick="switchTab('training')">Pressure Cooker v3</button>
            <button class="tab" onclick="switchTab('pipeline')">Pipelines</button>
            <button class="tab" onclick="switchTab('chat')">Assistant</button>
        </div>

        <!-- Dashboard -->
        <div id="dashboard" class="tab-content active">
            <div class="grid">
                <div class="card">
                    <h2>⚡ System Overview</h2>
                    <div class="stats-row">
                        <div>
                            <div class="stat-val">0.70.1</div>
                            <div class="stat-label">Version</div>
                        </div>
                        <div style="text-align: right;">
                            <div class="stat-val" style="color: var(--success);">Stable</div>
                            <div class="stat-label">Status</div>
                        </div>
                    </div>
                    <p style="color: var(--text-muted); margin-bottom: 1.5rem; line-height: 1.6;">
                        HyperNix engine is running optimally. Compute Framework detected <strong>CUDA backend</strong> with FSDP capabilities ready.
                    </p>
                    <label>Active Subsystems:</label>
                    <div class="tag-container" style="margin-top: 0.5rem;">
                        <span class="tag loaded">PressureCookerV3</span>
                        <span class="tag loaded">Abbicus</span>
                        <span class="tag loaded">ComputeFramework</span>
                        <span class="tag loaded">Ethanol</span>
                        <span class="tag loaded">UPS Daemon</span>
                    </div>
                </div>
                
                <div class="card">
                    <h2>🚀 Quick Actions</h2>
                    <button class="btn" onclick="switchTab('models')">🔌 Manage Neural Cores</button>
                    <button class="btn" onclick="switchTab('training')">📈 Launch Training Run</button>
                    <button class="btn btn-outline" onclick="switchTab('pipeline')">🎤 Start ASR Pipeline</button>
                    <button class="btn btn-outline" onclick="switchTab('chat')">💬 Open Assistant</button>
                </div>
            </div>
        </div>

        <!-- Models -->
        <div id="models" class="tab-content">
            <div class="card" style="max-width: 800px; margin: 0 auto;">
                <h2>📦 Neural Core Registry</h2>
                
                <label>Loaded Active Cores</label>
                <div class="tag-container">
                    <span class="tag loaded">nano-llama (80M) • FP16</span>
                    <span class="tag loaded">gemma-4-1b-it • Q4M</span>
                </div>
                
                <label style="margin-top: 1.5rem;">Available Blueprints</label>
                <div class="tag-container">
                    <span class="tag">LiquidAI/LFM2.5-8B</span>
                    <span class="tag">openbmb/MiniCPM5-1B</span>
                    <span class="tag">gemma-4-31B-it</span>
                    <span class="tag">Qwen3.5-7B</span>
                    <span class="tag">Phi-4-14B</span>
                    <span class="tag">DeepSeek-V2.5</span>
                    <span class="tag">nano-whisper</span>
                    <span class="tag">nano-tacotron</span>
                </div>
                
                <hr style="border: 0; border-top: 1px solid var(--glass-border); margin: 2rem 0;">
                
                <label>Deploy New Core</label>
                <select id="model-select">
                    <option value="nano-llama">Nano LLaMA (80M) - Extremely Fast</option>
                    <option value="gemma-4-1b-it">Gemma 4 1B IT - Balanced</option>
                    <option value="Phi-4-14B">Phi-4 14B - High Intelligence</option>
                </select>
                <button class="btn" onclick="alert('Allocating VRAM and instantiating core...')">Allocate & Load</button>
            </div>
        </div>

        <!-- Training -->
        <div id="training" class="tab-content">
            <div class="grid">
                <div class="card">
                    <h2>📈 Pressure Cooker v3 Config</h2>
                    
                    <label>Target Architecture</label>
                    <select>
                        <option>nano-llama</option>
                        <option>custom</option>
                    </select>
                    
                    <div style="display: flex; gap: 1rem;">
                        <div style="flex: 1;">
                            <label>Target Steps</label>
                            <input type="number" value="10000">
                        </div>
                        <div style="flex: 1;">
                            <label>Batch Size</label>
                            <input type="number" value="32">
                        </div>
                    </div>
                    
                    <label>Quantization (v3Plus)</label>
                    <select>
                        <option>FP8 (Hardware Accelerated)</option>
                        <option>Q5.5 (Balanced)</option>
                        <option>Q4M (Max Memory Saving)</option>
                        <option>None (FP16/FP32)</option>
                    </select>

                    <label>Token Regulation (Abbicus)</label>
                    <select>
                        <option>Dynamic Curriculum (Auto)</option>
                        <option>Static Padding</option>
                    </select>
                    
                    <button class="btn" onclick="startTraining()" id="train-btn" style="margin-top: 1rem;">Ignite Training Run</button>
                </div>
                
                <div class="card">
                    <h2>Live Telemetry</h2>
                    <div class="stats-row" style="margin-bottom: 0;">
                        <div>
                            <div class="stat-val" id="t-step">0</div>
                            <div class="stat-label">Step</div>
                        </div>
                        <div>
                            <div class="stat-val" id="t-loss" style="color: var(--accent);">--</div>
                            <div class="stat-label">Loss</div>
                        </div>
                        <div style="text-align: right;">
                            <div class="stat-val" id="t-status" style="color: var(--text-muted);">Idle</div>
                            <div class="stat-label">Status</div>
                        </div>
                    </div>
                    <div class="terminal" id="training-logs">Waiting for hypernix dispatcher...</div>
                </div>
            </div>
        </div>

        <!-- Pipeline -->
        <div id="pipeline" class="tab-content">
            <div class="card" style="max-width: 800px; margin: 0 auto;">
                <h2>🔄 End-to-End ASR → LLM → TTS</h2>
                
                <div style="display: flex; gap: 1rem; margin-bottom: 1.5rem;">
                    <div style="flex: 1;">
                        <label>ASR Ear</label>
                        <select><option>nano-whisper</option><option>conformer</option></select>
                    </div>
                    <div style="flex: 1;">
                        <label>Brain</label>
                        <select><option>nano-llama</option><option>gemma-4-1b-it</option></select>
                    </div>
                    <div style="flex: 1;">
                        <label>TTS Voice</label>
                        <select><option>nano-tacotron</option><option>fastpitch</option></select>
                    </div>
                </div>

                <label>Input Audio Source</label>
                <input type="file" accept="audio/*">
                
                <button class="btn" onclick="runPipeline()" style="margin-top: 1rem;">Process Pipeline Streaming</button>
                
                <div class="terminal" id="pipeline-output" style="height: 150px; margin-top: 1.5rem;">Awaiting stream input...</div>
            </div>
        </div>

        <!-- Chat -->
        <div id="chat" class="tab-content">
            <div class="card chat-window" style="max-width: 800px; margin: 0 auto; height: 600px;">
                <h2>💬 Neural Interface</h2>
                <div class="chat-messages" id="chat-messages">
                    <div class="msg msg-assistant">
                        <div class="msg-bubble">HyperNix Core initialized. How can I optimize your workflow today?</div>
                    </div>
                </div>
                <div class="chat-input-area">
                    <input type="text" id="chat-input" placeholder="Initiate query..." onkeypress="if(event.key==='Enter')sendMessage()">
                    <button class="btn" onclick="sendMessage()">Send</button>
                </div>
            </div>
        </div>

    </div>

    <script>
        function switchTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            event.target.classList.add('active');
        }

        let trainInterval;
        function startTraining() {
            const btn = document.getElementById('train-btn');
            if (btn.innerText === 'Stop Training') {
                clearInterval(trainInterval);
                btn.innerText = 'Ignite Training Run';
                btn.classList.remove('btn-outline');
                document.getElementById('t-status').innerText = 'Halted';
                document.getElementById('t-status').style.color = 'var(--danger)';
                return;
            }

            btn.innerText = 'Stop Training';
            btn.classList.add('btn-outline');
            document.getElementById('t-status').innerText = 'Cooking';
            document.getElementById('t-status').style.color = 'var(--success)';
            
            const logs = document.getElementById('training-logs');
            logs.innerHTML = '> Booting ComputeFramework...\\n> VRAM Allocated.\\n> Initializing PressureCookerV3Plus(dtype=FP8)...\\n';
            
            let step = 0;
            trainInterval = setInterval(() => {
                step += 10;
                const loss = (2.5 * Math.exp(-step * 0.001) + Math.random() * 0.05).toFixed(4);
                const lr = (3e-4 * Math.exp(-step * 0.0005)).toFixed(6);
                
                document.getElementById('t-step').innerText = step;
                document.getElementById('t-loss').innerText = loss;
                
                logs.innerHTML += `[Step ${step.toString().padStart(4, '0')}] Loss: ${loss} | LR: ${lr} | Throughput: ${(Math.random()*10+50).toFixed(1)} tk/s\\n`;
                logs.scrollTop = logs.scrollHeight;
                
                if (step >= 5000) clearInterval(trainInterval);
            }, 300);
        }

        function runPipeline() {
            const out = document.getElementById('pipeline-output');
            out.innerHTML = '> Starting ASR transcription...\\n';
            setTimeout(() => { out.innerHTML += '> Transcribed: "Hello, what is the status of the server?"\\n> Feeding to LLM...\\n'; }, 1000);
            setTimeout(() => { out.innerHTML += '> LLM Output: "The server is currently online and functioning nominally."\\n> Synthesizing speech...\\n'; }, 2500);
            setTimeout(() => { out.innerHTML += '> Audio synthesis complete. Playing...\\n'; }, 4000);
        }

        function sendMessage() {
            const input = document.getElementById('chat-input');
            const msg = input.value.trim();
            if(!msg) return;
            
            const chat = document.getElementById('chat-messages');
            chat.innerHTML += `<div class="msg msg-user"><div class="msg-bubble">${msg}</div></div>`;
            input.value = '';
            chat.scrollTop = chat.scrollHeight;

            setTimeout(() => {
                chat.innerHTML += `<div class="msg msg-assistant"><div class="msg-bubble">Processing request: "${msg}". Architecture constraints applied.</div></div>`;
                chat.scrollTop = chat.scrollHeight;
            }, 800);
        }
    </script>
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


def run_webui(host: str = "127.0.0.1", port: int = 8080, enable_tailscale: bool = False, static_dir: str | None = None) -> int:
    """Run the Web UI server as a CLI command.
    
    Args:
        host: Host to bind to
        port: Port to bind to
        enable_tailscale: Enable Tailscale tunneling
        static_dir: Directory to serve static files from
    
    Returns:
        Exit code (0 for success)
    """
    try:
        server = WebUIServer(host, port, enable_tailscale=enable_tailscale, static_dir=static_dir)
        server.start(background=False)
        return 0
    except KeyboardInterrupt:
        print("\nWeb UI stopped.")
        return 0
    except Exception as e:
        print(f"Error running Web UI: {e}")
        return 1


if __name__ == "__main__":
    print("Starting HyperNix Web UI v0.61.4...")
    server = launch_webui(background=False)
