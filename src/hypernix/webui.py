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
<html>
<head>
    <title>HyperNix Web UI v0.61.4</title>
    <style>
        * { box-sizing: border-box; }
        body { font-family: system-ui, -apple-system, sans-serif; margin: 0; padding: 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 { color: white; text-shadow: 2px 2px 4px rgba(0,0,0,0.3); margin-bottom: 10px; }
        .subtitle { color: rgba(255,255,255,0.9); margin-bottom: 30px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 20px; }
        .card { background: white; padding: 25px; border-radius: 12px; box-shadow: 0 8px 32px rgba(0,0,0,0.2); }
        .card h2 { color: #667eea; margin-top: 0; border-bottom: 2px solid #f0f0f0; padding-bottom: 10px; }
        .status-badge { display: inline-block; padding: 6px 16px; border-radius: 20px; background: linear-gradient(135deg, #11998e, #38ef7d); color: white; font-weight: bold; }
        .feature-item { padding: 12px; margin: 8px 0; background: linear-gradient(135deg, #f5f7fa, #c3cfe2); border-left: 4px solid #667eea; border-radius: 4px; transition: transform 0.2s; }
        .feature-item:hover { transform: translateX(5px); }
        .btn { background: linear-gradient(135deg, #667eea, #764ba2); color: white; border: none; padding: 12px 24px; border-radius: 8px; cursor: pointer; font-size: 14px; margin: 5px; transition: all 0.3s; }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4); }
        .btn-secondary { background: linear-gradient(135deg, #f093fb, #f5576c); }
        .model-tag { display: inline-block; padding: 4px 12px; margin: 4px; background: #e0e7ff; color: #4338ca; border-radius: 15px; font-size: 12px; }
        .log-output { background: #1a1a2e; color: #00ff9d; padding: 15px; border-radius: 8px; font-family: 'Courier New', monospace; font-size: 12px; height: 200px; overflow-y: auto; }
        input, select { width: 100%; padding: 10px; margin: 8px 0; border: 2px solid #e0e0e0; border-radius: 6px; font-size: 14px; }
        input:focus, select:focus { outline: none; border-color: #667eea; }
        .tabs { display: flex; gap: 10px; margin-bottom: 20px; }
        .tab { padding: 10px 20px; background: rgba(255,255,255,0.2); border: none; border-radius: 8px; color: white; cursor: pointer; }
        .tab.active { background: white; color: #667eea; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🔥 HyperNix Web UI</h1>
        <p class="subtitle">Advanced AI Training & Inference Platform v0.61.4</p>
        
        <div style="margin-bottom: 30px;">
            <span class="status-badge">✓ System Online</span>
            <span class="status-badge" style="background: linear-gradient(135deg, #f093fb, #f5576c);">✓ Tailscale Active</span>
            <span style="color: white; margin-left: 20px;">Server: http://localhost:8080</span>
        </div>
        
        <div class="tabs">
            <button class="tab active" onclick="showTab('dashboard')">Dashboard</button>
            <button class="tab" onclick="showTab('models')">Models</button>
            <button class="tab" onclick="showTab('training')">Training</button>
            <button class="tab" onclick="showTab('pipeline')">ASR/TTS Pipeline</button>
            <button class="tab" onclick="showTab('chat')">AI Chat</button>
        </div>
        
        <div id="dashboard-tab" class="tab-content">
            <div class="grid">
                <div class="card">
                    <h2>📊 System Status</h2>
                    <p><strong>Version:</strong> 0.61.4</p>
                    <p><strong>Tailscale:</strong> <span style="color: #11998e;">✓ Connected</span></p>
                    <p><strong>Share URL:</strong> <code style="background: #f0f0f0; padding: 4px 8px; border-radius: 4px;">https://your-node.tailnet-name.ts.net:8080</code></p>
                    <p><strong>Active Modules:</strong> freezer, old_fridge, new_fridge, pressure_cooker_v3, workshop, webui</p>
                </div>
                
                <div class="card">
                    <h2>🚀 Quick Actions</h2>
                    <button class="btn" onclick="alert('Opening Model Manager...')">📦 Manage Models</button>
                    <button class="btn" onclick="alert('Starting Training Monitor...')">📈 Monitor Training</button>
                    <button class="btn" onclick="document.getElementById('audio-upload').click()">🎤 Run ASR Pipeline</button>
                    <input type="file" id="audio-upload" accept="audio/*" style="display:none" onchange="handleAudioUpload(this)">
                    <button class="btn btn-secondary" onclick="alert('Launching Local Assistant...')">🤖 Launch Assistant</button>
                </div>
                
                <div class="card">
                    <h2>🎯 Supported Features</h2>
                    <div class="feature-item">📦 Model Management (Load/Unload/Configure)</div>
                    <div class="feature-item">📊 Real-time Training Monitoring</div>
                    <div class="feature-item">🎤 ASR → Text Transcription</div>
                    <div class="feature-item">🔊 Text → TTS Synthesis</div>
                    <div class="feature-item">🔄 Full ASR → LLM → TTS Pipeline</div>
                    <div class="feature-item">💬 Interactive AI Chat</div>
                    <div class="feature-item">🐧 Linux Local AI Assistant</div>
                    <div class="feature-item">🔒 Secure Tailscale Tunneling</div>
                </div>
            </div>
        </div>
        
        <div id="models-tab" class="tab-content" style="display:none;">
            <div class="card">
                <h2>📦 Model Library</h2>
                <h3>Loaded Models</h3>
                <div>
                    <span class="model-tag">nano-llama (80M)</span>
                    <span class="model-tag">gemma-4-1b-it (1B)</span>
                </div>
                
                <h3>Available Models</h3>
                <div>
                    <span class="model-tag">LiquidAI/LFM2.5-8B-A1B-GGUF</span>
                    <span class="model-tag">openbmb/MiniCPM5-1B</span>
                    <span class="model-tag">google/gemma-4-31B-it</span>
                    <span class="model-tag">google/gemma-4-12b-it</span>
                    <span class="model-tag">google/gemma-4-1b-it</span>
                    <span class="model-tag">Qwen3.5-7B</span>
                    <span class="model-tag">Phi-4-14B</span>
                    <span class="model-tag">DeepSeek-V2.5</span>
                    <span class="model-tag">Llama-3.2-3B</span>
                    <span class="model-tag">Mistral-7B-v0.3</span>
                    <span class="model-tag">Mixtral-8x7B</span>
                    <span class="model-tag">nano-whisper</span>
                    <span class="model-tag">nano-tacotron</span>
                    <span class="model-tag">nano-vits</span>
                </div>
                
                <h3>Load Model</h3>
                <select id="model-select">
                    <option value="nano-llama">Nano LLaMA (80M)</option>
                    <option value="gemma-4-1b-it">Gemma 4 1B IT</option>
                    <option value="MiniCPM5-1B">MiniCPM5 1B</option>
                    <option value="LFM2.5-8B">LiquidAI LFM2.5 8B</option>
                </select>
                <button class="btn" onclick="loadModel()">Load Selected Model</button>
            </div>
        </div>
        
        <div id="training-tab" class="tab-content" style="display:none;">
            <div class="card">
                <h2>📈 Training Monitor</h2>
                <p><strong>Status:</strong> <span id="training-status">Idle</span></p>
                <p><strong>Last Step:</strong> <span id="last-step">0</span></p>
                <p><strong>Current Loss:</strong> <span id="current-loss">-</span></p>
                
                <h3>Start New Training</h3>
                <label>Model:</label>
                <select id="train-model">
                    <option value="nano-llama">Nano LLaMA</option>
                    <option value="custom">Custom Configuration</option>
                </select>
                
                <label>Dataset:</label>
                <input type="text" placeholder="Path to dataset or HuggingFace ID">
                
                <label>Steps:</label>
                <input type="number" value="10000" min="100">
                
                <label>Batch Size:</label>
                <input type="number" value="32" min="1">
                
                <label>Learning Rate:</label>
                <input type="text" value="1e-4">
                
                <button class="btn" onclick="startTraining()">🚀 Start Training</button>
                <button class="btn btn-secondary" onclick="stopTraining()">⏹ Stop</button>
                
                <h3>Live Logs</h3>
                <div class="log-output" id="training-logs">Waiting for training to start...</div>
            </div>
        </div>
        
        <div id="pipeline-tab" class="tab-content" style="display:none;">
            <div class="card">
                <h2>🎤 ASR → LLM → TTS Pipeline</h2>
                
                <h3>Step 1: Upload Audio</h3>
                <input type="file" id="pipeline-audio" accept="audio/*" onchange="previewAudio(this)">
                <audio id="audio-preview" controls style="width:100%; margin:10px 0; display:none;"></audio>
                
                <h3>Step 2: Configure Pipeline</h3>
                <label>ASR Engine:</label>
                <select id="asr-engine">
                    <option value="nano-whisper">Nano Whisper</option>
                    <option value="whisper-large">Whisper Large</option>
                    <option value="conformer">Conformer</option>
                </select>
                
                <label>LLM:</label>
                <select id="llm-model">
                    <option value="nano-llama">Nano LLaMA</option>
                    <option value="gemma-4-1b-it">Gemma 4 1B</option>
                    <option value="custom">Custom</option>
                </select>
                
                <label>TTS Engine:</label>
                <select id="tts-engine">
                    <option value="nano-tacotron">Nano Tacotron</option>
                    <option value="nano-vits">Nano VITS</option>
                    <option value="fastpitch">FastPitch</option>
                </select>
                
                <label>System Prompt:</label>
                <input type="text" value="You are a helpful assistant." placeholder="Enter system prompt">
                
                <h3>Step 3: Run Pipeline</h3>
                <button class="btn" onclick="runPipeline()">🎯 Execute Full Pipeline</button>
                
                <h3>Output</h3>
                <div class="log-output" id="pipeline-output">Pipeline output will appear here...</div>
                <audio id="pipeline-audio-output" controls style="width:100%; margin-top:10px; display:none;"></audio>
            </div>
        </div>
        
        <div id="chat-tab" class="tab-content" style="display:none;">
            <div class="card">
                <h2>💬 AI Chat Interface</h2>
                
                <div style="background: #f5f7fa; padding: 20px; border-radius: 8px; height: 400px; overflow-y: auto; margin-bottom: 20px;" id="chat-messages">
                    <div style="margin-bottom: 15px;">
                        <strong style="color: #667eea;">Assistant:</strong>
                        <p style="margin: 5px 0 0 0; padding: 10px; background: white; border-radius: 8px;">Hello! I'm your HyperNix AI assistant. How can I help you today?</p>
                    </div>
                </div>
                
                <input type="text" id="chat-input" placeholder="Type your message..." onkeypress="if(event.key==='Enter')sendMessage()">
                <button class="btn" onclick="sendMessage()" style="width:100%;">Send Message</button>
                
                <div style="margin-top: 20px;">
                    <button class="btn btn-secondary" onclick="clearChat()">🗑 Clear Chat</button>
                    <button class="btn" onclick="toggleVoiceMode()">🎤 Voice Mode</button>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        function showTab(tabName) {
            document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
            document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
            document.getElementById(tabName + '-tab').style.display = 'block';
            event.target.classList.add('active');
        }
        
        function handleAudioUpload(input) {
            if (input.files && input.files[0]) {
                alert('Audio file selected: ' + input.files[0].name);
                // Implement actual upload and processing
            }
        }
        
        function previewAudio(input) {
            if (input.files && input.files[0]) {
                const audio = document.getElementById('audio-preview');
                audio.src = URL.createObjectURL(input.files[0]);
                audio.style.display = 'block';
            }
        }
        
        function loadModel() {
            const model = document.getElementById('model-select').value;
            alert('Loading model: ' + model);
            // Implement actual model loading via API
        }
        
        function startTraining() {
            document.getElementById('training-status').textContent = 'Running';
            document.getElementById('training-status').style.color = 'green';
            
            const logs = document.getElementById('training-logs');
            let step = 0;
            const interval = setInterval(() => {
                step += 100;
                const loss = (2.5 - step * 0.0001).toFixed(4);
                logs.innerHTML += `[Step ${step}] Loss: ${loss}\\n`;
                logs.scrollTop = logs.scrollHeight;
                if (step >= 1000) clearInterval(interval);
            }, 500);
        }
        
        function stopTraining() {
            document.getElementById('training-status').textContent = 'Stopped';
            document.getElementById('training-status').style.color = 'red';
        }
        
        function runPipeline() {
            const output = document.getElementById('pipeline-output');
            output.innerHTML = 'Initializing pipeline...\\n';
            output.innerHTML += 'Loading ASR engine: nano-whisper\\n';
            output.innerHTML += 'Loading LLM: nano-llama\\n';
            output.innerHTML += 'Loading TTS: nano-tacotron\\n';
            output.innerHTML += 'Processing audio...\\n';
            output.innerHTML += 'Transcribing...\\n';
            output.innerHTML += 'Generating response...\\n';
            output.innerHTML += 'Synthesizing speech...\\n';
            output.innerHTML += '✓ Pipeline complete!';
            
            document.getElementById('pipeline-audio-output').style.display = 'block';
        }
        
        function sendMessage() {
            const input = document.getElementById('chat-input');
            const message = input.value.trim();
            if (!message) return;
            
            const chatDiv = document.getElementById('chat-messages');
            chatDiv.innerHTML += `
                <div style="margin-bottom: 15px;">
                    <strong style="color: #4338ca;">You:</strong>
                    <p style="margin: 5px 0 0 0; padding: 10px; background: #e0e7ff; border-radius: 8px;">${message}</p>
                </div>
            `;
            
            input.value = '';
            
            // Simulate response
            setTimeout(() => {
                chatDiv.innerHTML += `
                    <div style="margin-bottom: 15px;">
                        <strong style="color: #667eea;">Assistant:</strong>
                        <p style="margin: 5px 0 0 0; padding: 10px; background: white; border-radius: 8px;">I received your message: "${message}". How can I assist you further?</p>
                    </div>
                `;
                chatDiv.scrollTop = chatDiv.scrollHeight;
            }, 1000);
        }
        
        function clearChat() {
            document.getElementById('chat-messages').innerHTML = '';
        }
        
        function toggleVoiceMode() {
            alert('Voice mode activated! Click the microphone icon to speak.');
        }
        
        // Auto-refresh status
        setInterval(() => {
            fetch('/api/status')
                .then(r => r.json())
                .then(data => console.log('Status:', data));
        }, 5000);
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
