// HyperNix Control Panel - Main Application Script

// Panel navigation
function showPanel(id) {
  // Hide all panels
  document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
  // Show target panel
  const target = document.getElementById(id);
  if (target) target.classList.add("active");
  
  // Update nav buttons
  document.querySelectorAll(".nav-item").forEach((b) => {
    b.classList.toggle("active", b.dataset.panel === id);
  });
  
  // Update breadcrumb
  const breadcrumbEl = document.getElementById("current-panel");
  if (breadcrumbEl) {
    const labelMap = {
      "dashboard": "Dashboard",
      "script-builder": "Script Builder",
      "training": "Training",
      "quantize": "Quantize",
      "tupperware": "Tupperware",
      "modules": "Modules",
      "chat": "Assistant Chat",
      "settings": "Settings"
    };
    breadcrumbEl.textContent = labelMap[id] || id.charAt(0).toUpperCase() + id.slice(1).replace("-", " ");
  }
}

// Initialize nav buttons
document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => showPanel(btn.dataset.panel));
});

// Uptime tracking
let startTime = Date.now();
function updateUptime() {
  const elapsed = Math.floor((Date.now() - startTime) / 1000);
  const el = document.getElementById("dash-uptime");
  if (el) {
    if (elapsed < 60) el.textContent = `${elapsed}s`;
    else if (elapsed < 3600) el.textContent = `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`;
    else el.textContent = `${Math.floor(elapsed / 3600)}h ${Math.floor((elapsed % 3600) / 60)}m`;
  }
}

// Fetch version from GitHub Pages
async function fetchGitHubVersion() {
  try {
    const res = await fetch("https://ray0rf1re.github.io/hypernix/version.json", { 
      cache: "no-cache",
      signal: AbortSignal.timeout(5000)
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    return data.version || null;
  } catch (err) {
    console.log("GitHub version fetch failed, using local:", err.message);
    return null;
  }
}

// Auto-update version display
async function updateVersionDisplay(localVersion) {
  const githubVersion = await fetchGitHubVersion();
  const displayVersion = githubVersion || localVersion;
  
  const sidebarVersion = document.getElementById("sidebar-version");
  const dashVersion = document.getElementById("dash-version");
  const updateIndicator = document.getElementById("update-indicator");
  
  if (sidebarVersion) sidebarVersion.textContent = `v${displayVersion}`;
  if (dashVersion) dashVersion.textContent = displayVersion;
  
  // Show if update available
  if (githubVersion && githubVersion !== localVersion) {
    if (updateIndicator) {
      updateIndicator.classList.remove("hidden");
      updateIndicator.title = `Update available: v${githubVersion} (you have v${localVersion})`;
    }
  }
}

// Status refresh
let refreshInterval = 15000;
let statusTimer = null;

async function refreshStatus(manual = false) {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    
    // Update Tailscale chip
    const tsChip = document.getElementById("tailscale-chip");
    if (tsChip) {
      const tsText = tsChip.querySelector(".chip-text");
      if (data.tailscale && data.tailscale.enabled) {
        if (data.tailscale.hostname) {
          tsChip.title = `Tailscale: ${data.tailscale.hostname}`;
          if (tsText) tsText.textContent = data.tailscale.hostname;
        } else {
          if (tsText) tsText.textContent = "Enabled";
        }
      } else {
        if (tsText) tsText.textContent = "Local Only";
      }
    }
    
    // Update host display
    const hostDisplay = document.getElementById("host-display");
    if (hostDisplay) {
      hostDisplay.textContent = new URL(data.url).host || window.location.host;
    }
    
    // Update version (with GitHub check on first load)
    const versionChecked = document.getElementById("version-checked");
    if (!versionChecked) {
      const meta = document.createElement("meta");
      meta.id = "version-checked";
      meta.name = "version-checked";
      meta.content = "true";
      document.head.appendChild(meta);
      updateVersionDisplay(data.version);
    }
    
    // Update dashboard stats
    const dashModulesCount = document.getElementById("dash-modules-count");
    if (dashModulesCount && data.modules) {
      dashModulesCount.textContent = data.modules.length;
    }
    
    const dashTsStatus = document.getElementById("dash-ts-status");
    if (dashTsStatus) {
      if (data.tailscale && data.tailscale.enabled) {
        dashTsStatus.textContent = data.tailscale.hostname ? "Connected" : "Enabled";
      } else {
        dashTsStatus.textContent = "Disabled";
      }
    }
    
    // Update module list on dashboard
    const dashModuleList = document.getElementById("dash-module-list");
    if (dashModuleList && data.modules) {
      dashModuleList.innerHTML = data.modules.map((m) => 
        `<div class="module-item"><span class="module-name">${m}</span><span class="module-status">✓</span></div>`
      ).join("");
    }
    
    if (manual) {
      alert("Status refreshed successfully!");
    }
  } catch (err) {
    console.warn("status fetch failed", err);
    if (manual) {
      alert("Failed to refresh status: " + err.message);
    }
  }
}

function setRefreshInterval(ms) {
  refreshInterval = ms;
  if (statusTimer) clearInterval(statusTimer);
  statusTimer = setInterval(refreshStatus, ms);
}

// Training simulation
let trainTimer = null;
function toggleTrain() {
  const btn = document.getElementById("train-btn");
  const log = document.getElementById("train-log");
  const status = document.getElementById("train-status");
  const progress = document.getElementById("train-progress");
  const stepEl = document.getElementById("train-step");
  const lossEl = document.getElementById("train-loss");
  const progressPercent = document.getElementById("progress-percent");
  const maxSteps = parseInt(document.getElementById("train-steps")?.value || 1000);
  
  if (!btn || !log) return;
  
  if (trainTimer) {
    clearInterval(trainTimer);
    trainTimer = null;
    btn.innerHTML = '<span class="btn-icon">▶</span><span>Start Training</span>';
    if (status) {
      status.textContent = "Stopped";
      status.style.color = "var(--warn)";
    }
    return;
  }
  
  btn.innerHTML = '<span class="btn-icon">⏹</span><span>Stop Training</span>';
  if (status) {
    status.textContent = "Running";
    status.style.color = "var(--ok)";
  }
  log.innerHTML = `> Initializing ${document.getElementById("train-optimizer")?.value || "PressureCookerV3Plus"}\n> Abbicus curriculum active\n> Loading dataset...\n`;
  
  let step = 0;
  trainTimer = setInterval(() => {
    step += 5;
    const loss = (2.2 * Math.exp(-step * 0.002) + Math.random() * 0.04).toFixed(4);
    if (stepEl) stepEl.textContent = step;
    if (lossEl) lossEl.textContent = loss;
    log.innerHTML += `[${String(step).padStart(5, "0")}] loss=${loss}\n`;
    log.scrollTop = log.scrollHeight;
    
    // Update progress bar
    if (progress) {
      const pct = Math.min(100, (step / maxSteps) * 100);
      progress.style.width = `${pct}%`;
    }
    if (progressPercent) {
      progressPercent.textContent = `${Math.min(100, Math.round((step / maxSteps) * 100))}%`;
    }
    
    if (step >= maxSteps) {
      clearInterval(trainTimer);
      trainTimer = null;
      btn.innerHTML = '<span class="btn-icon">▶</span><span>Start Training</span>';
      if (status) {
        status.textContent = "Complete";
        status.style.color = "var(--ok)";
      }
      log.innerHTML += "\n✓ Training completed successfully!\n";
    }
  }, 200);
}

// Quantization simulation
document.getElementById("quant-run-btn")?.addEventListener("click", () => {
  const log = document.getElementById("quant-log");
  if (!log) return;
  
  const profile = document.getElementById("quant-profile")?.value || "chat";
  const inputPath = document.getElementById("quant-input")?.value || "/path/to/model.gguf";
  const outputDir = document.getElementById("quant-output")?.value || "./quants/";
  const threads = document.getElementById("quant-threads")?.value || 4;
  
  log.innerHTML = `> Starting quantization job\n> Profile: ${profile}\n> Input: ${inputPath}\n> Output: ${outputDir}\n> Threads: ${threads}\n`;
  
  const steps = ["Loading model...", "Analyzing tensors...", "Applying q4_k_m quantization...", "Applying q5_k_m quantization...", "Applying q6_k quantization...", "Writing output files...", "Verifying integrity...", "✓ Complete!"];
  let i = 0;
  
  const quantInterval = setInterval(() => {
    if (i >= steps.length) {
      clearInterval(quantInterval);
      return;
    }
    log.innerHTML += `> ${steps[i]}\n`;
    log.scrollTop = log.scrollHeight;
    i++;
  }, 800);
});

// Tupperware planning
document.getElementById("tw-plan-btn")?.addEventListener("click", () => {
  const log = document.getElementById("tw-log");
  if (!log) return;
  
  const rounds = parseInt(document.getElementById("tw-rounds")?.value || 4);
  const evalAfter = document.getElementById("tw-eval")?.value === "yes";
  const dataset = document.getElementById("tw-dataset")?.value || "default_dataset";
  const baseSteps = parseInt(document.getElementById("tw-steps")?.value || 500);
  
  log.innerHTML = `> Tupperware Round Plan\n> Dataset: ${dataset}\n> Rounds: ${rounds}\n> Eval after round: ${evalAfter ? "Yes" : "No"}\n\n`;
  
  for (let r = 1; r <= rounds; r++) {
    const lr = (3e-4 * Math.pow(0.5, r - 1)).toExponential(2);
    const steps = Math.floor(baseSteps * Math.pow(0.9, r - 1));
    log.innerHTML += `Round ${r}: ${steps} steps @ LR ${lr}${evalAfter ? " + eval" : ""}\n`;
  }
  
  log.innerHTML += `\n> CLI command:\n  hypernix train --tupperware --rounds ${rounds} --dataset "${dataset}"\n`;
  log.scrollTop = log.scrollHeight;
});

// Script Builder - Block drag and drop
let draggedBlockType = null;
let selectedBlock = null;
let blockCounter = 0;

// Setup draggable blocks in palette
document.querySelectorAll(".block-palette .block").forEach((block) => {
  block.addEventListener("dragstart", (e) => {
    draggedBlockType = block.dataset.blockType;
    e.dataTransfer.setData("text/plain", draggedBlockType);
    e.dataTransfer.effectAllowed = "copy";
  });
});

// Setup canvas drop zone
const canvas = document.getElementById("workflow-canvas");
const placeholder = document.getElementById("canvas-placeholder");

if (canvas) {
  canvas.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    canvas.classList.add("drag-over");
  });
  
  canvas.addEventListener("dragleave", () => {
    canvas.classList.remove("drag-over");
  });
  
  canvas.addEventListener("drop", (e) => {
    e.preventDefault();
    canvas.classList.remove("drag-over");
    
    const blockType = e.dataTransfer.getData("text/plain") || draggedBlockType;
    if (!blockType) return;
    
    // Hide placeholder
    if (placeholder) placeholder.style.display = "none";
    
    // Create new block instance
    createWorkflowBlock(blockType);
  });
}

function createWorkflowBlock(type) {
  if (!canvas) return;
  
  blockCounter++;
  const blockId = `block-${blockCounter}`;
  
  const blockNames = {
    "download": "Download",
    "pressure-cooker": "Pressure Cooker",
    "abbicus": "Abbicus",
    "compute-framework": "Compute Framework",
    "quantize": "Quantize",
    "tupperware": "Tupperware",
    "sink": "Sink"
  };
  
  const blockIcons = {
    "download": "⬇️",
    "pressure-cooker": "🔥",
    "abbicus": "📈",
    "compute-framework": "💻",
    "quantize": "📦",
    "tupperware": "🔄",
    "sink": "💾"
  };
  
  const blockEl = document.createElement("div");
  blockEl.className = "workflow-block";
  blockEl.dataset.blockId = blockId;
  blockEl.dataset.blockType = type;
  blockEl.innerHTML = `
    <div class="workflow-block-header">
      <span class="workflow-block-icon">${blockIcons[type] || "🧩"}</span>
      <span class="workflow-block-title">${blockNames[type] || type}</span>
      <button class="workflow-block-remove" onclick="removeBlock('${blockId}')">×</button>
    </div>
    <div class="workflow-block-body">
      <small>ID: ${blockId}</small>
    </div>
  `;
  
  blockEl.addEventListener("click", () => selectBlock(blockId, type));
  canvas.appendChild(blockEl);
}

function removeBlock(blockId) {
  const block = document.querySelector(`[data-block-id="${blockId}"]`);
  if (block) {
    block.remove();
    // Show placeholder if no blocks left
    if (canvas && canvas.querySelectorAll(".workflow-block").length === 0) {
      if (placeholder) placeholder.style.display = "flex";
    }
    // Clear config panel if this was selected
    if (selectedBlock === blockId) {
      selectedBlock = null;
      const configPanel = document.getElementById("block-config");
      if (configPanel) {
        configPanel.innerHTML = '<h3>Configuration</h3><p class="config-hint">Select a block to configure</p>';
      }
    }
  }
}

function selectBlock(blockId, type) {
  selectedBlock = blockId;
  
  // Remove selection from all blocks
  document.querySelectorAll(".workflow-block").forEach((b) => b.classList.remove("selected"));
  
  // Add selection to clicked block
  const block = document.querySelector(`[data-block-id="${blockId}"]`);
  if (block) block.classList.add("selected");
  
  // Show configuration panel
  const configPanel = document.getElementById("block-config");
  if (!configPanel) return;
  
  const blockNames = {
    "download": "Download",
    "pressure-cooker": "Pressure Cooker",
    "abbicus": "Abbicus",
    "compute-framework": "Compute Framework",
    "quantize": "Quantize",
    "tupperware": "Tupperware",
    "sink": "Sink"
  };
  
  configPanel.innerHTML = `
    <h3>${blockNames[type] || type} Config</h3>
    <div class="config-form">
      <div class="form-group">
        <label>Block ID</label>
        <input type="text" value="${blockId}" disabled>
      </div>
      <div class="form-group">
        <label>Notes</label>
        <textarea placeholder="Add notes for this block..."></textarea>
      </div>
      <button class="btn secondary" onclick="saveBlockConfig('${blockId}')">Save Config</button>
    </div>
  `;
}

function saveBlockConfig(blockId) {
  alert(`Configuration saved for ${blockId}`);
}

function clearWorkspace() {
  if (!canvas) return;
  canvas.querySelectorAll(".workflow-block").forEach((b) => b.remove());
  if (placeholder) placeholder.style.display = "flex";
  selectedBlock = null;
  const configPanel = document.getElementById("block-config");
  if (configPanel) {
    configPanel.innerHTML = '<h3>Configuration</h3><p class="config-hint">Select a block to configure</p>';
  }
}

function exportScript() {
  const blocks = Array.from(document.querySelectorAll(".workflow-block")).map((b) => ({
    id: b.dataset.blockId,
    type: b.dataset.blockType
  }));
  
  const script = {
    name: "My HyperNix Workflow",
    version: "1.0",
    blocks: blocks
  };
  
  const json = JSON.stringify(script, null, 2);
  const blob = new Blob([json], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "hypernix-workflow.json";
  a.click();
  URL.revokeObjectURL(url);
}

function runScript() {
  const blocks = document.querySelectorAll(".workflow-block");
  if (blocks.length === 0) {
    alert("Add blocks to your workflow first!");
    return;
  }
  
  alert(`Running workflow with ${blocks.length} block(s)...\nCheck the training panel for progress.`);
  showPanel("training");
}

// Event listeners
document.getElementById("train-btn")?.addEventListener("click", toggleTrain);

document.getElementById("settings-refresh")?.addEventListener("change", (e) => {
  setRefreshInterval(parseInt(e.target.value));
});

// Chat functionality
let chatHistory = [];

function addMessage(content, isUser = false) {
  const messagesContainer = document.getElementById("chat-messages");
  if (!messagesContainer) return;
  
  const messageEl = document.createElement("div");
  messageEl.className = `message ${isUser ? "user" : "assistant"}`;
  messageEl.innerHTML = `
    <div class="message-avatar">${isUser ? "👤" : "🤖"}</div>
    <div class="message-content">
      <p>${content}</p>
    </div>
  `;
  messagesContainer.appendChild(messageEl);
  messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function generateResponse(question) {
  const q = question.toLowerCase();
  
  // Training-related responses
  if (q.includes("train") || q.includes("training")) {
    if (q.includes("start") || q.includes("begin")) {
      return `To start training:\n1. Go to the <strong>Training</strong> panel\n2. Select your optimizer (PressureCookerV3Plus recommended)\n3. Choose quant dtype (FP16 for quality, FP8 for speed)\n4. Set learning rate, batch size, and max steps\n5. Click <strong>Start Training</strong>\n\nOr use CLI: <code>hypernix train --optimizer PressureCookerV3Plus --lr 3e-4</code>`;
    }
    return `Training in HyperNix uses our advanced modules:\n• <strong>PressureCookerV3</strong> - QAT with gradient checkpointing\n• <strong>Abbicus</strong> - Dynamic curriculum learning\n• <strong>ComputeFramework</strong> - Hardware abstraction\n\nConfigure settings in the Training panel or use CLI flags.`;
  }
  
  // Quantization responses
  if (q.includes("quant") || q.includes("gguf") || q.includes("profile")) {
    return `<strong>Quantization Profiles:</strong>\n• <strong>Chat</strong> → q4_k_m, q5_k_m, q6_k (balanced)\n• <strong>Code</strong> → q5_k_m, q6_k, q8_0 (higher precision)\n• <strong>Edge</strong> → q4_k_m, iq4_xs, q3_k_m (small size)\n• <strong>Quality</strong> → q6_k, q8_0, f16 (best quality)\n\nUse the Quantize panel to run jobs.`;
  }
  
  // Tupperware responses
  if (q.includes("tupperware") || q.includes("round") || q.includes("dataset")) {
    return `<strong>Tupperware</strong> splits datasets into training rounds:\n1. Go to Tupperware panel\n2. Set number of rounds (4 recommended)\n3. Enable eval after each round if needed\n4. Enter dataset path\n5. Click <strong>Generate Plan</strong>\n\nEach round gets progressive LR decay and step reduction.`;
  }
  
  // Modules responses
  if (q.includes("module") || q.includes("active") || q.includes("using")) {
    return `Check the <strong>Modules</strong> panel for active modules.\n\nThe dashboard also shows active modules in real-time. Currently loaded modules are fetched from the backend and displayed with status indicators.`;
  }
  
  // Script builder responses
  if (q.includes("script") || q.includes("block") || q.includes("workflow")) {
    return `<strong>Script Builder</strong> lets you create visual workflows:\n1. Drag blocks from the palette\n2. Drop them on the canvas\n3. Configure each block by clicking it\n4. Export as JSON or run directly\n\nBlocks: Download, Pressure Cooker, Abbicus, Compute Framework, Quantize, Tupperware, Sink`;
  }
  
  // Default response
  return `I can help with:\n• <strong>Training</strong> - Setup and monitor training runs\n• <strong>Quantization</strong> - GGUF profiles and jobs\n• <strong>Tupperware</strong> - Dataset round planning\n• <strong>Script Builder</strong> - Visual workflow creation\n• <strong>Modules</strong> - Check active components\n\nAsk me anything about HyperNix!`;
}

function sendSuggestion(text) {
  const input = document.getElementById("chat-input");
  if (input) {
    input.value = text;
  }
  sendMessage();
}

function sendMessage() {
  const input = document.getElementById("chat-input");
  if (!input) return;
  
  const text = input.value.trim();
  if (!text) return;
  
  // Add user message
  addMessage(text, true);
  chatHistory.push({ role: "user", content: text });
  input.value = "";
  
  // Simulate thinking delay then respond
  setTimeout(() => {
    const response = generateResponse(text);
    addMessage(response, false);
    chatHistory.push({ role: "assistant", content: response });
  }, 600 + Math.random() * 400);
}

document.getElementById("chat-send-btn")?.addEventListener("click", sendMessage);

document.getElementById("chat-input")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

// Initialize
updateUptime();
setInterval(updateUptime, 1000);
refreshStatus();
statusTimer = setInterval(refreshStatus, refreshInterval);
