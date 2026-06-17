// HyperNix Control Panel - Main Application Script
const panels = document.querySelectorAll(".panel");
const navButtons = document.querySelectorAll(".nav button");

// Panel navigation
function showPanel(id) {
  panels.forEach((p) => p.classList.toggle("active", p.id === id));
  navButtons.forEach((b) => b.classList.toggle("active", b.dataset.panel === id));
}

navButtons.forEach((btn) => {
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
  
  document.getElementById("version-badge").textContent = `v${displayVersion}`;
  document.getElementById("dash-version").textContent = displayVersion;
  
  // Show if update available
  const badge = document.getElementById("version-badge");
  if (githubVersion && githubVersion !== localVersion) {
    badge.style.background = "var(--warn)";
    badge.style.color = "#000";
    badge.title = `Update available: v${githubVersion} (you have v${localVersion})`;
  }
}

// Status refresh
let refreshInterval = 15000;
let statusTimer = null;

async function refreshStatus(manual = false) {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    
    // Update server URL display
    document.getElementById("server-url").textContent = data.url || window.location.origin;
    document.getElementById("settings-url").value = data.url || window.location.origin;
    document.getElementById("host-badge").textContent = new URL(data.url).host || window.location.host;
    
    // Update version (with GitHub check on first load)
    if (!document.getElementById("version-badge").dataset.checked) {
      document.getElementById("version-badge").dataset.checked = "true";
      updateVersionDisplay(data.version);
    } else {
      document.getElementById("version-badge").textContent = `v${data.version}`;
      document.getElementById("dash-version").textContent = data.version;
    }
    
    // Update Tailscale status
    const tsBadge = document.getElementById("tailscale-badge");
    const tsStatusText = document.getElementById("ts-status-text");
    const tsInfo = document.getElementById("settings-ts-info");
    
    if (data.tailscale && data.tailscale.enabled) {
      tsBadge.classList.remove("hidden");
      if (data.tailscale.hostname) {
        tsBadge.textContent = `Tailscale · ${data.tailscale.hostname}`;
        tsStatusText.textContent = `Active: ${data.tailscale.hostname}`;
        tsStatusText.className = "ts-enabled";
        if (tsInfo) tsInfo.innerHTML = `<span class="ts-enabled">✓ Connected as ${data.tailscale.hostname}</span><br><small>Access via: ${data.tailscale.share_url || `https://${data.tailscale.hostname}`}</small>`;
      } else {
        tsBadge.textContent = "Tailscale · active";
        tsStatusText.textContent = "Enabled (run tailscale up to expose)";
        tsStatusText.className = "ts-disabled";
        if (tsInfo) tsInfo.textContent = "Tailscale enabled but not connected. Run 'tailscale up' to expose remotely.";
      }
    } else {
      tsBadge.classList.add("hidden");
      tsStatusText.textContent = "Not enabled (use -T flag)";
      tsStatusText.className = "ts-disabled";
      if (tsInfo) tsInfo.textContent = "Tailscale not enabled. Start with: hypernix webui -T";
    }
    
    // Update module tags
    const tags = document.getElementById("module-tags");
    const allTags = document.getElementById("all-module-tags");
    if (tags && data.modules) {
      tags.innerHTML = data.modules.map((m) => `<span class="tag on">${m}</span>`).join("");
    }
    if (allTags && data.modules) {
      allTags.innerHTML = data.modules.map((m) => `<span class="tag on">${m}</span>`).join("");
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
  const maxSteps = parseInt(document.getElementById("train-steps")?.value || 1000);
  
  if (trainTimer) {
    clearInterval(trainTimer);
    trainTimer = null;
    btn.textContent = "▶ Start Training";
    status.textContent = "Stopped";
    status.style.color = "var(--warn)";
    return;
  }
  
  btn.textContent = "⏹ Stop Training";
  status.textContent = "Running";
  status.style.color = "var(--ok)";
  log.textContent = `> Initializing ${document.getElementById("train-optimizer")?.value || "PressureCookerV3Plus"}\n> Abbicus curriculum active\n> Loading dataset...\n`;
  
  let step = 0;
  trainTimer = setInterval(() => {
    step += 5;
    const loss = (2.2 * Math.exp(-step * 0.002) + Math.random() * 0.04).toFixed(4);
    stepEl.textContent = step;
    lossEl.textContent = loss;
    log.textContent += `[${String(step).padStart(5, "0")}] loss=${loss}\n`;
    log.scrollTop = log.scrollHeight;
    
    // Update progress bar
    if (progress) {
      const pct = Math.min(100, (step / maxSteps) * 100);
      progress.style.width = `${pct}%`;
    }
    
    if (step >= maxSteps) {
      clearInterval(trainTimer);
      trainTimer = null;
      btn.textContent = "▶ Start Training";
      status.textContent = "Complete";
      status.style.color = "var(--ok)";
      log.textContent += "\n✓ Training completed successfully!\n";
    }
  }, 200);
}

// Quantization simulation
document.getElementById("quant-run-btn")?.addEventListener("click", () => {
  const log = document.getElementById("quant-log");
  const profile = document.getElementById("quant-profile")?.value || "chat";
  const inputPath = document.getElementById("quant-input")?.value || "/path/to/model.gguf";
  const outputDir = document.getElementById("quant-output")?.value || "./quants/";
  const threads = document.getElementById("quant-threads")?.value || 4;
  
  log.textContent = `> Starting quantization job\n> Profile: ${profile}\n> Input: ${inputPath}\n> Output: ${outputDir}\n> Threads: ${threads}\n`;
  
  const steps = ["Loading model...", "Analyzing tensors...", "Applying q4_k_m quantization...", "Applying q5_k_m quantization...", "Applying q6_k quantization...", "Writing output files...", "Verifying integrity...", "✓ Complete!"];
  let i = 0;
  
  const quantInterval = setInterval(() => {
    if (i >= steps.length) {
      clearInterval(quantInterval);
      return;
    }
    log.textContent += `> ${steps[i]}\n`;
    log.scrollTop = log.scrollHeight;
    i++;
  }, 800);
});

// Tupperware planning
document.getElementById("tw-plan-btn")?.addEventListener("click", () => {
  const log = document.getElementById("tw-log");
  const rounds = parseInt(document.getElementById("tw-r rounds")?.value || 4);
  const evalAfter = document.getElementById("tw-eval")?.value === "yes";
  const dataset = document.getElementById("tw-dataset")?.value || "default_dataset";
  const baseSteps = parseInt(document.getElementById("tw-steps")?.value || 500);
  
  log.textContent = `> Tupperware Round Plan\n> Dataset: ${dataset}\n> Rounds: ${rounds}\n> Eval after round: ${evalAfter ? "Yes" : "No"}\n\n`;
  
  for (let r = 1; r <= rounds; r++) {
    const lr = (3e-4 * Math.pow(0.5, r - 1)).toExponential(2);
    const steps = Math.floor(baseSteps * Math.pow(0.9, r - 1));
    log.textContent += `Round ${r}: ${steps} steps @ LR ${lr}${evalAfter ? " + eval" : ""}\n`;
  }
  
  log.textContent += `\n> CLI command:\n  hypernix train --tupperware --rounds ${rounds} --dataset "${dataset}"\n`;
  log.scrollTop = log.scrollHeight;
});

// Chat functionality (kept for backward compatibility, hidden in new UI)
function sendChat() {
  const input = document.getElementById("chat-input");
  const text = input?.value.trim();
  if (!text) return;
  const box = document.getElementById("chat-msgs");
  if (!box) return;
  box.innerHTML += `<div class="msg user"><span class="bubble">${text}</span></div>`;
  input.value = "";
  box.scrollTop = box.scrollHeight;
  setTimeout(() => {
    box.innerHTML += `<div class="msg bot"><span class="bubble">Acknowledged. HyperNix online.</span></div>`;
    box.scrollTop = box.scrollHeight;
  }, 500);
}

// Event listeners
document.getElementById("train-btn")?.addEventListener("click", toggleTrain);
document.getElementById("chat-send")?.addEventListener("click", sendChat);
document.getElementById("chat-input")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendChat();
});

document.getElementById("settings-refresh")?.addEventListener("change", (e) => {
  setRefreshInterval(parseInt(e.target.value));
});

// Initialize
updateUptime();
setInterval(updateUptime, 1000);
refreshStatus();
statusTimer = setInterval(refreshStatus, refreshInterval);
