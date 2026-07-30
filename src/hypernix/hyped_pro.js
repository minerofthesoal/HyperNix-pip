#!/usr/bin/env node
"use strict";
/**
 * hyped+ (hyped-pro) — TypeScript TUI Agent CLI for HyperNix.
 *
 * The TUI itself (footer/palette/keypress engine below) is pure Node and
 * has no model or provider logic of its own. Every real operation —
 * cloud API calls, local HuggingFace downloads, local inference, the T1
 * Gatekeeper quota layer, and the model/provider catalog — is delegated
 * to a single Python worker process (`python3 -m hypernix.hyped_pro_bridge
 * serve`, see the Bridge class below) so there is exactly one
 * implementation of "how hyped-pro talks to a model", shared with the
 * hyped-pro GUI (`hyped_pro_gui.py`). Nothing here fabricates a reply —
 * every chat turn is a real bridge round-trip that either returns a real
 * model response or a real, coded error (see ERROR CODES below).
 *
 * Compiled with `tsc` (see tsconfig.json) to hyped_pro.js, which is what
 * hyped_pro.py actually spawns — edit this file, not the compiled output.
 *
 * ERROR CODES (printed to the terminal, never swallowed):
 *   HPT-BRIDGE-001  could not spawn the Python bridge process
 *   HPT-BRIDGE-002  the Python bridge process exited unexpectedly
 *   HPT-BRIDGE-003  malformed JSON from the Python bridge
 *   HPT-CATALOG-001 could not load the model/provider catalog at startup
 *   HPT-CATALOG-002 the catalog response was malformed
 *   HPT-GUI-001     could not launch the hyped-pro GUI
 *   (HPC-*, HPB-* codes surfacing from a bridge call originate in Python —
 *    see hypernix/hyped_pro_core.py and hyped_pro_bridge.py.)
 */
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.THEMES = exports.COMMANDS = exports.SKILLS = exports.PROVIDERS = exports.MODELS = void 0;
exports.main = main;
exports.estimatePrice = estimatePrice;
exports.compactPrompt = compactPrompt;
exports.letterFilter = letterFilter;
const fs = __importStar(require("fs"));
const os = __importStar(require("os"));
const path = __importStar(require("path"));
const readline = __importStar(require("readline"));
const child_process_1 = require("child_process");
const VERSION = "0.71.4b6";
const NL = "\r\n"; // raw mode leaves OPOST alone but we own the terminal, so be explicit
const DEBUG = !!process.env.HYPED_PRO_DEBUG;
function pythonBin() {
    return process.env.HYPED_PRO_PYTHON || 'python3';
}
// ---------------------------------------------------------------------------
// ANSI helpers
// ---------------------------------------------------------------------------
const CSI = "\x1b[";
const CLEAR = `${CSI}2J${CSI}H`;
const SHOW_CURSOR = `${CSI}?25h`;
const RESET = `${CSI}0m`;
function c256(code, text) { return `${CSI}38;5;${code}m${text}${RESET}`; }
function bg256(code, text) { return `${CSI}48;5;${code}m${text}${RESET}`; }
function bold(text) { return `${CSI}1m${text}${RESET}`; }
function dim(text) { return `${CSI}2m${text}${RESET}`; }
function stripAnsi(str) { return str.replace(/\x1b\[[0-9;?]*[a-zA-Z]/g, ''); }
// ---------------------------------------------------------------------------
// Config persistence (~/.hyped-plus/config.json) — survives restarts.
// Cloud API keys are NOT stored here — those live in ~/.hypernix/config.json
// via the Python bridge (hypernix.config.set_provider_key), shared with the
// GUI and the rest of the hypernix CLI so a key set in one place works
// everywhere.
// ---------------------------------------------------------------------------
const CONFIG_DIR = path.join(os.homedir(), '.hyped-plus');
const CONFIG_PATH = path.join(CONFIG_DIR, 'config.json');
function loadConfig() {
    try {
        return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
    }
    catch {
        return {};
    }
}
function saveConfig(cfg) {
    try {
        fs.mkdirSync(CONFIG_DIR, { recursive: true });
        fs.writeFileSync(CONFIG_PATH, JSON.stringify(cfg, null, 2));
        return true;
    }
    catch {
        return false;
    }
}
// ---------------------------------------------------------------------------
// Bridge — one long-lived Python worker (hypernix.hyped_pro_bridge) that
// owns the real model catalog, real cloud HTTP calls, real HF downloads,
// real local inference, and the real T1 Gatekeeper. stderr is inherited
// straight through to this terminal so every download progress bar,
// [hypernix] log line, and Python traceback is visible unmodified.
// ---------------------------------------------------------------------------
class Bridge {
    proc = null;
    nextId = 1;
    pending = new Map();
    buf = "";
    ensureStarted() {
        if (this.proc)
            return this.proc;
        const py = pythonBin();
        const child = (0, child_process_1.spawn)(py, ['-m', 'hypernix.hyped_pro_bridge', 'serve'], {
            stdio: ['pipe', 'pipe', 'inherit'],
            env: process.env,
        });
        child.stdout.setEncoding('utf8');
        child.stdout.on('data', (chunk) => this.onData(chunk));
        child.on('error', (err) => {
            elog('HPT-BRIDGE-001', `failed to start the Python bridge (${py} -m hypernix.hyped_pro_bridge): ${err.message}. Install with 'pip install hypernix', or set HYPED_PRO_PYTHON to a python that has it.`);
        });
        child.on('exit', (code, signal) => {
            if (this.pending.size > 0) {
                elog('HPT-BRIDGE-002', `Python bridge exited (code=${code}, signal=${signal}) with ${this.pending.size} request(s) still in flight.`);
            }
            for (const resolve of this.pending.values()) {
                resolve({ id: null, ok: false, code: 'HPT-BRIDGE-002', error: 'bridge process exited' });
            }
            this.pending.clear();
            this.proc = null;
        });
        this.proc = child;
        return child;
    }
    onData(chunk) {
        this.buf += chunk;
        let idx;
        while ((idx = this.buf.indexOf('\n')) >= 0) {
            const line = this.buf.slice(0, idx);
            this.buf = this.buf.slice(idx + 1);
            if (!line.trim())
                continue;
            let resp;
            try {
                resp = JSON.parse(line);
            }
            catch {
                elog('HPT-BRIDGE-003', `malformed JSON from bridge: ${line.slice(0, 200)}`);
                continue;
            }
            if (typeof resp.id === 'number') {
                const cb = this.pending.get(resp.id);
                if (cb) {
                    this.pending.delete(resp.id);
                    cb(resp);
                }
            }
        }
    }
    async call(cmd, params = {}) {
        const child = this.ensureStarted();
        const id = this.nextId++;
        const req = { id, cmd, ...params };
        return new Promise((resolve) => {
            this.pending.set(id, resolve);
            child.stdin.write(JSON.stringify(req) + "\n", (err) => {
                if (err) {
                    this.pending.delete(id);
                    resolve({ id, ok: false, code: 'HPT-BRIDGE-001', error: `write to bridge failed: ${err.message}` });
                }
            });
        });
    }
    shutdown() {
        if (this.proc) {
            try {
                this.proc.stdin.end();
            }
            catch { /* already gone */ }
            try {
                this.proc.kill('SIGTERM');
            }
            catch { /* already gone */ }
            this.proc = null;
        }
    }
}
const bridge = new Bridge();
// ---------------------------------------------------------------------------
// Debug/error logging — every failure path prints a grep-able code, per
// spec, regardless of which backend (cloud vendor, local snapshot, T1,
// GUI launch) produced it.
// ---------------------------------------------------------------------------
function elog(code, msg) {
    log(c256(196, `  [hyped-pro] ERROR ${code}: ${msg}`));
}
function dlog(msg) {
    if (!DEBUG)
        return;
    log(dim(`  [hyped-pro] DEBUG: ${msg}`));
}
// ---------------------------------------------------------------------------
// Catalog — loaded once, synchronously, at startup from the Python bridge
// (`hypernix.hyped_pro_core.MODELS` / `PROVIDERS`) so there is exactly one
// place that lists models and their real provider info; hyped_pro.ts never
// keeps its own duplicate copy that could drift out of sync.
// ---------------------------------------------------------------------------
function loadCatalogSync() {
    const py = pythonBin();
    const result = (0, child_process_1.spawnSync)(py, ['-m', 'hypernix.hyped_pro_bridge', 'catalog'], { encoding: 'utf8', timeout: 15000 });
    const fail = (code, detail) => {
        console.error(c256(196, `[hyped-pro] ERROR ${code}: could not load the model catalog from the Python backend (${py} -m hypernix.hyped_pro_bridge catalog).`));
        console.error(c256(196, `  ${detail}`));
        console.error(dim(`  Install the hypernix package (pip install hypernix) so '${py} -m hypernix' works, or set HYPED_PRO_PYTHON.`));
    };
    if (result.error || result.status !== 0 || !result.stdout) {
        fail('HPT-CATALOG-001', result.error ? result.error.message : (result.stderr || `exit code ${result.status}`));
        return { models: [], providers: {} };
    }
    try {
        const lastLine = result.stdout.trim().split('\n').pop() || '{}';
        const parsed = JSON.parse(lastLine);
        if (!parsed.ok)
            throw new Error(parsed.error || 'bridge returned ok=false');
        const data = parsed.data;
        const models = data.models.map((m) => ({
            short: m.short, repo: m.repo, vendor: m.vendor, kind: m.kind,
            badge: m.badge, contextWindow: m.context_window, notes: m.notes || "",
        }));
        return { models, providers: data.providers };
    }
    catch (exc) {
        fail('HPT-CATALOG-002', String(exc));
        return { models: [], providers: {} };
    }
}
const { models: LOADED_MODELS, providers: PROVIDERS } = loadCatalogSync();
exports.PROVIDERS = PROVIDERS;
const FALLBACK_MODEL = {
    short: "(catalog unavailable)", repo: "", vendor: "unavailable", kind: "local",
    badge: "\u26a0\ufe0f", contextWindow: 0, notes: "The Python catalog failed to load — see the HPT-CATALOG error above.",
};
const MODELS = LOADED_MODELS.length > 0 ? LOADED_MODELS : [FALLBACK_MODEL];
exports.MODELS = MODELS;
function providerOf(m) {
    return PROVIDERS[m.vendor];
}
// Confirmed, vendor-documented per-1M-token rates only. Anthropic/OpenAI
// pricing changes often enough (and third-party trackers disagree with
// each other) that guessing here would be exactly the kind of fabricated
// number this rewrite is meant to remove — /price shows "no verified rate
// on file" instead of a made-up figure when a vendor isn't listed.
const PRICE_RATES = {
    "kimi-k3": [3.00, 15.00], // Moonshot platform docs, cache-miss rate
};
// HyperNix's own named modules, exposed to the agent as "skills"
const SKILLS = [
    { name: "pressure-cooker", desc: "Core training loop / fine-tuning engine (StovetopV3CookerPlus)" },
    { name: "cutting-board", desc: "Dataset prep, tokenization & curriculum structuring" },
    { name: "freezer", desc: "Checkpointing & model storage" },
    { name: "smoke-alarm", desc: "Safety / eval callbacks during training" },
    { name: "tvtop", desc: "Live training status display" },
    { name: "gui-mode", desc: "Launch the hyped-pro desktop GUI (Qt6 / GTK) — run with /gui" },
];
exports.SKILLS = SKILLS;
// Slash commands — single source of truth for /help, the live palette, and dispatch
const COMMANDS = [
    { name: "/help", desc: "Show this command list" },
    { name: "/model", desc: "Switch or list model catalog entries" },
    { name: "/download", desc: "Download a local model's weights from HuggingFace" },
    { name: "/configure", desc: "Interactive setup wizard: model, persona, keys, theme" },
    { name: "/persona", desc: "Set agent persona (coder, reviewer, writer, none)" },
    { name: "/system-prompt", desc: "Set custom system prompt" },
    { name: "/compact-prompt", desc: "Compact system prompt into dense directives" },
    { name: "/auto-compact", desc: "Toggle auto context compaction" },
    { name: "/skills", desc: "List HyperNix skills available to the agent" },
    { name: "/context", desc: "Show context/token usage bar" },
    { name: "/price", desc: "Display price & token estimate breakdown" },
    { name: "/theme", desc: "Cycle the TUI color theme" },
    { name: "/save", desc: "Save the transcript to a file" },
    { name: "/retry", desc: "Regenerate the last agent reply" },
    { name: "/key", desc: "Set/view a cloud API key: /key <vendor> [api-key]" },
    { name: "/gui", desc: "Launch the hyped-pro desktop GUI in a new window" },
    { name: "/clear", desc: "Clear conversation context (scrollback stays)" },
    { name: "/quit", desc: "Exit hyped+ TUI" },
];
exports.COMMANDS = COMMANDS;
const THEMES = [
    { name: "classic", border: 135, title: 220, accent: 33 },
    { name: "ocean", border: 33, title: 51, accent: 39 },
    { name: "forest", border: 34, title: 82, accent: 29 },
    { name: "sunset", border: 202, title: 214, accent: 208 },
];
exports.THEMES = THEMES;
const PERSONAS = {
    none: "",
    coder: "Favor concrete, runnable code over explanation. Verify before claiming something works.",
    reviewer: "Read for correctness and edge cases first. Flag risks before style nits.",
    writer: "Prioritize clarity and concision in prose; avoid filler.",
};
// ---------------------------------------------------------------------------
// Session state
// ---------------------------------------------------------------------------
const cfg = loadConfig();
let currentModel = MODELS.find(m => m.short === cfg.model) || MODELS[0];
let persona = cfg.persona && PERSONAS[cfg.persona] !== undefined ? cfg.persona : "coder";
let systemPrompt = "You are Hyped+, an autonomous TUI coding assistant for HyperNix.";
let history = [];
let toolCallCount = 0;
let autoCompact = cfg.autoCompact !== undefined ? cfg.autoCompact : true;
let themeIdx = typeof cfg.themeIdx === 'number' && Number.isInteger(cfg.themeIdx) ? cfg.themeIdx : 0;
const startTime = Date.now();
// Models already confirmed present on disk this session, so we don't
// re-check/re-download on every turn.
const downloadedThisSession = new Set();
function theme() { return THEMES[themeIdx]; }
function persistConfig() {
    saveConfig({ model: currentModel.short, persona, autoCompact, themeIdx });
}
// ---------------------------------------------------------------------------
// Box rendering
// ---------------------------------------------------------------------------
function renderBox(title, lines, width = 80, borderCol = 135, titleCol = 96) {
    const top = c256(borderCol, "\u256d") + bg256(234, c256(titleCol, bold(` ${title} `))) + c256(borderCol, "\u2500".repeat(Math.max(0, width - title.length - 4)) + "\u256e");
    const bottom = c256(borderCol, "\u2570" + "\u2500".repeat(width - 2) + "\u256f");
    const body = lines.map(ln => {
        const plain = stripAnsi(ln);
        const pad = Math.max(0, width - 4 - plain.length);
        return c256(borderCol, "\u2502 ") + ln + " ".repeat(pad) + c256(borderCol, " \u2502");
    });
    return [top, ...body, bottom];
}
function estimatePrice(model, historyList) {
    const inToks = historyList.reduce((acc, m) => acc + (m.content ? m.content.length / 4 : 0), 0);
    const outToks = toolCallCount * 120 + historyList.length * 40;
    const rate = PRICE_RATES[model.short];
    if (!rate)
        return { inToks: Math.round(inToks), outToks: Math.round(outToks), cost: null };
    const [inR, outR] = rate;
    const cost = (inToks / 1e6) * inR + (outToks / 1e6) * outR;
    return { inToks: Math.round(inToks), outToks: Math.round(outToks), cost: cost.toFixed(6) };
}
function compactPrompt(raw) {
    const directives = raw.split("\n")
        .map(s => s.trim())
        .filter(Boolean)
        .map(s => s.replace(/^(please|always|make sure to)\s+/i, '').replace(/\.$/, ''));
    return "DIRECTIVES: " + Array.from(new Set(directives)).slice(0, 12).join(" | ");
}
// ---------------------------------------------------------------------------
// Live fuzzy letter-match for the "/" palette
//   - a candidate survives only if every typed letter appears in it
//   - matched letters are lit up, the rest stay dim/gray
// ---------------------------------------------------------------------------
function letterFilter(query, candidates, nameFn) {
    if (!query)
        return candidates;
    const qChars = Array.from(new Set(query.toLowerCase().split('')));
    return candidates.filter(cand => {
        const s = nameFn(cand).toLowerCase();
        return qChars.every(ch => s.includes(ch));
    });
}
function highlightLetters(name, query) {
    const qSet = new Set(query.toLowerCase().split(''));
    return name.split('').map(ch => (qSet.has(ch.toLowerCase()) ? c256(theme().title, bold(ch)) : dim(ch))).join('');
}
function paletteCandidates(query) {
    const cmds = letterFilter(query, COMMANDS, c => c.name.slice(1));
    const skills = letterFilter(query, SKILLS, s => s.name);
    return {
        cmds: cmds.slice(0, query ? 8 : 6),
        skills: skills.slice(0, query ? 6 : 3),
    };
}
// ---------------------------------------------------------------------------
// Footer engine: everything above this line is a normal, permanent, scrolling
// terminal — nothing here ever gets cleared. Only the footer (status bar,
// live palette, hint line, input line) redraws in place.
// ---------------------------------------------------------------------------
let footerLineCount = 0;
let buffer = "";
let cursorPos = 0;
let inputHistory = [];
let historyIdx = 0;
let paletteIndex = 0;
let pending = false;
let modelPickerOpen = false;
let modelPickerIndex = 0;
let spinnerFrame = 0;
const SPINNER = ["\u280b", "\u2819", "\u2839", "\u2838", "\u283c", "\u2834", "\u2826", "\u2827", "\u2807", "\u280f"];
function isPaletteOpen() {
    return buffer.startsWith("/") && !buffer.includes(" ");
}
function renderModelPicker() {
    const t = theme();
    const total = MODELS.length;
    const windowSize = 10;
    let start = Math.max(0, modelPickerIndex - Math.floor(windowSize / 2));
    start = Math.min(start, Math.max(0, total - windowSize));
    const end = Math.min(total, start + windowSize);
    const rows = [dim(` select model — ${modelPickerIndex + 1}/${total}`)];
    if (start > 0)
        rows.push(dim(`   \u25b2 ${start} more above`));
    for (let i = start; i < end; i++) {
        const m = MODELS[i];
        const selected = i === modelPickerIndex;
        const marker = selected ? c256(t.accent, "\u25b8 ") : "  ";
        const line = `${marker}${m.badge} ${m.short.padEnd(24)} ${dim(`(${m.kind}/${m.vendor})`)}`;
        rows.push(selected ? bold(line) : line);
    }
    if (end < total)
        rows.push(dim(`   \u25bc ${total - end} more below`));
    rows.push(dim(" \u2191\u2193 browse   \u2192 / \u21b5 select   esc cancel"));
    return rows;
}
function buildFooterLines() {
    const width = Math.min(100, Math.max(70, process.stdout.columns || 80));
    const t = theme();
    const elapsedMin = Math.floor((Date.now() - startTime) / 60000);
    const providerLabel = currentModel.vendor.toUpperCase();
    const price = estimatePrice(currentModel, history);
    const costStr = price.cost === null ? "n/a" : `$${price.cost}`;
    const statusLines = [
        ` Model:  ${c256(36, currentModel.short)} (${providerLabel}) ${currentModel.badge}   Persona: ${c256(t.accent, persona)}   Theme: ${c256(t.accent, t.name)}`,
        ` Status: ${c256(82, 'ACTIVE')}  Auto-Compact: ${c256(220, autoCompact ? 'ON' : 'OFF')}  Skills: ${c256(51, String(SKILLS.length))}  Commands: ${c256(51, String(COMMANDS.length))}`,
        ` Usage:  Turns: ${history.length / 2}  Calls: ${toolCallCount}  Est. Cost: ${costStr}  cwd: ${c256(90, path.basename(process.cwd()))}  up: ${elapsedMin}m`,
    ];
    if (currentModel.short.includes("hyper-nix.2")) {
        statusLines.push(c256(196, " \u26a0\ufe0f  hyper-Nix.2 is severely undertrained — expect weird output"));
    }
    const lines = renderBox(`HYPED+ TUI (v${VERSION})`, statusLines, width, t.border, t.title);
    if (modelPickerOpen) {
        lines.push(...renderModelPicker());
    }
    else if (pending) {
        lines.push(` ${c256(t.title, SPINNER[spinnerFrame % SPINNER.length])} ${dim("agent thinking\u2026  (esc to cancel)")}`);
    }
    else if (isPaletteOpen()) {
        const query = buffer.slice(1);
        const { cmds, skills } = paletteCandidates(query);
        const rows = [];
        cmds.forEach(cmd => rows.push({ type: "cmd", name: "/" + highlightLetters(cmd.name.slice(1), query), desc: cmd.desc }));
        skills.forEach(sk => rows.push({ type: "skill", name: highlightLetters(sk.name, query), desc: sk.desc }));
        if (rows.length === 0) {
            lines.push(dim(" (no commands or skills match) — press esc to dismiss"));
        }
        else {
            rows.forEach((row, i) => {
                const marker = i === paletteIndex ? c256(t.accent, "\u25b8 ") : "  ";
                const tagStr = row.type === "skill" ? ` ${c256(90, "skill")}` : "";
                lines.push(`${marker}${row.name}${tagStr}  ${dim(row.desc)}`);
            });
            lines.push(dim(" \u21b9 accept   \u2191\u2193 navigate   esc dismiss"));
        }
    }
    else {
        lines.push(dim(" /  for commands & skills   alt+y model picker   \u2191\u2193 history   ^L clear   ^C exit"));
    }
    const prompt = c256(t.accent, "hyped+> ");
    lines.push(prompt + buffer);
    return lines;
}
function eraseFooter() {
    if (!process.stdout.isTTY)
        return;
    if (footerLineCount > 0) {
        // drawFooter() leaves the real cursor sitting ON the last footer row
        // (at the input column), not on the row below it — so we only need to
        // move up (footerLineCount - 1) rows to reach the footer's first row,
        // then back to column 1 before clearing, or a stray column offset
        // leaves the start of that row un-cleared and a leftover line of real
        // scrollback gets eaten by the extra row of upward movement.
        const up = footerLineCount - 1;
        const upSeq = up > 0 ? `${CSI}${up}A` : '';
        process.stdout.write(`${upSeq}${CSI}1G${CSI}0J`);
    }
    footerLineCount = 0;
}
function drawFooter() {
    if (!process.stdout.isTTY)
        return;
    const lines = buildFooterLines();
    process.stdout.write(lines.join(NL) + NL);
    footerLineCount = lines.length;
    const promptLen = stripAnsi("hyped+> ").length;
    const col = promptLen + cursorPos + 1;
    process.stdout.write(`${CSI}1A${CSI}${col}G`);
}
function redrawFooter() {
    eraseFooter();
    drawFooter();
}
// Permanent, scrolling output — this is the fix for output vanishing too fast:
// it is never cleared, exactly like normal terminal scrollback.
function log(text) {
    if (!process.stdout.isTTY) {
        console.log(stripAnsi(text));
        return;
    }
    eraseFooter();
    process.stdout.write(text + NL);
    drawFooter();
}
// ---------------------------------------------------------------------------
// "HYPED+" gradient block wordmark — printed once, deterministically, before
// anything else. A single synchronous print can't race with later output.
// ---------------------------------------------------------------------------
const HYPED_BANNER_GLYPHS = {
    H: ["\u2588   \u2588", "\u2588   \u2588", "\u2588\u2588\u2588\u2588\u2588", "\u2588   \u2588", "\u2588   \u2588"],
    Y: ["\u2588   \u2588", " \u2588 \u2588 ", "  \u2588  ", "  \u2588  ", "  \u2588  "],
    P: ["\u2588\u2588\u2588\u2588 ", "\u2588   \u2588", "\u2588\u2588\u2588\u2588 ", "\u2588    ", "\u2588    "],
    E: ["\u2588\u2588\u2588\u2588\u2588", "\u2588    ", "\u2588\u2588\u2588\u2588 ", "\u2588    ", "\u2588\u2588\u2588\u2588\u2588"],
    D: ["\u2588\u2588\u2588\u2588 ", "\u2588   \u2588", "\u2588   \u2588", "\u2588   \u2588", "\u2588\u2588\u2588\u2588 "],
    "+": ["  \u2588  ", "  \u2588  ", "\u2588\u2588\u2588\u2588\u2588", "  \u2588  ", "  \u2588  "],
};
const HYPED_BANNER_WORD = ["H", "Y", "P", "E", "D", "+"];
const HYPED_BANNER_GRADIENT = [39, 45, 99, 135, 171, 213]; // blue -> cyan -> purple -> violet -> pink
function buildHypedBanner() {
    const rows = [];
    for (let r = 0; r < 5; r++) {
        let line = "";
        HYPED_BANNER_WORD.forEach((ch, i) => {
            line += c256(HYPED_BANNER_GRADIENT[i], HYPED_BANNER_GLYPHS[ch][r]) + " ";
        });
        rows.push(line);
    }
    return rows;
}
function printBanner() {
    console.log("");
    buildHypedBanner().forEach(line => console.log(line));
    console.log(dim("  hyped-pro \u00b7 TUI agent for HyperNix"));
    console.log("");
    console.log(dim("Tips: /  for commands & skills \u00b7 alt+y to switch models \u00b7 /configure to set up \u00b7 /help for everything."));
    if (LOADED_MODELS.length === 0) {
        console.log(c256(196, "  Model catalog failed to load — /model, /download, and chat are unavailable until the HPT-CATALOG error above is fixed."));
    }
    console.log("");
}
// ---------------------------------------------------------------------------
// Slash commands
// ---------------------------------------------------------------------------
function renderContextBar() {
    const p = estimatePrice(currentModel, history);
    const win = currentModel.contextWindow || 128000;
    const used = Math.min(1, p.inToks / win);
    const barWidth = 30;
    const filled = Math.round(used * barWidth);
    const bar = c256(used > 0.85 ? 196 : used > 0.6 ? 220 : 82, "\u2588".repeat(filled)) + dim("\u2591".repeat(barWidth - filled));
    return `  [${bar}] ${p.inToks}/${win} tok (${(used * 100).toFixed(1)}%)`;
}
// Ensure a local model's weights are on disk, downloading if necessary.
// Hands the terminal fully over to the Python child while it runs (erases
// the footer and doesn't redraw it) so huggingface_hub's own progress bars
// and [hypernix] log lines scroll normally instead of fighting the footer's
// cursor-positioned redraws.
async function ensureLocalModelReady(model) {
    if (model.kind !== "local" || model.vendor !== "huggingface")
        return true;
    if (downloadedThisSession.has(model.short))
        return true;
    const checkResp = await bridge.call('is_downloaded', { model: model.short });
    if (!checkResp.ok) {
        elog(checkResp.code || 'HPT-BRIDGE-002', checkResp.error || 'could not check download status');
        return false;
    }
    if (checkResp.data.downloaded) {
        downloadedThisSession.add(model.short);
        return true;
    }
    eraseFooter();
    process.stdout.write(dim(`\n  ${model.short} isn't downloaded yet — fetching ${model.repo} from HuggingFace...\n`) + NL);
    const dlResp = await bridge.call('download', { model: model.short });
    if (!dlResp.ok) {
        process.stdout.write(NL);
        drawFooter();
        elog(dlResp.code || 'HPC-LOCAL-001', dlResp.error || 'download failed');
        return false;
    }
    process.stdout.write(c256(82, `  Downloaded -> ${dlResp.data.path}\n`) + NL);
    drawFooter();
    downloadedThisSession.add(model.short);
    return true;
}
async function switchModel(target) {
    currentModel = target;
    persistConfig();
    log(c256(82, `  Switched to model: ${target.short} (${target.kind}/${target.vendor})`));
    if (target.kind === "local") {
        // Auto-download local models the moment they're selected, per spec —
        // don't wait for the first chat turn to discover the weights are missing.
        void ensureLocalModelReady(target);
    }
}
async function handleSlashCommand(cmdStr) {
    const [cmd, ...args] = cmdStr.trim().split(/\s+/);
    const argText = args.join(" ");
    switch (cmd.toLowerCase()) {
        case "/help": {
            const out = [c256(96, "\n  hyped+ commands:")];
            COMMANDS.forEach(({ name, desc }) => {
                out.push(`  ${c256(33, name.padEnd(18))} ${dim(desc)}`);
            });
            out.push(dim("\n  type / to open the live command + skill palette"));
            log(out.join(NL));
            break;
        }
        case "/model": {
            if (!argText) {
                const out = [c256(96, "\n  Available Models:")];
                MODELS.forEach((m, i) => out.push(`  ${i + 1}. ${m.badge} ${m.short} (${m.kind}/${m.vendor})`));
                log(out.join(NL));
            }
            else {
                const found = MODELS.find(m => m.short.toLowerCase() === argText.toLowerCase());
                if (found) {
                    await switchModel(found);
                }
                else {
                    log(c256(196, `  Unknown model '${argText}'. Try /model with no args to list.`));
                }
            }
            break;
        }
        case "/download": {
            const target = argText
                ? MODELS.find(m => m.short.toLowerCase() === argText.toLowerCase())
                : currentModel;
            if (!target) {
                log(c256(196, `  Unknown model '${argText}'. Try /model with no args to list.`));
                break;
            }
            if (target.kind !== "local") {
                log(c256(220, `  ${target.short} is a ${target.kind} model (${target.vendor}) — nothing to download, it's called over the network. Set a key with /key ${target.vendor} <api-key>.`));
                break;
            }
            const ok = await ensureLocalModelReady(target);
            if (ok)
                log(c256(82, `  ${target.short} is ready.`));
            break;
        }
        case "/configure":
            await runConfigureWizard();
            return; // wizard already redrew (raw mode) or handed back to the shared loop (non-TTY)
        case "/persona": {
            const names = Object.keys(PERSONAS);
            if (!argText) {
                log(c256(96, `\n  Personas: ${names.join(", ")}\n  Current: ${persona}`));
            }
            else if (names.includes(argText.toLowerCase())) {
                persona = argText.toLowerCase();
                persistConfig();
                log(c256(82, `  Persona set: ${persona}`));
            }
            else {
                log(c256(196, `  Unknown persona '${argText}'. Options: ${names.join(", ")}`));
            }
            break;
        }
        case "/system-prompt":
            if (argText) {
                systemPrompt = argText;
                log(c256(82, `  System prompt updated (${argText.length} chars)`));
            }
            else {
                log(c256(96, `\n  Current System Prompt:\n  ${systemPrompt}`));
            }
            break;
        case "/compact-prompt":
            systemPrompt = compactPrompt(systemPrompt);
            log(c256(82, `\n  Compacted System Prompt:\n  ${systemPrompt}`));
            break;
        case "/auto-compact":
            autoCompact = !autoCompact;
            persistConfig();
            log(c256(82, `  Auto compaction ${autoCompact ? 'enabled' : 'disabled'}`));
            break;
        case "/skills": {
            const out = [c256(96, "\n  HyperNix skills:")];
            SKILLS.forEach(s => out.push(`  ${c256(51, s.name.padEnd(18))} ${dim(s.desc)}`));
            log(out.join(NL));
            break;
        }
        case "/context":
            log(c256(96, "\n  Context usage:") + NL + renderContextBar());
            break;
        case "/price": {
            const p = estimatePrice(currentModel, history);
            const costStr = p.cost === null
                ? `no verified rate on file${providerOf(currentModel)?.docs_url ? ` — see ${providerOf(currentModel).docs_url}` : ''}`
                : `$${p.cost}`;
            log(c256(96, `\n  Est. Input Tokens: ${p.inToks} | Est. Output Tokens: ${p.outToks} | Cost: ${costStr}`));
            break;
        }
        case "/theme":
            themeIdx = (themeIdx + 1) % THEMES.length;
            persistConfig();
            log(c256(theme().accent, `  Theme: ${theme().name}`));
            break;
        case "/save": {
            const file = path.join(process.cwd(), `hyped-transcript-${Date.now()}.txt`);
            const body = history.map(m => `${m.role}: ${m.content}`).join("\n");
            try {
                fs.writeFileSync(file, body || "(empty transcript)");
                log(c256(82, `  Saved transcript -> ${file}`));
            }
            catch (e) {
                const msg = e instanceof Error ? e.message : String(e);
                log(c256(196, `  Could not save transcript: ${msg}`));
            }
            break;
        }
        case "/retry": {
            if (history.length < 2) {
                log(dim("  Nothing to retry yet."));
                break;
            }
            const lastUser = [...history].reverse().find(m => m.role === 'user');
            if (!lastUser) {
                log(dim("  No previous user turn found."));
                break;
            }
            if (history[history.length - 1].role === 'assistant')
                history.pop();
            log(c256(90, `  Retrying: "${lastUser.content.slice(0, 60)}"`));
            void runChatTurn(lastUser.content, /*record=*/ false);
            return;
        }
        case "/key": {
            const validVendors = Object.keys(PROVIDERS).filter(v => PROVIDERS[v].kind === "cloud" || v === "t1");
            if (!argText) {
                const out = [c256(96, "\n  Cloud API keys:")];
                for (const v of validVendors) {
                    const r = await bridge.call('key_get', { vendor: v });
                    const status = r.ok && r.data.set ? c256(82, r.data.masked) : dim("not set");
                    out.push(`  ${c256(33, v.padEnd(12))} ${status}  ${dim(PROVIDERS[v]?.auth_env_var || "")}`);
                }
                out.push(dim("\n  Usage: /key <vendor> <api-key>   e.g. /key anthropic sk-ant-..."));
                log(out.join(NL));
                break;
            }
            const [vendor, ...keyParts] = args;
            const key = keyParts.join(" ");
            if (!validVendors.includes(vendor.toLowerCase())) {
                log(c256(196, `  Unknown vendor '${vendor}'. Options: ${validVendors.join(", ")}`));
                break;
            }
            if (!key) {
                log(c256(96, `  Usage: /key ${vendor} <api-key>`));
                break;
            }
            const setResp = await bridge.call('key_set', { vendor: vendor.toLowerCase(), key });
            if (setResp.ok) {
                // usable immediately in this process too, without a restart
                const envVar = PROVIDERS[vendor.toLowerCase()]?.auth_env_var;
                if (envVar)
                    process.env[envVar] = key;
                log(c256(82, `  Key saved for ${vendor} (${key.slice(0, 8)}...)`));
            }
            else {
                elog(setResp.code || 'HPT-BRIDGE-002', setResp.error || 'could not save key');
            }
            break;
        }
        case "/gui": {
            const py = pythonBin();
            log(dim(`  Launching hyped-pro GUI (${py} -m hypernix.hyped_pro_gui) — its logs print to this terminal...`));
            try {
                const child = (0, child_process_1.spawn)(py, ['-m', 'hypernix.hyped_pro_gui'], {
                    detached: true,
                    stdio: ['ignore', 'inherit', 'inherit'],
                    env: process.env,
                });
                child.on('error', (err) => {
                    elog('HPT-GUI-001', `failed to launch the GUI (${py} -m hypernix.hyped_pro_gui): ${err.message}`);
                });
                child.unref();
            }
            catch (exc) {
                elog('HPT-GUI-001', `failed to launch the GUI: ${exc}`);
            }
            break;
        }
        case "/clear":
        case "/reset":
            history = [];
            toolCallCount = 0;
            log(dim("  Conversation context cleared (scrollback above is untouched)."));
            break;
        case "/quit":
        case "/exit":
            cleanupAndExit(0);
            return;
        default:
            log(c256(196, `  Unknown command '${cmd}'. Try /help.`));
    }
    redrawFooter();
}
// ---------------------------------------------------------------------------
// /configure — interactive wizard. Temporarily drops out of raw-keypress mode
// and uses a plain readline Q&A, then resumes the live TUI loop.
// ---------------------------------------------------------------------------
// Shared line source for the non-TTY fallback. Using rl.question() in a
// recursive chain is fragile once any await is involved: Node's readline
// processes every buffered line in one synchronous pass when a pipe delivers
// them all at once, and a line arriving while nothing has re-armed
// rl.question() yet is silently dropped. This queue buffers every 'line'
// event as it happens (never lost) and hands lines out one at a time to
// whichever async consumer — the main loop or the /configure wizard — is
// currently awaiting one.
function createLineQueue(rl) {
    const buffered = [];
    const waiters = [];
    let ended = false;
    rl.on('line', (l) => {
        const w = waiters.shift();
        if (w)
            w(l);
        else
            buffered.push(l);
    });
    rl.on('close', () => {
        ended = true;
        let w;
        while ((w = waiters.shift()))
            w(null);
    });
    return {
        next() {
            if (buffered.length)
                return Promise.resolve(buffered.shift());
            if (ended)
                return Promise.resolve(null);
            return new Promise(resolve => waiters.push(resolve));
        },
    };
}
// Set by runSimpleTUI() in the non-TTY fallback; when present, /configure
// pulls from the same queue instead of opening a second readline.Interface
// on the same stdin (two interfaces racing for one stream drops input).
let activeRL = null;
let activeQueue = null;
function pauseRawInput() {
    process.stdin.removeListener('keypress', onKeypress);
    if (process.stdin.isTTY)
        process.stdin.setRawMode(false);
}
function resumeRawInput() {
    if (process.stdin.isTTY)
        process.stdin.setRawMode(true);
    process.stdin.on('keypress', onKeypress);
    buffer = "";
    cursorPos = 0;
    footerLineCount = 0;
    drawFooter();
}
async function askLine(queue, promptText) {
    process.stdout.write(promptText);
    const line = await queue.next();
    return line === null ? "" : line.trim();
}
async function runConfigureWizard() {
    eraseFooter();
    const ownRL = !activeQueue;
    let rl = activeRL;
    let queue = activeQueue;
    if (ownRL) {
        pauseRawInput();
        process.stdout.write(SHOW_CURSOR);
        rl = readline.createInterface({ input: process.stdin, output: process.stdout, terminal: false });
        queue = createLineQueue(rl);
    }
    const q = queue; // always assigned: either shared or just-created above
    console.log(c256(96, "\n  hyped+ configure \u2014 press Enter to keep the current value\n"));
    console.log(c256(90, "  Models:"));
    MODELS.forEach((m, i) => console.log(`    ${i + 1}. ${m.badge} ${m.short} (${m.kind}/${m.vendor})`));
    const modelAns = await askLine(q, `  choose [1-${MODELS.length}, blank=keep "${currentModel.short}"]: `);
    if (modelAns) {
        const idx = parseInt(modelAns, 10);
        if (idx >= 1 && idx <= MODELS.length)
            currentModel = MODELS[idx - 1];
    }
    const personaNames = Object.keys(PERSONAS);
    const personaAns = await askLine(q, `  persona [${personaNames.join("/")}, blank=keep "${persona}"]: `);
    if (personaAns && personaNames.includes(personaAns.toLowerCase()))
        persona = personaAns.toLowerCase();
    const provider = providerOf(currentModel);
    if (provider && provider.kind === "cloud") {
        const existing = await bridge.call('key_get', { vendor: currentModel.vendor });
        const hint = existing.ok && existing.data.set ? ` [blank=keep ${existing.data.masked}]` : "";
        const keyAns = await askLine(q, `  API key for ${currentModel.vendor}${hint}: `);
        if (keyAns) {
            const setResp = await bridge.call('key_set', { vendor: currentModel.vendor, key: keyAns });
            if (setResp.ok && provider.auth_env_var)
                process.env[provider.auth_env_var] = keyAns;
            if (!setResp.ok)
                console.log(c256(196, `  Could not save key: ${setResp.error}`));
        }
    }
    else if (currentModel.vendor === "t1") {
        const keyAns = await askLine(q, "  HNX T1 key [blank=keep existing]: ");
        if (keyAns)
            await bridge.call('key_set', { vendor: 't1', key: keyAns });
    }
    const compactAns = await askLine(q, `  auto-compact on/off [blank=keep "${autoCompact ? 'on' : 'off'}"]: `);
    if (compactAns)
        autoCompact = /^(y|yes|on|true)$/i.test(compactAns);
    console.log(c256(90, `  Themes: ${THEMES.map(t => t.name).join(", ")}`));
    const themeAns = await askLine(q, `  theme [blank=keep "${theme().name}"]: `);
    if (themeAns) {
        const found = THEMES.findIndex(t => t.name === themeAns.toLowerCase());
        if (found >= 0)
            themeIdx = found;
    }
    persistConfig();
    console.log(c256(82, "\n  Configuration saved -> ~/.hyped-plus/config.json\n"));
    if (currentModel.kind === "local") {
        console.log(dim(`  Checking local weights for ${currentModel.short}...`));
        await ensureLocalModelReady(currentModel);
    }
    if (ownRL && rl) {
        rl.close();
        await new Promise(r => setTimeout(r, 600));
        resumeRawInput();
    }
    // else: leave the shared interface/queue open — runSimpleTUI's loop resumes it
}
// ---------------------------------------------------------------------------
// Chat turn — a real round-trip through the Python bridge to whichever
// backend the current model's provider maps to (cloud HTTP API, local
// HyperNix/transformers inference, or the T1 Gatekeeper). No branch here
// fabricates a reply: a failed call surfaces its real HPC-*/HPB-* error
// code instead.
// ---------------------------------------------------------------------------
let cancelRequested = false;
async function runChatTurn(line, record = true) {
    if (record)
        history.push({ role: 'user', content: line });
    if (currentModel.vendor === "unavailable") {
        elog('HPT-CATALOG-001', "no model catalog loaded — nothing to chat with. See the startup error above.");
        return;
    }
    if (currentModel.kind === "local") {
        const ready = await ensureLocalModelReady(currentModel);
        if (!ready) {
            if (record)
                history.pop();
            return;
        }
    }
    pending = true;
    cancelRequested = false;
    const spin = setInterval(() => { spinnerFrame++; redrawFooter(); }, 90);
    const personaText = PERSONAS[persona] || "";
    const fullSystem = [systemPrompt, personaText].filter(Boolean).join("\n\n");
    const resp = await bridge.call('chat', {
        model: currentModel.short,
        messages: history.map(m => ({ role: m.role, content: m.content })),
        system: fullSystem,
    });
    clearInterval(spin);
    pending = false;
    if (cancelRequested) {
        log(dim("  (cancelled)"));
        redrawFooter();
        return;
    }
    if (!resp.ok) {
        if (record)
            history.pop(); // don't leave a dangling user turn with no reply
        elog(resp.code || 'HPB-INTERNAL-001', resp.error || 'chat request failed');
        redrawFooter();
        return;
    }
    toolCallCount++;
    const reply = resp.data.reply;
    history.push({ role: 'assistant', content: reply });
    log(`${c256(33, 'agent>')} ${reply}`);
    if (autoCompact && history.length > 20) {
        history = history.slice(-10);
    }
}
// ---------------------------------------------------------------------------
// Raw-mode input engine
// ---------------------------------------------------------------------------
function cleanupAndExit(code = 0) {
    eraseFooter();
    process.stdout.write(SHOW_CURSOR + NL);
    bridge.shutdown();
    process.exit(code);
}
function submitInput() {
    const line = buffer.trim();
    eraseFooter();
    if (line)
        process.stdout.write(c256(theme().accent, "hyped+> ") + line + NL);
    if (line) {
        inputHistory.push(line);
        historyIdx = inputHistory.length;
    }
    buffer = "";
    cursorPos = 0;
    paletteIndex = 0;
    drawFooter();
    if (!line)
        return;
    if (line.startsWith("/")) {
        void handleSlashCommand(line);
    }
    else {
        void runChatTurn(line);
    }
}
function acceptPaletteSelection() {
    if (!isPaletteOpen())
        return;
    const query = buffer.slice(1);
    const { cmds, skills } = paletteCandidates(query);
    const rows = [
        ...cmds.map(c => ({ type: "cmd", name: c.name, desc: c.desc })),
        ...skills.map(s => ({ type: "skill", name: s.name, desc: s.desc })),
    ];
    if (rows.length === 0)
        return;
    const pick = rows[Math.min(paletteIndex, rows.length - 1)];
    paletteIndex = 0;
    if (pick.type === "cmd") {
        // commands complete into the input so args can follow
        buffer = pick.name + " ";
        cursorPos = buffer.length;
        redrawFooter();
    }
    else {
        // skills aren't invocable — accepting one just surfaces what it does
        buffer = "";
        cursorPos = 0;
        log(`  ${c256(51, pick.name)}  ${dim(pick.desc)}`);
    }
}
function movePalette(delta) {
    const query = buffer.slice(1);
    const { cmds, skills } = paletteCandidates(query);
    const total = cmds.length + skills.length;
    if (total === 0)
        return;
    paletteIndex = (paletteIndex + delta + total) % total;
    redrawFooter();
}
function onKeypress(str, key) {
    if (!key)
        return;
    if (key.ctrl && key.name === 'c') {
        cleanupAndExit(0);
    }
    if (pending) {
        if (key.name === 'escape') {
            cancelRequested = true;
        }
        return; // everything else is swallowed while a reply is in flight
    }
    if (modelPickerOpen) {
        if (key.name === 'up') {
            modelPickerIndex = (modelPickerIndex - 1 + MODELS.length) % MODELS.length;
            redrawFooter();
            return;
        }
        if (key.name === 'down') {
            modelPickerIndex = (modelPickerIndex + 1) % MODELS.length;
            redrawFooter();
            return;
        }
        if (key.name === 'right' || key.name === 'return') {
            modelPickerOpen = false;
            void switchModel(MODELS[modelPickerIndex]);
            return;
        }
        if (key.name === 'escape' || key.name === 'left') {
            modelPickerOpen = false;
            redrawFooter();
            return;
        }
        return; // swallow anything else while the picker is open
    }
    if (key.meta && key.name === 'y') {
        modelPickerIndex = Math.max(0, MODELS.findIndex(m => m.short === currentModel.short));
        modelPickerOpen = true;
        redrawFooter();
        return;
    }
    if (key.ctrl && key.name === 'l') {
        process.stdout.write(CLEAR);
        footerLineCount = 0;
        drawFooter();
        return;
    }
    if (key.ctrl && key.name === 'u') {
        buffer = "";
        cursorPos = 0;
        paletteIndex = 0;
        redrawFooter();
        return;
    }
    switch (key.name) {
        case 'return':
            submitInput();
            return;
        case 'backspace':
            if (cursorPos > 0) {
                buffer = buffer.slice(0, cursorPos - 1) + buffer.slice(cursorPos);
                cursorPos--;
                paletteIndex = 0;
                redrawFooter();
            }
            return;
        case 'delete':
            if (cursorPos < buffer.length) {
                buffer = buffer.slice(0, cursorPos) + buffer.slice(cursorPos + 1);
                redrawFooter();
            }
            return;
        case 'left':
            cursorPos = Math.max(0, cursorPos - 1);
            redrawFooter();
            return;
        case 'right':
            cursorPos = Math.min(buffer.length, cursorPos + 1);
            redrawFooter();
            return;
        case 'tab':
            acceptPaletteSelection();
            return;
        case 'up':
            if (isPaletteOpen()) {
                movePalette(-1);
                return;
            }
            if (inputHistory.length) {
                historyIdx = Math.max(0, historyIdx - 1);
                buffer = inputHistory[historyIdx] || "";
                cursorPos = buffer.length;
                redrawFooter();
            }
            return;
        case 'down':
            if (isPaletteOpen()) {
                movePalette(1);
                return;
            }
            if (inputHistory.length) {
                historyIdx = Math.min(inputHistory.length, historyIdx + 1);
                buffer = inputHistory[historyIdx] || "";
                cursorPos = buffer.length;
                redrawFooter();
            }
            return;
        case 'escape':
            if (isPaletteOpen()) {
                buffer = "";
                cursorPos = 0;
                redrawFooter();
            }
            return;
        default:
            break;
    }
    if (str && !key.ctrl && !key.meta) {
        buffer = buffer.slice(0, cursorPos) + str + buffer.slice(cursorPos);
        cursorPos += str.length;
        paletteIndex = 0;
        redrawFooter();
    }
}
// ---------------------------------------------------------------------------
// Fallback loop for non-TTY input (pipes, tests) — no live palette possible,
// but output still isn't clobbered by a full-screen clear.
// ---------------------------------------------------------------------------
function runSimpleTUI() {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout, terminal: false });
    const queue = createLineQueue(rl); // local, stable reference for this loop
    activeRL = rl;
    activeQueue = queue; // module-level, so /configure can find & reuse it
    rl.on('close', () => {
        // Only clear activeRL — the queue itself stays valid and keeps draining
        // any lines that were already buffered before stdin hit EOF. Nulling it
        // here would orphan an in-flight consumer (e.g. the /configure wizard)
        // that captured this same queue reference earlier and is still awaiting
        // answers still sitting in its buffer.
        activeRL = null;
    });
    console.log(c256(90, "  (non-interactive input detected — live palette disabled, type / for commands)\n"));
    void (async () => {
        for (;;) {
            process.stdout.write("hyped+> ");
            const raw = await queue.next();
            if (raw === null)
                break; // stdin closed, nothing left buffered
            const line = raw.trim();
            if (!line)
                continue;
            if (line.startsWith("/")) {
                await handleSlashCommand(line); // log()/eraseFooter/drawFooter are TTY-aware no-ops here
                continue;
            }
            console.log(dim("  agent> (thinking...)"));
            await runChatTurn(line);
        }
    })();
}
// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------
async function main(argv) {
    const args = argv || process.argv.slice(2);
    if (args.includes('--help') || args.includes('-h')) {
        console.log(`hyped+ v${VERSION}\nUsage: hyped+ [--model <short>] [--no-color]\n`);
        return;
    }
    const modelFlagIdx = args.indexOf('--model');
    if (modelFlagIdx >= 0 && args[modelFlagIdx + 1]) {
        const found = MODELS.find(m => m.short === args[modelFlagIdx + 1]);
        if (found)
            currentModel = found;
    }
    printBanner();
    if (!process.stdin.isTTY) {
        runSimpleTUI();
        return;
    }
    readline.emitKeypressEvents(process.stdin);
    process.stdin.setRawMode(true);
    process.stdin.on('keypress', onKeypress);
    process.stdout.on('resize', () => redrawFooter());
    process.on('SIGINT', () => cleanupAndExit(0));
    drawFooter();
}
if (require.main === module) {
    main().catch(err => {
        console.error("hyped+ error:", err);
        process.exit(1);
    });
}
