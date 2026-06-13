const panels = document.querySelectorAll(".panel");
const navButtons = document.querySelectorAll(".nav button");

function showPanel(id) {
  panels.forEach((p) => p.classList.toggle("active", p.id === id));
  navButtons.forEach((b) => b.classList.toggle("active", b.dataset.panel === id));
}

navButtons.forEach((btn) => {
  btn.addEventListener("click", () => showPanel(btn.dataset.panel));
});

async function refreshStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    document.getElementById("version-badge").textContent = `v${data.version}`;
    document.getElementById("version-stat").textContent = data.version;
    document.getElementById("host-badge").textContent = data.url || window.location.origin;

    const tsBadge = document.getElementById("tailscale-badge");
    if (data.tailscale && data.tailscale.enabled) {
      tsBadge.classList.remove("hidden");
      tsBadge.textContent = data.tailscale.hostname
        ? `Tailscale · ${data.tailscale.hostname}`
        : "Tailscale · active";
    } else {
      tsBadge.classList.add("hidden");
    }

    const tags = document.getElementById("module-tags");
    if (tags && data.modules) {
      tags.innerHTML = data.modules
        .map((m) => `<span class="tag on">${m}</span>`)
        .join("");
    }
  } catch (err) {
    console.warn("status fetch failed", err);
  }
}

let trainTimer = null;
function toggleTrain() {
  const btn = document.getElementById("train-btn");
  const log = document.getElementById("train-log");
  const status = document.getElementById("train-status");
  if (trainTimer) {
    clearInterval(trainTimer);
    trainTimer = null;
    btn.textContent = "Start training";
    status.textContent = "Idle";
    return;
  }
  btn.textContent = "Stop";
  status.textContent = "Running";
  log.textContent = "> PressureCookerV3Plus ready\n> Abbicus curriculum active\n";
  let step = 0;
  trainTimer = setInterval(() => {
    step += 5;
    const loss = (2.2 * Math.exp(-step * 0.002) + Math.random() * 0.04).toFixed(4);
    document.getElementById("train-step").textContent = step;
    document.getElementById("train-loss").textContent = loss;
    log.textContent += `[${String(step).padStart(5, "0")}] loss=${loss}\n`;
    log.scrollTop = log.scrollHeight;
    if (step >= 500) {
      clearInterval(trainTimer);
      trainTimer = null;
      btn.textContent = "Start training";
      status.textContent = "Done";
    }
  }, 400);
}

function sendChat() {
  const input = document.getElementById("chat-input");
  const text = input.value.trim();
  if (!text) return;
  const box = document.getElementById("chat-msgs");
  box.innerHTML += `<div class="msg user"><span class="bubble">${text}</span></div>`;
  input.value = "";
  box.scrollTop = box.scrollHeight;
  setTimeout(() => {
    box.innerHTML += `<div class="msg bot"><span class="bubble">Acknowledged. HyperNix v0.70.3b2 online.</span></div>`;
    box.scrollTop = box.scrollHeight;
  }, 500);
}

document.getElementById("train-btn")?.addEventListener("click", toggleTrain);
document.getElementById("chat-send")?.addEventListener("click", sendChat);
document.getElementById("chat-input")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendChat();
});

refreshStatus();
setInterval(refreshStatus, 15000);
