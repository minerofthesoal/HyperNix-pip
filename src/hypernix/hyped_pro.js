#!/usr/bin/env node
/**
 * hyped+ (hyped-pro) — High-performance Node.js TUI Agent CLI for HyperNix.
 *
 * Highly inspired by OpenClaw, Qwen Code CLI, Claude Desktop, and Claude CLI.
 * Uses Hyped TUI 256-color theme, locked multi-panel layout, startup animation,
 * 2D pixel art coffee mascot, price estimator, prompt compactor, auto-compaction,
 * and slash command autocompletion.
 */

const fs = require('fs');
const path = require('path');
const readline = require('readline');
const { spawn } = require('child_process');

const VERSION = "v0.71.4b2";

// ANSI Codes & Colors
const CSI = "\x1b[";
const CLEAR = `${CSI}2J${CSI}H`;
const HIDE_CURSOR = `${CSI}?25l`;
const SHOW_CURSOR = `${CSI}?25h`;
const RESET = `${CSI}0m`;

function c256(code, text) {
  return `${CSI}38;5;${code}m${text}${RESET}`;
}
function bg256(code, text) {
  return `${CSI}48;5;${code}m${text}${RESET}`;
}
function bold(text) {
  return `${CSI}1m${text}${RESET}`;
}
function dim(text) {
  return `${CSI}2m${text}${RESET}`;
}
function stripAnsi(str) {
  return str.replace(/\x1b\[[0-9;?]*[a-zA-Z]/g, '');
}

// 2D Pixel Art Coffee Mascot (Steaming Coffee Mug)
const COFFEE_MASCOT_FRAMES = [
  [
    "      )  (  (     ",
    "     (   )  )     ",
    "    .----------.  ",
    "   /  HYPED+   \\_ ",
    "  |  ☕ COFFEE  | )",
    "   \\  OPENCLAW /  ",
    "    `---------'   "
  ],
  [
    "     (   )  )     ",
    "      )  (  (     ",
    "    .----------.  ",
    "   /  HYPED+   \\_ ",
    "  |  ☕ COFFEE  | )",
    "   \\  OPENCLAW /  ",
    "    `---------'   "
  ]
];

// OpenClaw Header ASCII Sigil
const OPENCLAW_SIGIL = [
  " █░█ █░█ █▀█ █▀▀ █▀▄ █░█ █▀█ █▀█ ",
  " █▀█ ░█░ █▀▀ ██▄ █▄▀ ███ █▀▀ █▄█ ",
  "  hyped-pro · openclaw tui edition  "
];

// Curated Models Catalog
const MODELS = [
  { short: "qwen3.7-plus", repo: "Qwen/Qwen3.7-Plus", provider: "local", badge: "★" },
  { short: "kimi-k3", repo: "MoonshotAI/Kimi-K3", provider: "local", badge: "★" },
  { short: "claude-sonnet-4.6", repo: "claude-4-6-sonnet", provider: "anthropic", badge: "⚡" },
  { short: "claude-sonnet-5", repo: "claude-5-sonnet", provider: "anthropic", badge: "⚡" },
  { short: "claude-opus-4.8", repo: "claude-4-8-opus", provider: "anthropic", badge: "⚡" },
  { short: "fable-5", repo: "fable-ai/fable-5", provider: "local", badge: "★" },
  { short: "gpt-4o", repo: "gpt-4o", provider: "openai", badge: "⚡" },
  { short: "gpt-5.6-terra", repo: "gpt-5.6-terra", provider: "openai", badge: "⚡" },
  { short: "gpt-5.6-sol", repo: "gpt-5.6-sol", provider: "openai", badge: "⚡" },
  { short: "gpt-5.5", repo: "gpt-5.5", provider: "openai", badge: "⚡" },
  { short: "deepseek-r1", repo: "deepseek-ai/DeepSeek-R1", provider: "local", badge: "★" },
  { short: "deekseek-v4flash", repo: "deepseek-ai/DeepSeek-V4-Flash", provider: "local", badge: "⚡" },
  { short: "gemma-4-27b", repo: "google/gemma-4-27b-it", provider: "local", badge: "★" },
  { short: "hyper-nix.2", repo: "ray0rf1re/hyper-Nix.2", provider: "local", badge: "⚠️" }
];

// Agent State
let currentModel = MODELS[0];
let systemPrompt = "You are Hyped+ OpenClaw Agent, a world-class autonomous TUI coding assistant.";
let history = [];
let toolCallCount = 0;
let autoCompact = true;
let apiKey = process.env.OPENAI_API_KEY || process.env.ANTHROPIC_API_KEY || "";
let t1Key = process.env.HNX_T1_KEY || "";

function renderBox(title, lines, width = 80, borderCol = 135, titleCol = 96) {
  const top = c256(borderCol, "╭") + bg256(234, c256(titleCol, bold(` ${title} `))) + c256(borderCol, "─".repeat(Math.max(0, width - title.length - 4)) + "╮");
  const bottom = c256(borderCol, "╰" + "─".repeat(width - 2) + "╯");
  const body = lines.map(ln => {
    const plain = stripAnsi(ln);
    const pad = Math.max(0, width - 4 - plain.length);
    return c256(borderCol, "│ ") + ln + " ".repeat(pad) + c256(borderCol, " │");
  });
  return [top, ...body, bottom];
}

function estimatePrice(modelShort, historyList) {
  const inToks = historyList.reduce((acc, m) => acc + (m.content ? m.content.length / 4 : 0), 0);
  const outToks = toolCallCount * 120 + historyList.length * 40;
  const rates = {
    "gpt-4o": [2.50, 10.00],
    "gpt-5.6-terra": [5.00, 15.00],
    "gpt-5.6-sol": [3.00, 10.00],
    "gpt-5.5": [4.00, 12.00],
    "claude-sonnet-4.6": [3.00, 15.00],
    "claude-sonnet-5": [3.50, 17.50],
    "claude-opus-4.8": [15.00, 75.00],
    "deepseek-r1": [0.55, 2.19]
  };
  const [inR, outR] = rates[modelShort] || [0.0, 0.0];
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

async function runStartupAnimation() {
  process.stdout.write(CLEAR + HIDE_CURSOR);
  for (let step = 0; step < 4; step++) {
    const frame = COFFEE_MASCOT_FRAMES[step % 2];
    process.stdout.write(CLEAR);
    console.log(c256(220, "  🚀 INITIALIZING HYPED+ OPENCLAW TUI ENGINE..."));
    console.log(c256(135, OPENCLAW_SIGIL[0]));
    console.log(c256(51, OPENCLAW_SIGIL[1]));
    console.log(c256(242, OPENCLAW_SIGIL[2]));
    console.log("");
    frame.forEach(ln => console.log(c256(214, "    " + ln)));
    console.log(dim(`\n  Loading modules... version ${VERSION}`));
    await new Promise(r => setTimeout(r, 220));
  }
  process.stdout.write(SHOW_CURSOR);
}

function renderUI() {
  const width = Math.max(70, process.stdout.columns || 80);
  const statusLines = [
    ` Model:     ${c256(36, currentModel.short)} (${currentModel.provider}) ${currentModel.badge}`,
    ` Status:    ${c256(82, 'ACTIVE')}  |  Auto-Compact: ${c256(220, autoCompact ? 'ON' : 'OFF')}  |  Tools: ${c256(51, '34 Registered')}`,
    ` Usage:     Turns: ${history.length / 2}  |  Calls: ${toolCallCount}  |  Est. Cost: $${estimatePrice(currentModel.short, history).cost}`
  ];
  if (currentModel.short.includes("hyper-nix.2")) {
    statusLines.push(c256(196, " ⚠️ WARNING: hyper-Nix.2 is INSANELY UNDERTRAINED!"));
  }

  const statusBox = renderBox(`HYPED+ OPENCLAW TUI (${VERSION})`, statusLines, width, 135, 220);

  const transcriptLines = [];
  if (history.length === 0) {
    transcriptLines.push(dim("  (Welcome to hyped+ TUI. Type a prompt or /help for slash commands)"));
  } else {
    history.slice(-12).forEach(m => {
      const tag = m.role === 'user' ? c256(36, 'user>') : c256(33, 'agent>');
      transcriptLines.push(` ${tag} ${m.content}`);
    });
  }

  const transcriptBox = renderBox("transcript", transcriptLines, width, 33, 51);
  return [...statusBox, "", ...transcriptBox].join("\n");
}

function handleSlashCommand(cmdStr) {
  const [cmd, ...args] = cmdStr.trim().split(/\s+/);
  const argText = args.join(" ");

  switch (cmd.toLowerCase()) {
    case "/help":
      console.log(c256(96, "\n  hyped+ commands:"));
      const cmds = [
        ["/model <name>",         "Switch model catalog entry"],
        ["/system-prompt <text>", "Set custom system prompt"],
        ["/compact-prompt",       "Compact system prompt into dense directives"],
        ["/auto-compact",         "Toggle auto context compaction"],
        ["/price",                "Display price & token estimate breakdown"],
        ["/key <val>",            "Set API key (OpenAI/Anthropic/T1)"],
        ["/clear",                "Clear conversation history"],
        ["/quit",                 "Exit hyped+ TUI"],
      ];
      cmds.forEach(([name, desc]) => {
        console.log(`  ${c256(33, name).padEnd(25 + 15)} ${dim(desc)}`);
      });
      console.log("");
      break;

    case "/model":
      if (!argText) {
        console.log(c256(96, "\n  Available Models:"));
        MODELS.forEach((m, i) => console.log(`  ${i+1}. ${m.badge} ${m.short} (${m.provider})`));
      } else {
        const found = MODELS.find(m => m.short.toLowerCase() === argText.toLowerCase());
        if (found) {
          currentModel = found;
          console.log(c256(82, `  Switched to model: ${found.short}`));
        } else {
          console.log(c256(196, `  Unknown model '${argText}'`));
        }
      }
      break;

    case "/system-prompt":
      if (argText) {
        systemPrompt = argText;
        console.log(c256(82, `  System prompt updated (${argText.length} chars)`));
      } else {
        console.log(c256(96, `\n  Current System Prompt:\n  ${systemPrompt}`));
      }
      break;

    case "/compact-prompt":
      systemPrompt = compactPrompt(systemPrompt);
      console.log(c256(82, `\n  Compacted System Prompt:\n  ${systemPrompt}`));
      break;

    case "/auto-compact":
      autoCompact = !autoCompact;
      console.log(c256(82, `  Auto compaction ${autoCompact ? 'enabled' : 'disabled'}`));
      break;

    case "/price":
      const p = estimatePrice(currentModel.short, history);
      console.log(c256(96, `\n  Est. Input Tokens: ${p.inToks} | Est. Output Tokens: ${p.outToks} | Cost: $${p.cost}`));
      break;

    case "/clear":
    case "/reset":
      history = [];
      console.log(dim("  History cleared."));
      break;

    case "/quit":
    case "/exit":
      process.exit(0);

    default:
      console.log(c256(196, `  Unknown command '${cmd}'. Try /help.`));
  }
}

async function main() {
  await runStartupAnimation();

  const COMMANDS = ["/help", "/model", "/system-prompt", "/compact-prompt", "/auto-compact", "/price", "/key", "/clear", "/quit"];

  function completer(line) {
    const hits = COMMANDS.filter(c => c.startsWith(line));
    return [hits.length ? hits : COMMANDS, line];
  }

  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    completer
  });

  const promptUser = () => {
    process.stdout.write(CLEAR + renderUI() + "\n\n");
    rl.question(c256(33, "hyped+> "), async (input) => {
      const line = input.trim();
      if (!line) {
        promptUser();
        return;
      }
      if (line.startsWith("/")) {
        handleSlashCommand(line);
        setTimeout(promptUser, 1000);
        return;
      }

      history.push({ role: 'user', content: line });

      // Simulated agent turn with tool execution check
      process.stdout.write(c256(33, "\nagent> thinking…"));
      await new Promise(r => setTimeout(r, 400));

      const reply = `Hyped+ Agent [${currentModel.short}]: Processed request "${line.slice(0, 40)}...". All OpenClaw systems operational.`;
      history.push({ role: 'assistant', content: reply });

      if (autoCompact && history.length > 20) {
        history = history.slice(-10);
      }

      promptUser();
    });
  };

  promptUser();
}

if (require.main === module) {
  main().catch(err => {
    console.error("hyped+ error:", err);
    process.exit(1);
  });
}

module.exports = { main, MODELS, estimatePrice, compactPrompt };
