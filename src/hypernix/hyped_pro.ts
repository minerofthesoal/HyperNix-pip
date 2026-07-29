#!/usr/bin/env node
/**
 * hyped+ (hyped-pro) — TypeScript TUI Agent CLI for HyperNix.
 *
 * Ported from hyped_pro.js to TypeScript. Uses a live status/palette footer,
 * a deterministic startup banner, price estimator, prompt compactor,
 * auto-compaction, a fuzzy slash-command + skill palette, and an
 * alt+y model picker over a curated model catalog.
 *
 * Compiled with `tsc` (see tsconfig.json) to hyped_pro.js, which is what
 * hyped_pro.py actually spawns — edit this file, not the compiled output.
 */

import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as readline from 'readline';
import { execSync } from 'child_process'; // <-- ADD THIS

const VERSION = "v0.71.4";
const NL = "\r\n"; // raw mode leaves OPOST alone but we own the terminal, so be explicit

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
type Provider = "local" | "anthropic" | "openai" | "t1";

interface ModelDef {
  short: string;
  repo: string;
  provider: Provider;
  badge: string;
}

interface CommandDef {
  name: string;
  desc: string;
}

interface SkillDef {
  name: string;
  desc: string;
}

interface ThemeDef {
  name: string;
  border: number;
  title: number;
  accent: number;
}

interface HypedConfig {
  model?: string;
  persona?: string;
  autoCompact?: boolean;
  themeIdx?: number;
}

interface HistoryMsg {
  role: "user" | "assistant";
  content: string;
}

interface PriceEstimate {
  inToks: number;
  outToks: number;
  cost: string;
}

interface PaletteCandidates {
  cmds: CommandDef[];
  skills: SkillDef[];
}

interface PaletteRow {
  type: "cmd" | "skill";
  name: string;
  desc: string;
}

interface LineQueue {
  next(): Promise<string | null>;
}

// ---------------------------------------------------------------------------
// ANSI helpers
// ---------------------------------------------------------------------------
const CSI = "\x1b[";
const CLEAR = `${CSI}2J${CSI}H`;
const SHOW_CURSOR = `${CSI}?25h`;
const RESET = `${CSI}0m`;

function c256(code: number, text: string): string { return `${CSI}38;5;${code}m${text}${RESET}`; }
function bg256(code: number, text: string): string { return `${CSI}48;5;${code}m${text}${RESET}`; }
function bold(text: string): string { return `${CSI}1m${text}${RESET}`; }
function dim(text: string): string { return `${CSI}2m${text}${RESET}`; }
function stripAnsi(str: string): string { return str.replace(/\x1b\[[0-9;?]*[a-zA-Z]/g, ''); }

// ---------------------------------------------------------------------------
// Config persistence (~/.hyped-plus/config.json) — survives restarts
// ---------------------------------------------------------------------------
const CONFIG_DIR = path.join(os.homedir(), '.hyped-plus');
const CONFIG_PATH = path.join(CONFIG_DIR, 'config.json');

function loadConfig(): HypedConfig {
  try {
    return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8')) as HypedConfig;
  } catch {
    return {};
  }
}

function saveConfig(cfg: HypedConfig): boolean {
  try {
    fs.mkdirSync(CONFIG_DIR, { recursive: true });
    fs.writeFileSync(CONFIG_PATH, JSON.stringify(cfg, null, 2));
    return true;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Curated Models Catalog
// ---------------------------------------------------------------------------
const MODELS: ModelDef[] = [
  { short: "qwen3.7-plus", repo: "Qwen/Qwen3.7-Plus", provider: "local", badge: "\u2605" },
  { short: "kimi-k3", repo: "MoonshotAI/Kimi-K3", provider: "local", badge: "\u2605" },
  { short: "claude-sonnet-4.6", repo: "claude-4-6-sonnet", provider: "anthropic", badge: "\u26a1" },
  { short: "claude-sonnet-5", repo: "claude-5-sonnet", provider: "anthropic", badge: "\u26a1" },
  { short: "claude-opus-4.8", repo: "claude-4-8-opus", provider: "anthropic", badge: "\u26a1" },
  { short: "claude-fable-5", repo: "claude-fable-5", provider: "anthropic", badge: "\u2605" },
  { short: "gpt-4o", repo: "gpt-4o", provider: "openai", badge: "\u26a1" },
  { short: "gpt-5.6-terra", repo: "gpt-5.6-terra", provider: "openai", badge: "\u26a1" },
  { short: "gpt-5.6-sol", repo: "gpt-5.6-sol", provider: "openai", badge: "\u26a1" },
  { short: "gpt-5.5", repo: "gpt-5.5", provider: "openai", badge: "\u26a1" },
  { short: "deepseek-r1", repo: "deepseek-ai/DeepSeek-R1", provider: "local", badge: "\u2605" },
  { short: "deekseek-v4flash", repo: "deepseek-ai/DeepSeek-V4-Flash", provider: "local", badge: "\u26a1" },
  { short: "gemma-4-27b", repo: "google/gemma-4-27b-it", provider: "local", badge: "\u2605" },
  { short: "hyper-nix.2", repo: "ray0rf1re/hyper-Nix.2", provider: "local", badge: "\u26a0\ufe0f" },
  // -- extended local catalog --------------------------------------------
// deleted the extened catalog, all of those models were not real
  // -- verified real Hugging Face repos (checked live, not fictional) ----
  { short: "qwable-3.6-27b-mtp", repo: "Mia-AiLab/Qwable-3.6-27b-MTP", provider: "local", badge: "\u2605" },
  { short: "qwable-9b-fable5", repo: "empero-ai/Qwable-9B-Claude-Fable-5", provider: "local", badge: "\u2605" },
  { short: "qwopus-3.6-35b-a3b-coder-mtp", repo: "Jackrong/Qwopus3.6-35B-A3B-Coder-MTP-GGUF", provider: "local", badge: "\u2605" },
  { short: "qwopus-3.6-27b-coder", repo: "Jackrong/Qwopus3.6-27B-Coder", provider: "local", badge: "\u2605" },
  { short: "qwopus-3.5-9b-v3", repo: "Jackrong/Qwopus3.5-9B-v3", provider: "local", badge: "\u2605" },
  { short: "qwopus-3.6-35b-a3b-v1-mtp", repo: "Jackrong/Qwopus3.6-35B-A3B-v1-MTP-GGUF", provider: "local", badge: "\u2605" },
  { short: "kimi-k2.7-code", repo: "moonshotai/Kimi-K2.7-Code", provider: "local", badge: "\u2605" },
];

const CONTEXT_WINDOWS: Record<string, number> = {
  "qwen3.7-plus": 131072, "kimi-k3": 131072, "claude-sonnet-4.6": 200000,
  "claude-sonnet-5": 200000, "claude-opus-4.8": 200000, "fable-5": 200000,
  "gpt-4o": 128000, "gpt-5.6-terra": 200000, "gpt-5.6-sol": 200000, "gpt-5.5": 128000,
  "deepseek-r1": 128000, "deekseek-v4flash": 128000, "gemma-4-27b": 8192,
  "hyper-nix.2": 4096,
  "kimi-k2.7-code": 262144, // verified: 256K per the real model card
};

// HyperNix's own named modules, exposed to the agent as "skills"
const SKILLS: SkillDef[] = [
  { name: "pressure-cooker", desc: "Core training loop / fine-tuning engine (StovetopV3CookerPlus)" },
  { name: "cutting-board", desc: "Dataset prep, tokenization & curriculum structuring" },
  { name: "freezer", desc: "Checkpointing & model storage" },
  { name: "smoke-alarm", desc: "Safety / eval callbacks during training" },
  { name: "tvtop", desc: "Live training status display" },
];

// Slash commands — single source of truth for /help, the live palette, and dispatch
const COMMANDS: CommandDef[] = [
  { name: "/help", desc: "Show this command list" },
  { name: "/model", desc: "Switch or list model catalog entries" },
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
  { name: "/key", desc: "Set API key (OpenAI / Anthropic / T1)" },
  { name: "/clear", desc: "Clear conversation context (scrollback stays)" },
  { name: "/quit", desc: "Exit hyped+ TUI" },
];

const THEMES: ThemeDef[] = [
  { name: "openclaw", border: 135, title: 220, accent: 33 },
  { name: "ocean", border: 33, title: 51, accent: 39 },
  { name: "forest", border: 34, title: 82, accent: 29 },
  { name: "sunset", border: 202, title: 214, accent: 208 },
];

const PERSONAS: Record<string, string> = {
  none: "",
  coder: "Favor concrete, runnable code over explanation. Verify before claiming something works.",
  reviewer: "Read for correctness and edge cases first. Flag risks before style nits.",
  writer: "Prioritize clarity and concision in prose; avoid filler.",
};

// ---------------------------------------------------------------------------
// Session state
// ---------------------------------------------------------------------------
const cfg: HypedConfig = loadConfig();
let currentModel: ModelDef = MODELS.find(m => m.short === cfg.model) || MODELS[0];
let persona: string = cfg.persona && PERSONAS[cfg.persona] !== undefined ? cfg.persona : "coder";
let systemPrompt = "You are Hyped+ OpenClaw Agent, a world-class autonomous TUI coding assistant.";
let history: HistoryMsg[] = [];
let toolCallCount = 0;
let autoCompact: boolean = cfg.autoCompact !== undefined ? cfg.autoCompact : true;
let apiKey = process.env.OPENAI_API_KEY || process.env.ANTHROPIC_API_KEY || "";
let t1Key = process.env.HNX_T1_KEY || "";
let themeIdx: number = typeof cfg.themeIdx === 'number' && Number.isInteger(cfg.themeIdx) ? cfg.themeIdx : 0;
const startTime = Date.now();

function theme(): ThemeDef { return THEMES[themeIdx]; }

function persistConfig(): void {
  saveConfig({ model: currentModel.short, persona, autoCompact, themeIdx });
}

// ---------------------------------------------------------------------------
// Box rendering
// ---------------------------------------------------------------------------
function renderBox(title: string, lines: string[], width = 80, borderCol = 135, titleCol = 96): string[] {
  const top = c256(borderCol, "\u256d") + bg256(234, c256(titleCol, bold(` ${title} `))) + c256(borderCol, "\u2500".repeat(Math.max(0, width - title.length - 4)) + "\u256e");
  const bottom = c256(borderCol, "\u2570" + "\u2500".repeat(width - 2) + "\u256f");
  const body = lines.map(ln => {
    const plain = stripAnsi(ln);
    const pad = Math.max(0, width - 4 - plain.length);
    return c256(borderCol, "\u2502 ") + ln + " ".repeat(pad) + c256(borderCol, " \u2502");
  });
  return [top, ...body, bottom];
}

function estimatePrice(modelShort: string, historyList: HistoryMsg[]): PriceEstimate {
  const inToks = historyList.reduce((acc, m) => acc + (m.content ? m.content.length / 4 : 0), 0);
  const outToks = toolCallCount * 120 + historyList.length * 40;
  const rates: Record<string, [number, number]> = {
    "gpt-4o": [2.50, 10.00],
    "gpt-5.6-terra": [5.00, 15.00],
    "gpt-5.6-sol": [3.00, 10.00],
    "gpt-5.5": [4.00, 12.00],
    "claude-sonnet-4.6": [3.00, 15.00],
    "claude-sonnet-5": [3.50, 17.50],
    "claude-opus-4.8": [15.00, 75.00],
    "deepseek-r1": [0.55, 2.19],
  };
  const [inR, outR] = rates[modelShort] || [0.0, 0.0];
  const cost = (inToks / 1e6) * inR + (outToks / 1e6) * outR;
  return { inToks: Math.round(inToks), outToks: Math.round(outToks), cost: cost.toFixed(6) };
}

function compactPrompt(raw: string): string {
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
function letterFilter<T>(query: string, candidates: T[], nameFn: (c: T) => string): T[] {
  if (!query) return candidates;
  const qChars = Array.from(new Set(query.toLowerCase().split('')));
  return candidates.filter(cand => {
    const s = nameFn(cand).toLowerCase();
    return qChars.every(ch => s.includes(ch));
  });
}

function highlightLetters(name: string, query: string): string {
  const qSet = new Set(query.toLowerCase().split(''));
  return name.split('').map(ch => (qSet.has(ch.toLowerCase()) ? c256(theme().title, bold(ch)) : dim(ch))).join('');
}

function paletteCandidates(query: string): PaletteCandidates {
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
let inputHistory: string[] = [];
let historyIdx = 0;
let paletteIndex = 0;
let pending = false;
let modelPickerOpen = false;
let modelPickerIndex = 0;
let spinnerFrame = 0;
const SPINNER = ["\u280b", "\u2819", "\u2839", "\u2838", "\u283c", "\u2834", "\u2826", "\u2827", "\u2807", "\u280f"];

function isPaletteOpen(): boolean {
  return buffer.startsWith("/") && !buffer.includes(" ");
}

function renderModelPicker(): string[] {
  const t = theme();
  const total = MODELS.length;
  const windowSize = 10;
  let start = Math.max(0, modelPickerIndex - Math.floor(windowSize / 2));
  start = Math.min(start, Math.max(0, total - windowSize));
  const end = Math.min(total, start + windowSize);

  const rows: string[] = [dim(` select model — ${modelPickerIndex + 1}/${total}`)];
  if (start > 0) rows.push(dim(`   \u25b2 ${start} more above`));
  for (let i = start; i < end; i++) {
    const m = MODELS[i];
    const selected = i === modelPickerIndex;
    const marker = selected ? c256(t.accent, "\u25b8 ") : "  ";
    const line = `${marker}${m.badge} ${m.short.padEnd(24)} ${dim(`(${m.provider})`)}`;
    rows.push(selected ? bold(line) : line);
  }
  if (end < total) rows.push(dim(`   \u25bc ${total - end} more below`));
  rows.push(dim(" \u2191\u2193 browse   \u2192 / \u21b5 select   esc cancel"));
  return rows;
}

function buildFooterLines(): string[] {
  const width = Math.min(100, Math.max(70, process.stdout.columns || 80));
  const t = theme();
  const elapsedMin = Math.floor((Date.now() - startTime) / 60000);
  const providerLabel = currentModel.provider.toUpperCase();

  const statusLines: string[] = [
    ` Model:  ${c256(36, currentModel.short)} (${providerLabel}) ${currentModel.badge}   Persona: ${c256(t.accent, persona)}   Theme: ${c256(t.accent, t.name)}`,
    ` Status: ${c256(82, 'ACTIVE')}  Auto-Compact: ${c256(220, autoCompact ? 'ON' : 'OFF')}  Skills: ${c256(51, String(SKILLS.length))}  Commands: ${c256(51, String(COMMANDS.length))}`,
    ` Usage:  Turns: ${history.length / 2}  Calls: ${toolCallCount}  Est. Cost: $${estimatePrice(currentModel.short, history).cost}  cwd: ${c256(90, path.basename(process.cwd()))}  up: ${elapsedMin}m`,
  ];
  if (currentModel.short.includes("hyper-nix.2")) {
    statusLines.push(c256(196, " \u26a0\ufe0f  hyper-Nix.2 is INSANELY UNDERTRAINED — expect weird output"));
  }
  const lines = renderBox(`HYPED+ OPENCLAW TUI (${VERSION})`, statusLines, width, t.border, t.title);

  if (modelPickerOpen) {
    lines.push(...renderModelPicker());
  } else if (pending) {
    lines.push(` ${c256(t.title, SPINNER[spinnerFrame % SPINNER.length])} ${dim("agent thinking\u2026  (esc to cancel)")}`);
  } else if (isPaletteOpen()) {
    const query = buffer.slice(1);
    const { cmds, skills } = paletteCandidates(query);
    const rows: PaletteRow[] = [];
    cmds.forEach(cmd => rows.push({ type: "cmd", name: "/" + highlightLetters(cmd.name.slice(1), query), desc: cmd.desc }));
    skills.forEach(sk => rows.push({ type: "skill", name: highlightLetters(sk.name, query), desc: sk.desc }));

    if (rows.length === 0) {
      lines.push(dim(" (no commands or skills match) — press esc to dismiss"));
    } else {
      rows.forEach((row, i) => {
        const marker = i === paletteIndex ? c256(t.accent, "\u25b8 ") : "  ";
        const tagStr = row.type === "skill" ? ` ${c256(90, "skill")}` : "";
        lines.push(`${marker}${row.name}${tagStr}  ${dim(row.desc)}`);
      });
      lines.push(dim(" \u21b9 accept   \u2191\u2193 navigate   esc dismiss"));
    }
  } else {
    lines.push(dim(" /  for commands & skills   alt+y model picker   \u2191\u2193 history   ^L clear   ^C exit"));
  }

  const prompt = c256(t.accent, "hyped+> ");
  lines.push(prompt + buffer);

  return lines;
}

function eraseFooter(): void {
  if (!process.stdout.isTTY) return;
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

function drawFooter(): void {
  if (!process.stdout.isTTY) return;
  const lines = buildFooterLines();
  process.stdout.write(lines.join(NL) + NL);
  footerLineCount = lines.length;
  const promptLen = stripAnsi("hyped+> ").length;
  const col = promptLen + cursorPos + 1;
  process.stdout.write(`${CSI}1A${CSI}${col}G`);
}

function redrawFooter(): void {
  eraseFooter();
  drawFooter();
}

// Permanent, scrolling output — this is the fix for output vanishing too fast:
// it is never cleared, exactly like normal terminal scrollback.
function log(text: string): void {
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
// anything else. The old version cleared the screen 4x in a timed loop to
// animate a mascot; on a real terminal that timing is exactly what let
// later output race ahead of the banner. A single synchronous print can't
// race with anything.
// ---------------------------------------------------------------------------
const HYPED_BANNER_GLYPHS: Record<string, string[]> = {
  H: ["\u2588   \u2588", "\u2588   \u2588", "\u2588\u2588\u2588\u2588\u2588", "\u2588   \u2588", "\u2588   \u2588"],
  Y: ["\u2588   \u2588", " \u2588 \u2588 ", "  \u2588  ", "  \u2588  ", "  \u2588  "],
  P: ["\u2588\u2588\u2588\u2588 ", "\u2588   \u2588", "\u2588\u2588\u2588\u2588 ", "\u2588    ", "\u2588    "],
  E: ["\u2588\u2588\u2588\u2588\u2588", "\u2588    ", "\u2588\u2588\u2588\u2588 ", "\u2588    ", "\u2588\u2588\u2588\u2588\u2588"],
  D: ["\u2588\u2588\u2588\u2588 ", "\u2588   \u2588", "\u2588   \u2588", "\u2588   \u2588", "\u2588\u2588\u2588\u2588 "],
  "+": ["  \u2588  ", "  \u2588  ", "\u2588\u2588\u2588\u2588\u2588", "  \u2588  ", "  \u2588  "],
};
const HYPED_BANNER_WORD = ["H", "Y", "P", "E", "D", "+"];
const HYPED_BANNER_GRADIENT = [39, 45, 99, 135, 171, 213]; // blue -> cyan -> purple -> violet -> pink

function buildHypedBanner(): string[] {
  const rows: string[] = [];
  for (let r = 0; r < 5; r++) {
    let line = "";
    HYPED_BANNER_WORD.forEach((ch, i) => {
      line += c256(HYPED_BANNER_GRADIENT[i], HYPED_BANNER_GLYPHS[ch][r]) + " ";
    });
    rows.push(line);
  }
  return rows;
}

function printBanner(): void {
  console.log("");
  buildHypedBanner().forEach(line => console.log(line));
  console.log(dim("  hyped-pro \u00b7 openclaw tui edition"));
  console.log("");
  console.log(dim("Tips: /  for commands & skills \u00b7 alt+y to switch models \u00b7 /configure to set up \u00b7 /help for everything."));
  console.log("");
}

// ---------------------------------------------------------------------------
// Slash commands
// ---------------------------------------------------------------------------
function renderContextBar(): string {
  const p = estimatePrice(currentModel.short, history);
  const win = CONTEXT_WINDOWS[currentModel.short] || 128000;
  const used = Math.min(1, p.inToks / win);
  const barWidth = 30;
  const filled = Math.round(used * barWidth);
  const bar = c256(used > 0.85 ? 196 : used > 0.6 ? 220 : 82, "\u2588".repeat(filled)) + dim("\u2591".repeat(barWidth - filled));
  return `  [${bar}] ${p.inToks}/${win} tok (${(used * 100).toFixed(1)}%)`;
}

async function handleSlashCommand(cmdStr: string): Promise<void> {
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
        MODELS.forEach((m, i) => out.push(`  ${i + 1}. ${m.badge} ${m.short} (${m.provider})`));
        log(out.join(NL));
      } else {
        const found = MODELS.find(m => m.short.toLowerCase() === argText.toLowerCase());
        if (found) {
          currentModel = found;
          persistConfig();
          log(c256(82, `  Switched to model: ${found.short}`));
        } else {
          log(c256(196, `  Unknown model '${argText}'. Try /model with no args to list.`));
        }
      }
      break;
    }

    case "/configure":
      await runConfigureWizard();
      return; // wizard already redrew (raw mode) or handed back to the shared loop (non-TTY)

    case "/persona": {
      const names = Object.keys(PERSONAS);
      if (!argText) {
        log(c256(96, `\n  Personas: ${names.join(", ")}\n  Current: ${persona}`));
      } else if (names.includes(argText.toLowerCase())) {
        persona = argText.toLowerCase();
        persistConfig();
        log(c256(82, `  Persona set: ${persona}`));
      } else {
        log(c256(196, `  Unknown persona '${argText}'. Options: ${names.join(", ")}`));
      }
      break;
    }

    case "/system-prompt":
      if (argText) {
        systemPrompt = argText;
        log(c256(82, `  System prompt updated (${argText.length} chars)`));
      } else {
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
      const p = estimatePrice(currentModel.short, history);
      log(c256(96, `\n  Est. Input Tokens: ${p.inToks} | Est. Output Tokens: ${p.outToks} | Cost: $${p.cost}`));
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
      } catch (e) {
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
      if (history[history.length - 1].role === 'assistant') history.pop();
      log(c256(90, `  Retrying: "${lastUser.content.slice(0, 60)}"`));
      void runChatTurn(lastUser.content, /*record=*/false);
      return;
    }

    case "/key":
      if (argText) {
        apiKey = argText;
        log(c256(82, `  Key saved (${argText.slice(0, 8)}...)`));
      } else {
        log(c256(96, "  Usage: /key <api-key>"));
      }
      break;

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
function createLineQueue(rl: readline.Interface): LineQueue {
  const buffered: string[] = [];
  const waiters: Array<(v: string | null) => void> = [];
  let ended = false;
  rl.on('line', (l: string) => {
    const w = waiters.shift();
    if (w) w(l);
    else buffered.push(l);
  });
  rl.on('close', () => {
    ended = true;
    let w: ((v: string | null) => void) | undefined;
    while ((w = waiters.shift())) w(null);
  });
  return {
    next(): Promise<string | null> {
      if (buffered.length) return Promise.resolve(buffered.shift() as string);
      if (ended) return Promise.resolve(null);
      return new Promise<string | null>(resolve => waiters.push(resolve));
    },
  };
}

// Set by runSimpleTUI() in the non-TTY fallback; when present, /configure
// pulls from the same queue instead of opening a second readline.Interface
// on the same stdin (two interfaces racing for one stream drops input).
let activeRL: readline.Interface | null = null;
let activeQueue: LineQueue | null = null;

function pauseRawInput(): void {
  process.stdin.removeListener('keypress', onKeypress);
  if (process.stdin.isTTY) process.stdin.setRawMode(false);
}

function resumeRawInput(): void {
  if (process.stdin.isTTY) process.stdin.setRawMode(true);
  process.stdin.on('keypress', onKeypress);
  buffer = "";
  cursorPos = 0;
  footerLineCount = 0;
  drawFooter();
}

async function askLine(queue: LineQueue, promptText: string): Promise<string> {
  process.stdout.write(promptText);
  const line = await queue.next();
  return line === null ? "" : line.trim();
}

async function runConfigureWizard(): Promise<void> {
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
  const q = queue as LineQueue; // always assigned: either shared or just-created above
  console.log(c256(96, "\n  hyped+ configure \u2014 press Enter to keep the current value\n"));

  console.log(c256(90, "  Models:"));
  MODELS.forEach((m, i) => console.log(`    ${i + 1}. ${m.badge} ${m.short} (${m.provider})`));
  const modelAns = await askLine(q, `  choose [1-${MODELS.length}, blank=keep "${currentModel.short}"]: `);
  if (modelAns) {
    const idx = parseInt(modelAns, 10);
    if (idx >= 1 && idx <= MODELS.length) currentModel = MODELS[idx - 1];
  }

  const personaNames = Object.keys(PERSONAS);
  const personaAns = await askLine(q, `  persona [${personaNames.join("/")}, blank=keep "${persona}"]: `);
  if (personaAns && personaNames.includes(personaAns.toLowerCase())) persona = personaAns.toLowerCase();

  if (currentModel.provider === "openai" || currentModel.provider === "anthropic") {
    const keyAns = await askLine(q, `  API key for ${currentModel.provider} [blank=keep existing]: `);
    if (keyAns) apiKey = keyAns;
  } else if (currentModel.provider === "t1") {
    const keyAns = await askLine(q, "  HNX T1 key [blank=keep existing]: ");
    if (keyAns) t1Key = keyAns;
  }

  const compactAns = await askLine(q, `  auto-compact on/off [blank=keep "${autoCompact ? 'on' : 'off'}"]: `);
  if (compactAns) autoCompact = /^(y|yes|on|true)$/i.test(compactAns);

  console.log(c256(90, `  Themes: ${THEMES.map(t => t.name).join(", ")}`));
  const themeAns = await askLine(q, `  theme [blank=keep "${theme().name}"]: `);
  if (themeAns) {
    const found = THEMES.findIndex(t => t.name === themeAns.toLowerCase());
    if (found >= 0) themeIdx = found;
  }

  persistConfig();
  console.log(c256(82, "\n  Configuration saved -> ~/.hyped-plus/config.json\n"));

  if (ownRL && rl) {
    rl.close();
    await new Promise(r => setTimeout(r, 600));
    resumeRawInput();
  }
  // else: leave the shared interface/queue open — runSimpleTUI's loop resumes it
}

// ---------------------------------------------------------------------------
// Chat turn (simulated — hyped+ does not wire real inference here yet;
// this mirrors the previous mock behaviour, now rendered through log()
// so replies persist instead of being wiped by the next redraw)
// ---------------------------------------------------------------------------
let cancelRequested = false;

async function runChatTurn(line: string, record = true): Promise<void> {
  if (record) history.push({ role: 'user', content: line });

  pending = true;
  cancelRequested = false;
  const spin = setInterval(() => { spinnerFrame++; redrawFooter(); }, 90);
  await new Promise(r => setTimeout(r, 500));
  clearInterval(spin);
  pending = false;

  if (cancelRequested) {
    log(dim("  (cancelled)"));
    redrawFooter();
    return;
  }

  const reply = `Hyped+ Agent [${currentModel.short}]: Processed request "${line.slice(0, 40)}${line.length > 40 ? '...' : ''}". All OpenClaw systems operational.`;
  history.push({ role: 'assistant', content: reply });

  log(`${c256(33, 'agent>')} ${reply}`);

  if (autoCompact && history.length > 20) {
    history = history.slice(-10);
  }
}

// ---------------------------------------------------------------------------
// Raw-mode input engine
// ---------------------------------------------------------------------------
function cleanupAndExit(code = 0): never {
  eraseFooter();
  process.stdout.write(SHOW_CURSOR + NL);
  process.exit(code);
}

function submitInput(): void {
  const line = buffer.trim();
  eraseFooter();
  if (line) process.stdout.write(c256(theme().accent, "hyped+> ") + line + NL);
  if (line) { inputHistory.push(line); historyIdx = inputHistory.length; }
  buffer = "";
  cursorPos = 0;
  paletteIndex = 0;
  drawFooter();
  if (!line) return;
  if (line.startsWith("/")) {
    void handleSlashCommand(line);
  } else {
    void runChatTurn(line);
  }
}

function acceptPaletteSelection(): void {
  if (!isPaletteOpen()) return;
  const query = buffer.slice(1);
  const { cmds, skills } = paletteCandidates(query);
  const rows: PaletteRow[] = [
    ...cmds.map(c => ({ type: "cmd" as const, name: c.name, desc: c.desc })),
    ...skills.map(s => ({ type: "skill" as const, name: s.name, desc: s.desc })),
  ];
  if (rows.length === 0) return;
  const pick = rows[Math.min(paletteIndex, rows.length - 1)];
  paletteIndex = 0;
  if (pick.type === "cmd") {
    // commands complete into the input so args can follow
    buffer = pick.name + " ";
    cursorPos = buffer.length;
    redrawFooter();
  } else {
    // skills aren't invocable — accepting one just surfaces what it does
    buffer = "";
    cursorPos = 0;
    log(`  ${c256(51, pick.name)}  ${dim(pick.desc)}`);
  }
}

function movePalette(delta: number): void {
  const query = buffer.slice(1);
  const { cmds, skills } = paletteCandidates(query);
  const total = cmds.length + skills.length;
  if (total === 0) return;
  paletteIndex = (paletteIndex + delta + total) % total;
  redrawFooter();
}

function onKeypress(str: string | undefined, key: readline.Key): void {
  if (!key) return;

  if (key.ctrl && key.name === 'c') { cleanupAndExit(0); }

  if (pending) {
    if (key.name === 'escape') { cancelRequested = true; }
    return; // everything else is swallowed while a reply is in flight
  }

  if (modelPickerOpen) {
    if (key.name === 'up') { modelPickerIndex = (modelPickerIndex - 1 + MODELS.length) % MODELS.length; redrawFooter(); return; }
    if (key.name === 'down') { modelPickerIndex = (modelPickerIndex + 1) % MODELS.length; redrawFooter(); return; }
    if (key.name === 'right' || key.name === 'return') {
      currentModel = MODELS[modelPickerIndex];
      persistConfig();
      modelPickerOpen = false;
      log(c256(82, `  Switched to model: ${currentModel.short}`));
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

  if (key.ctrl && key.name === 'l') { process.stdout.write(CLEAR); footerLineCount = 0; drawFooter(); return; }
  if (key.ctrl && key.name === 'u') { buffer = ""; cursorPos = 0; paletteIndex = 0; redrawFooter(); return; }

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
      if (isPaletteOpen()) { movePalette(-1); return; }
      if (inputHistory.length) {
        historyIdx = Math.max(0, historyIdx - 1);
        buffer = inputHistory[historyIdx] || "";
        cursorPos = buffer.length;
        redrawFooter();
      }
      return;
    case 'down':
      if (isPaletteOpen()) { movePalette(1); return; }
      if (inputHistory.length) {
        historyIdx = Math.min(inputHistory.length, historyIdx + 1);
        buffer = inputHistory[historyIdx] || "";
        cursorPos = buffer.length;
        redrawFooter();
      }
      return;
    case 'escape':
      if (isPaletteOpen()) { buffer = ""; cursorPos = 0; redrawFooter(); }
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
function runSimpleTUI(): void {
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
      if (raw === null) break; // stdin closed, nothing left buffered
      const line = raw.trim();
      if (!line) continue;
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
async function main(argv?: string[]): Promise<void> {
  const args = argv || process.argv.slice(2);
  if (args.includes('--help') || args.includes('-h')) {
    console.log(`hyped+ ${VERSION}\nUsage: hyped+ [--model <short>] [--no-color]\n`);
    return;
  }
  const modelFlagIdx = args.indexOf('--model');
  if (modelFlagIdx >= 0 && args[modelFlagIdx + 1]) {
    const found = MODELS.find(m => m.short === args[modelFlagIdx + 1]);
    if (found) currentModel = found;
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

export { main, MODELS, SKILLS, COMMANDS, THEMES, estimatePrice, compactPrompt, letterFilter };
