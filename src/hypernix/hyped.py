"""hyped — high-quality TUI autonomous agent CLI for the HyperNix family.

V0.71.2: Transformed into a full TUI Agent (similar to openclaw, Claude code CLI,
Claude code app, Qwen 3 coder CLI).

Key Capabilities:
* **Multi-Provider Support**: Local HyperNix models, HyperNix package models,
  OpenAI style API keys, Anthropic API keys, Custom REST API endpoints, and
  HyperNix HNX1/T1 API keys (via Keymaster & Gatekeeper).
* **Extended Model Catalog**: 11 model families (HyperNix, Nix, Qwen 3.5, Nano,
  LLaMA 3, DeepSeek, Mistral, Gemma, Phi, OpenAI, Anthropic) and 25+ curated models.
* **34+ Built-in Unique Tools**: File management, command execution, web search & fetch,
  git operations, code syntax analysis, tree visualization, Keymaster key management,
  Gatekeeper quota monitoring, and HyperNix lifecycle pipelines (download/convert/quantize/train).
* **AI Self-Created Tool Creation Skills**: Dynamic Skill Creator engine allowing the agent
  or user to create, list, execute, and delete custom Python/bash skills stored persistently.
* **TUI Visual Aesthetics**: OpenClaw-inspired multi-panel layout, rolling 256-color gradient
  headers, real-time tool execution cards, agent reasoning blocks, and status bar.
* **Agentic ReAct Loop**: Anti-hallucination system prompts, empirical verification,
  file-grounded code editing, and multi-step autonomous tool execution.
"""
from __future__ import annotations

import html
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import menu as _menu
from .download import KNOWN_MODELS

try:
    import readline  # noqa: F401
except Exception:  # noqa: BLE001
    pass

# ---------------------------------------------------------------------------
# Version & Defaults
# ---------------------------------------------------------------------------

HYPED_VERSION = "v0.71.2"
SKILLS_DIR = Path.home() / ".hypernix" / "skills"
SKILLS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Curated Model Catalog (11 Families, 25+ Models)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelEntry:
    short: str
    repo_id: str
    label: str
    family: str = ""
    badge: str = ""
    provider: str = "local"  # local | openai | anthropic | rest | t1


CURATED_MODELS: tuple[ModelEntry, ...] = (
    # HyperNix Family
    ModelEntry("hyper-nix.2",       "ray0rf1re/hyper-Nix.2",        "⚠ undertrained — see warning",         "HyperNix",   "⚠", "local"),
    ModelEntry("hyper-nix.1",       "ray0rf1re/hyper-nix.1",        "v1 base model — solid, no chat tune",  "HyperNix",   "",  "local"),
    ModelEntry("hyper-nix.3",       "ray0rf1re/hyper-nix.3",        "v3 experimental agentic model",       "HyperNix",   "★", "local"),

    # Nix Family
    ModelEntry("nix2.7a",           "Nix-ai/Nix-2.7a",              "Nix 2.7a — 2B Qwen2-shape",            "Nix",        "★", "local"),
    ModelEntry("nix2.6-mm",         "Nix-ai/Nix2.6-mm",             "Nix 2.6-mm — 3B Qwen2-shape",          "Nix",        "",  "local"),
    ModelEntry("nix2.5",            "ray0rf1re/Nix2.5",             "Nix 2.5 — 3B Qwen2, tied embeds",      "Nix",        "",  "local"),
    ModelEntry("nix3-coder",        "Nix-ai/Nix3-Coder-7B",         "Nix 3 Coder 7B agentic fine-tune",     "Nix",        "★", "local"),

    # Qwen Family
    ModelEntry("qwen3.5-0.8b",      "Qwen/Qwen3.5-0.8B",            "Qwen3.5 0.8B — AutoModel",             "Qwen 3.5",   "",  "local"),
    ModelEntry("qwen3.5-2b",        "Qwen/Qwen3.5-2B",              "Qwen3.5 2B — AutoModel",               "Qwen 3.5",   "",  "local"),
    ModelEntry("qwen3.5-4b",        "Qwen/Qwen3.5-4B",              "Qwen3.5 4B — AutoModel",               "Qwen 3.5",   "★", "local"),
    ModelEntry("qwen3.5-9b",        "Qwen/Qwen3.5-9B",              "Qwen3.5 9B — AutoModel",               "Qwen 3.5",   "",  "local"),

    # Nano Family
    ModelEntry("nano-nano-v4",      "ray0rf1re/Nano-nano-v4",       "Llama-shape, 14L/896d",                "Nano",       "",  "local"),
    ModelEntry("nano-mini-6.99-v2", "ray0rf1re/Nano-mini-6.99-v2",   "Llama-shape, 12L/768d",                "Nano",       "",  "local"),
    ModelEntry("nano-nano-927-v3",  "ray0rf1re/nano-nano-927-v3",    "custom NanoNano, 12L/120d",             "Nano",       "",  "local"),

    # LLaMA 3 Family
    ModelEntry("llama-3.3-70b",     "meta-llama/Llama-3.3-70B-Instruct", "LLaMA 3.3 70B Instruct",            "LLaMA 3",    "★", "local"),
    ModelEntry("llama-3.1-8b",      "meta-llama/Llama-3.1-8B-Instruct",  "LLaMA 3.1 8B Instruct",             "LLaMA 3",    "",  "local"),

    # DeepSeek Family
    ModelEntry("deepseek-r1",       "deepseek-ai/DeepSeek-R1",      "DeepSeek R1 Reasoning Agent",          "DeepSeek",   "★", "local"),
    ModelEntry("deepseek-v3",       "deepseek-ai/DeepSeek-V3",      "DeepSeek V3 671B MoE",                 "DeepSeek",   "",  "local"),

    # Mistral Family
    ModelEntry("mistral-small-24b", "mistralai/Mistral-Small-24B-Instruct-2501", "Mistral Small 24B",      "Mistral",    "",  "local"),
    ModelEntry("mixtral-8x7b",      "mistralai/Mixtral-8x7B-Instruct-v0.1", "Mixtral 8x7B MoE",             "Mistral",    "",  "local"),

    # Gemma Family
    ModelEntry("gemma-2-9b",        "google/gemma-2-9b-it",         "Gemma 2 9B Instruct",                  "Gemma",      "",  "local"),
    ModelEntry("gemma-3-12b",       "google/gemma-3-12b-it",        "Gemma 3 12B Multimodal",               "Gemma",      "★", "local"),

    # Phi Family
    ModelEntry("phi-4-14b",         "microsoft/phi-4",              "Phi-4 14B Reasoning LM",               "Phi",        "★", "local"),
    ModelEntry("phi-3.5-mini",      "microsoft/Phi-3.5-mini-instruct", "Phi-3.5 Mini 3.8B",               "Phi",        "",  "local"),

    # OpenAI API Family
    ModelEntry("openai:gpt-4o",      "gpt-4o",                       "OpenAI GPT-4o API",                    "OpenAI",     "⚡", "openai"),
    ModelEntry("openai:gpt-4o-mini", "gpt-4o-mini",                  "OpenAI GPT-4o Mini API",               "OpenAI",     "⚡", "openai"),
    ModelEntry("openai:o3-mini",     "o3-mini",                      "OpenAI o3-mini Reasoning API",         "OpenAI",     "⚡", "openai"),

    # Anthropic API Family
    ModelEntry("anthropic:claude-3-5-sonnet", "claude-3-5-sonnet-20241022", "Anthropic Claude 3.5 Sonnet", "Anthropic",  "⚡", "anthropic"),
    ModelEntry("anthropic:claude-3-5-haiku",  "claude-3-5-haiku-20241022",  "Anthropic Claude 3.5 Haiku",  "Anthropic",  "⚡", "anthropic"),
)


# ---------------------------------------------------------------------------
# Sampling Profile & Provider Configuration
# ---------------------------------------------------------------------------

@dataclass
class SamplingConfig:
    temperature: float = 0.7
    top_k: int = 40
    top_p: float = 0.95
    max_new_tokens: int = 512
    seed: int | None = None
    persona: str | None = "coder"
    flour_preset: str = "smart"
    provider: str = "local"        # local | openai | anthropic | rest | t1
    api_key: str = ""
    api_base: str = ""
    t1_key: str = ""

    def to_kwargs(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "top_k": self.top_k,
            "top_p": self.top_p,
            "max_new_tokens": self.max_new_tokens,
            "seed": self.seed,
        }


# ---------------------------------------------------------------------------
# ANSI / TUI Helpers
# ---------------------------------------------------------------------------

CSI = "\x1b["
CLEAR = f"{CSI}2J{CSI}H"
HIDE_CURSOR = f"{CSI}?25l"
SHOW_CURSOR = f"{CSI}?25h"

_C256_FG = "\x1b[38;5;{}m"
_C256_BG = "\x1b[48;5;{}m"
_RESET = "\x1b[0m"

# Palettes
_SIGIL_COLORS = [129, 135, 141, 147, 153, 159, 51, 45, 39, 33, 27, 21]
_ACCENT_BLUE   = 33
_ACCENT_CYAN   = 51
_ACCENT_VIOLET = 135
_ACCENT_GOLD   = 220
_ACCENT_GREEN  = 82
_ACCENT_RED    = 196
_ACCENT_GRAY   = 242


def _color(code: int, text: str, *, on: bool = True) -> str:
    return f"{CSI}{code}m{text}{CSI}0m" if on else text


def _c256(n: int, text: str, *, on: bool = True) -> str:
    return f"{_C256_FG.format(n)}{text}{_RESET}" if on else text


def _bold(text: str, *, on: bool = True) -> str:
    return _color(1, text, on=on) if on else text


def _dim(text: str, *, on: bool = True) -> str:
    return f"{CSI}2m{text}{_RESET}" if on else text


def _strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", s)


def _term_width(default: int = 100) -> int:
    try:
        return shutil.get_terminal_size((default, 24)).columns
    except Exception:  # noqa: BLE001
        return default


def _render_sigil_line(line: str, colors: list[int], *, on: bool = True) -> str:
    if not on:
        return line
    out = []
    ci = 0
    for ch in line:
        if ch != ' ':
            out.append(f"{_C256_FG.format(colors[ci % len(colors)])}{ch}")
            ci += 1
        else:
            out.append(ch)
    return ''.join(out) + _RESET


_HYPED_SIGIL = [
    r" ██╗  ██╗██╗   ██╗██████╗ ███████╗██████╗ ",
    r" ██║  ██║╚██╗ ██╔╝██╔══██╗██╔════╝██╔══██╗",
    r" ███████║ ╚████╔╝ ██████╔╝█████╗  ██║  ██║",
    r" ██╔══██║  ╚██╔╝  ██╔═══╝ ██╔══╝  ██║  ██║",
    r" ██║  ██║   ██║   ██║     ███████╗██████╔╝",
]


def _panel(
    title: str,
    body: list[str],
    *,
    width: int,
    color: bool,
    ascii_only: bool,
    title_color: int = 135,
    border_color: int = 33,
) -> list[str]:
    if ascii_only:
        tl, tr, bl, br, h, v = "+", "+", "+", "+", "-", "|"
    else:
        tl, tr, bl, br, h, v = "╭", "╮", "╰", "╯", "─", "│"
    inner = max(1, width - 2)
    if color:
        def _bc(s: str) -> str:
            return f"{_C256_FG.format(border_color)}{s}{_RESET}"
        def _tc(s: str) -> str:
            return f"{_C256_FG.format(title_color)}{_C256_BG.format(234)}\x1b[1m{s}{_RESET}"
    else:
        def _bc(s: str) -> str:
            return s
        def _tc(s: str) -> str:
            return s
    title_render = _tc(f" {title} ")
    title_vis = len(f" {title} ")
    fill = max(0, inner - 2 - title_vis)
    top_left  = _bc(tl + h)
    top_right = _bc(h * fill + tr)
    rows = [top_left + title_render + top_right]
    for ln in body:
        plain = _strip_ansi(ln)
        pad = max(0, inner - len(plain))
        rows.append(_bc(v) + ln + " " * pad + _bc(v))
    rows.append(_bc(bl + h * inner + br))
    return rows


# ---------------------------------------------------------------------------
# AI Self-Created Skill Creator Engine
# ---------------------------------------------------------------------------

class SkillManager:
    """Manages creation, execution, listing, and deletion of custom AI skills."""

    def __init__(self, storage_dir: Path = SKILLS_DIR) -> None:
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def list_skills(self) -> list[dict[str, Any]]:
        skills = []
        for file in self.storage_dir.glob("*.json"):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                skills.append(data)
            except Exception:  # noqa: BLE001
                pass
        return sorted(skills, key=lambda s: s.get("name", ""))

    def create_skill(self, name: str, description: str, code: str, schema: dict[str, Any] | None = None) -> str:
        name_clean = re.sub(r"[^a-zA-Z0-9_]", "_", name.lower())
        json_path = self.storage_dir / f"{name_clean}.json"
        py_path = self.storage_dir / f"{name_clean}.py"

        data = {
            "name": name_clean,
            "description": description,
            "code": code,
            "schema": schema or {"type": "object", "properties": {}},
            "created_at": time.time(),
        }
        json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        py_path.write_text(code, encoding="utf-8")
        return f"Successfully created and registered skill '{name_clean}' at {json_path}"

    def run_skill(self, name: str, args: dict[str, Any]) -> str:
        name_clean = re.sub(r"[^a-zA-Z0-9_]", "_", name.lower())
        py_path = self.storage_dir / f"{name_clean}.py"
        if not py_path.exists():
            return f"Error: Skill '{name_clean}' not found."
        try:
            spec = importlib.util.spec_from_file_location(name_clean, py_path)
            if spec is None or spec.loader is None:
                return f"Error: Failed to load spec for skill '{name_clean}'."
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "execute"):
                res = mod.execute(args)
                return str(res)
            elif hasattr(mod, "main"):
                res = mod.main(args)
                return str(res)
            else:
                return f"Error: Skill module '{name_clean}' has no 'execute(args)' entry point."
        except Exception as exc:  # noqa: BLE001
            return f"Error executing skill '{name_clean}': {exc}"

    def delete_skill(self, name: str) -> str:
        name_clean = re.sub(r"[^a-zA-Z0-9_]", "_", name.lower())
        json_path = self.storage_dir / f"{name_clean}.json"
        py_path = self.storage_dir / f"{name_clean}.py"
        deleted = False
        if json_path.exists():
            json_path.unlink()
            deleted = True
        if py_path.exists():
            py_path.unlink()
            deleted = True
        return f"Deleted skill '{name_clean}'" if deleted else f"Skill '{name_clean}' not found."


# ---------------------------------------------------------------------------
# 34+ Built-in Unique Tools & Integrations
# ---------------------------------------------------------------------------

class ToolRegistry:
    """Registry containing 34+ built-in unique tools for code, system, web, git,
    keymaster, gatekeeper, hypernix pipeline, and skill creator integrations."""

    def __init__(self, skill_manager: SkillManager) -> None:
        self.skill_mgr = skill_manager
        self.tools: dict[str, Callable[..., str]] = {}
        self.schemas: list[dict[str, Any]] = []
        self._register_all()

    def register(self, name: str, description: str, func: Callable[..., str], schema: dict[str, Any]) -> None:
        self.tools[name] = func
        self.schemas.append({
            "name": name,
            "description": description,
            "parameters": schema,
        })

    def _register_all(self) -> None:
        # File System Tools
        self.register("view_file", "Read file lines with optional range", self._view_file, {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
            },
            "required": ["path"],
        })
        self.register("write_file", "Write or overwrite content to a file", self._write_file, {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "overwrite": {"type": "boolean"},
            },
            "required": ["path", "content"],
        })
        self.register("replace_file_content", "Single contiguous block text replacement in a file", self._replace_file_content, {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "target": {"type": "string"},
                "replacement": {"type": "string"},
            },
            "required": ["path", "target", "replacement"],
        })
        self.register("multi_replace", "Multiple non-contiguous text replacements in a file", self._multi_replace, {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "replacements": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "target": {"type": "string"},
                            "replacement": {"type": "string"},
                        },
                        "required": ["target", "replacement"],
                    },
                },
            },
            "required": ["path", "replacements"],
        })
        self.register("list_dir", "List directory files and folders", self._list_dir, {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        })
        self.register("grep_search", "Grep/regex pattern search across directory", self._grep_search, {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "path": {"type": "string"},
                "is_regex": {"type": "boolean"},
            },
            "required": ["query", "path"],
        })
        self.register("find_files", "Find files matching glob pattern", self._find_files, {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["pattern", "path"],
        })
        self.register("delete_file", "Delete a file from disk", self._delete_file, {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        })
        self.register("file_info", "Stat file size, permissions, and modification time", self._file_info, {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        })
        self.register("copy_file", "Copy a file or directory", self._copy_file, {
            "type": "object",
            "properties": {
                "src": {"type": "string"},
                "dst": {"type": "string"},
            },
            "required": ["src", "dst"],
        })
        self.register("move_file", "Move or rename a file or directory", self._move_file, {
            "type": "object",
            "properties": {
                "src": {"type": "string"},
                "dst": {"type": "string"},
            },
            "required": ["src", "dst"],
        })

        # Terminal & Execution Tools
        self.register("run_command", "Run bash shell command", self._run_command, {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
            },
            "required": ["command"],
        })
        self.register("system_info", "Fetch system CPU, RAM, GPU, OS info", self._system_info, {
            "type": "object",
            "properties": {},
        })
        self.register("execute_script", "Execute python code snippet inline", self._execute_script, {
            "type": "object",
            "properties": {"code": {"type": "string"}},
            "required": ["code"],
        })

        # Web & Internet Tools
        self.register("web_search", "Search web via DuckDuckGo HTML parser", self._web_search, {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        })
        self.register("fetch_url", "Fetch web page content and convert HTML to markdown text", self._fetch_url, {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        })

        # Git Tools
        self.register("git_status", "Run git status", self._git_status, {"type": "object", "properties": {}})
        self.register("git_diff", "Run git diff", self._git_diff, {"type": "object", "properties": {}})
        self.register("git_log", "Get recent git commits", self._git_log, {
            "type": "object",
            "properties": {"max_count": {"type": "integer"}},
        })
        self.register("git_commit", "Make git commit", self._git_commit, {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        })
        self.register("git_branch", "List git branches", self._git_branch, {"type": "object", "properties": {}})

        # Code Inspection Tools
        self.register("syntax_check", "Check syntax of python/json/yaml file", self._syntax_check, {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        })
        self.register("code_summary", "Summarize classes and functions in python file", self._code_summary, {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        })
        self.register("tree_view", "Show visual directory tree structure", self._tree_view, {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_depth": {"type": "integer"},
            },
            "required": ["path"],
        })

        # Keymaster & Gatekeeper Tools
        self.register("keymaster_create_key", "Create fresh T1 API key in Keymaster", self._keymaster_create_key, {
            "type": "object",
            "properties": {
                "key_type": {"type": "string"},
                "scopes": {"type": "array", "items": {"type": "string"}},
                "note": {"type": "string"},
            },
        })
        self.register("keymaster_list_keys", "List active T1 keys managed by Keymaster", self._keymaster_list_keys, {
            "type": "object",
            "properties": {"active_only": {"type": "boolean"}},
        })
        self.register("keymaster_revoke_key", "Revoke T1 API key in Keymaster", self._keymaster_revoke_key, {
            "type": "object",
            "properties": {
                "key_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["key_id"],
        })
        self.register("gatekeeper_check_quota", "Check Gatekeeper rate limits and quota", self._gatekeeper_check_quota, {
            "type": "object",
            "properties": {"key_id": {"type": "string"}},
            "required": ["key_id"],
        })
        self.register("gatekeeper_stats", "Get Gatekeeper usage stats for key", self._gatekeeper_stats, {
            "type": "object",
            "properties": {"key_id": {"type": "string"}},
        })

        # HyperNix Pipeline Integrations
        self.register("hypernix_download", "Download model snapshot via hypernix.download", self._hypernix_download, {
            "type": "object",
            "properties": {"repo_id": {"type": "string"}},
            "required": ["repo_id"],
        })
        self.register("hypernix_quantize", "Quantize model GGUF via hypernix.quantize", self._hypernix_quantize, {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "output": {"type": "string"},
                "quant_type": {"type": "string"},
            },
            "required": ["source", "output", "quant_type"],
        })
        self.register("hypernix_train", "Run HyperNix training utility", self._hypernix_train, {
            "type": "object",
            "properties": {
                "model_dir": {"type": "string"},
                "dataset": {"type": "string"},
                "out_dir": {"type": "string"},
                "steps": {"type": "integer"},
            },
            "required": ["model_dir", "dataset", "out_dir"],
        })
        self.register("hypernix_convert", "Convert PyTorch model to GGUF", self._hypernix_convert, {
            "type": "object",
            "properties": {
                "model_dir": {"type": "string"},
                "output": {"type": "string"},
            },
            "required": ["model_dir", "output"],
        })
        self.register("hypernix_assistant", "Run HyperNix environment assistant check", self._hypernix_assistant, {
            "type": "object",
            "properties": {},
        })

        # Skill Creator Tools
        self.register("create_skill", "Create and register a custom Python skill tool dynamically", self._create_skill, {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "code": {"type": "string"},
            },
            "required": ["name", "description", "code"],
        })
        self.register("list_skills", "List all AI self-created active skills", self._list_skills, {"type": "object", "properties": {}})
        self.register("run_skill", "Execute an AI self-created skill", self._run_skill, {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "args": {"type": "object"},
            },
            "required": ["name"],
        })
        self.register("delete_skill", "Delete an AI self-created skill", self._delete_skill, {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        })

    def execute_tool(self, name: str, kwargs: dict[str, Any]) -> str:
        if name in self.tools:
            try:
                return self.tools[name](**kwargs)
            except Exception as exc:  # noqa: BLE001
                return f"Tool Execution Error ({name}): {exc}"
        return f"Error: Tool '{name}' is not registered."

    # Implementations
    def _view_file(self, path: str, start_line: int | None = None, end_line: int | None = None) -> str:
        p = Path(path)
        if not p.exists():
            return f"Error: File '{path}' does not exist."
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        s = (start_line or 1) - 1
        e = end_line or len(lines)
        s = max(0, min(s, len(lines)))
        e = max(s, min(e, len(lines)))
        selected = lines[s:e]
        return "\n".join(f"{i + s + 1:>4} | {line}" for i, line in enumerate(selected))

    def _write_file(self, path: str, content: str, overwrite: bool = True) -> str:
        p = Path(path)
        if p.exists() and not overwrite:
            return f"Error: File '{path}' exists and overwrite is False."
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} characters to {path}"

    def _replace_file_content(self, path: str, target: str, replacement: str) -> str:
        p = Path(path)
        if not p.exists():
            return f"Error: File '{path}' does not exist."
        text = p.read_text(encoding="utf-8")
        if target not in text:
            return f"Error: target string not found in '{path}'."
        text = text.replace(target, replacement, 1)
        p.write_text(text, encoding="utf-8")
        return f"Successfully replaced target content in {path}"

    def _multi_replace(self, path: str, replacements: list[dict[str, str]]) -> str:
        p = Path(path)
        if not p.exists():
            return f"Error: File '{path}' does not exist."
        text = p.read_text(encoding="utf-8")
        count = 0
        for r in replacements:
            t, rep = r.get("target", ""), r.get("replacement", "")
            if t in text:
                text = text.replace(t, rep, 1)
                count += 1
        p.write_text(text, encoding="utf-8")
        return f"Successfully performed {count} replacement(s) in {path}"

    def _list_dir(self, path: str = ".") -> str:
        p = Path(path)
        if not p.exists():
            return f"Error: Path '{path}' does not exist."
        entries = []
        for child in sorted(p.iterdir()):
            kind = "DIR " if child.is_dir() else "FILE"
            size = child.stat().st_size if child.is_file() else 0
            entries.append(f"{kind:<4}  {size:>10} bytes  {child.name}")
        return "\n".join(entries) or "(empty directory)"

    def _grep_search(self, query: str, path: str = ".", is_regex: bool = False) -> str:
        p = Path(path)
        if not p.exists():
            return f"Error: Path '{path}' does not exist."
        matches = []
        pattern = re.compile(query) if is_regex else None
        files = [p] if p.is_file() else p.rglob("*")
        for f in files:
            if f.is_file() and not f.name.startswith("."):
                try:
                    for i, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                        matched = bool(pattern.search(line)) if pattern else (query in line)
                        if matched:
                            matches.append(f"{f}:{i}: {line}")
                            if len(matches) >= 50:
                                break
                except Exception:  # noqa: BLE001
                    pass
            if len(matches) >= 50:
                break
        return "\n".join(matches) or "No matches found."

    def _find_files(self, pattern: str, path: str = ".") -> str:
        p = Path(path)
        if not p.exists():
            return f"Error: Path '{path}' does not exist."
        matches = [str(m) for m in p.rglob(pattern)][:50]
        return "\n".join(matches) or "No matching files."

    def _delete_file(self, path: str) -> str:
        p = Path(path)
        if not p.exists():
            return f"Error: File '{path}' does not exist."
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        return f"Successfully deleted '{path}'"

    def _file_info(self, path: str) -> str:
        p = Path(path)
        if not p.exists():
            return f"Error: Path '{path}' does not exist."
        st = p.stat()
        return (
            f"Path: {p.resolve()}\n"
            f"Type: {'Directory' if p.is_dir() else 'File'}\n"
            f"Size: {st.st_size} bytes\n"
            f"Mode: {oct(st.st_mode)}\n"
            f"Modified: {time.ctime(st.st_mtime)}"
        )

    def _copy_file(self, src: str, dst: str) -> str:
        s, d = Path(src), Path(dst)
        if not s.exists():
            return f"Error: Source '{src}' does not exist."
        d.parent.mkdir(parents=True, exist_ok=True)
        if s.is_dir():
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)
        return f"Successfully copied '{src}' to '{dst}'"

    def _move_file(self, src: str, dst: str) -> str:
        s, d = Path(src), Path(dst)
        if not s.exists():
            return f"Error: Source '{src}' does not exist."
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(s), str(d))
        return f"Successfully moved '{src}' to '{dst}'"

    def _run_command(self, command: str, cwd: str | None = None) -> str:
        try:
            res = subprocess.run(
                command,
                shell=True,
                cwd=cwd or os.getcwd(),
                capture_output=True,
                text=True,
                timeout=30,
            )
            out = res.stdout
            if res.stderr:
                out += f"\n[stderr]\n{res.stderr}"
            return out.strip() or "(no output)"
        except Exception as exc:  # noqa: BLE001
            return f"Command execution error: {exc}"

    def _system_info(self) -> str:
        import platform
        info = [
            f"OS: {platform.system()} {platform.release()} ({platform.machine()})",
            f"Python: {sys.version.split()[0]}",
            f"CPUs: {os.cpu_count() or 1}",
        ]
        try:
            import torch
            info.append(f"PyTorch: {torch.__version__}")
            info.append(f"CUDA Available: {torch.cuda.is_available()}")
            if torch.cuda.is_available():
                info.append(f"GPU: {torch.cuda.get_device_name(0)}")
        except Exception:  # noqa: BLE001
            pass
        return "\n".join(info)

    def _execute_script(self, code: str) -> str:
        try:
            loc: dict[str, Any] = {}
            exec(code, {}, loc)
            return f"Executed script successfully. Result symbols: {list(loc.keys())}"
        except Exception as exc:  # noqa: BLE001
            return f"Script Execution Error: {exc}"

    def _web_search(self, query: str) -> str:
        try:
            q_enc = urllib.parse.quote_plus(query)
            url = f"https://html.duckduckgo.com/html/?q={q_enc}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
            # Basic HTML result extraction
            titles = re.findall(r'<a class="result__url"[^>]*>(.*?)</a>', body)
            snippets = re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', body)
            results = []
            for t, s in zip(titles[:5], snippets[:5], strict=False):
                clean_t = html.unescape(re.sub(r'<[^>]+>', '', t)).strip()
                clean_s = html.unescape(re.sub(r'<[^>]+>', '', s)).strip()
                results.append(f"• {clean_t}\n  {clean_s}")
            return "\n\n".join(results) or f"No web search results returned for '{query}'."
        except Exception as exc:  # noqa: BLE001
            return f"Web search error: {exc}"

    def _fetch_url(self, url: str) -> str:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                html_raw = resp.read().decode("utf-8", errors="ignore")
            text = re.sub(r'<script.*?</script>', '', html_raw, flags=re.DOTALL)
            text = re.sub(r'<style.*?</style>', '', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = html.unescape(text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:4000] + ("…" if len(text) > 4000 else "")
        except Exception as exc:  # noqa: BLE001
            return f"Fetch URL error: {exc}"

    def _git_status(self) -> str:
        return self._run_command("git status -s")

    def _git_diff(self) -> str:
        return self._run_command("git diff")[:3000]

    def _git_log(self, max_count: int = 5) -> str:
        return self._run_command(f"git log -n {max_count} --oneline")

    def _git_commit(self, message: str) -> str:
        return self._run_command(f'git commit -am "{message}"')

    def _git_branch(self) -> str:
        return self._run_command("git branch -a")

    def _syntax_check(self, path: str) -> str:
        p = Path(path)
        if not p.exists():
            return f"Error: '{path}' does not exist."
        if p.suffix == ".py":
            try:
                compile(p.read_text(encoding="utf-8"), path, "exec")
                return f"Syntax OK: '{path}' compiled with no errors."
            except SyntaxError as err:
                return f"Syntax Error in '{path}': line {err.lineno}: {err.msg}"
        elif p.suffix == ".json":
            try:
                json.loads(p.read_text(encoding="utf-8"))
                return f"JSON OK: '{path}' is valid JSON."
            except json.JSONDecodeError as err:
                return f"JSON Error in '{path}': {err}"
        return f"File type {p.suffix} syntax check not implemented."

    def _code_summary(self, path: str) -> str:
        p = Path(path)
        if not p.exists():
            return f"Error: '{path}' does not exist."
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        defs = []
        for i, line in enumerate(lines, 1):
            if re.match(r"^\s*(class|def)\s+[a-zA-Z0-9_]+", line):
                defs.append(f"Line {i:>4}: {line.strip()}")
        return "\n".join(defs) or f"No class/def declarations found in {path}."

    def _tree_view(self, path: str = ".", max_depth: int = 2) -> str:
        p = Path(path)
        if not p.exists():
            return f"Error: '{path}' does not exist."
        out = []

        def _walk(curr: Path, depth: int, prefix: str = "") -> None:
            if depth > max_depth:
                return
            children = sorted([c for c in curr.iterdir() if not c.name.startswith(".")])
            for i, child in enumerate(children):
                is_last = (i == len(children) - 1)
                branch = "└── " if is_last else "├── "
                out.append(f"{prefix}{branch}{child.name}")
                if child.is_dir():
                    _walk(child, depth + 1, prefix + ("    " if is_last else "│   "))

        out.append(p.resolve().name)
        _walk(p, 1)
        return "\n".join(out[:100])

    # Keymaster / Gatekeeper
    def _keymaster_create_key(self, key_type: str = "user", scopes: list[str] | None = None, note: str = "") -> str:
        from .keymaster import Keymaster, KeyScope, KeyType
        km = Keymaster()
        st = {KeyScope(s) for s in (scopes or ["read"])}
        meta = km.create(key_type=KeyType(key_type), scopes=st, note=note)
        return f"Created T1 Key: {meta.key}\nID: {meta.key_id}\nServer: {meta.server_id}"

    def _keymaster_list_keys(self, active_only: bool = True) -> str:
        from .keymaster import Keymaster
        km = Keymaster()
        keys = km.list(active_only=active_only)
        return "\n".join(m.display() for m in keys) or "No active T1 keys found."

    def _keymaster_revoke_key(self, key_id: str, reason: str = "") -> str:
        from .keymaster import Keymaster
        km = Keymaster()
        km.revoke(key_id, reason=reason)
        return f"Revoked T1 Key {key_id}"

    def _gatekeeper_check_quota(self, key_id: str) -> str:
        from .gatekeeper import Gatekeeper
        from .keymaster import Keymaster
        km = Keymaster()
        gk = Gatekeeper(keymaster=km)
        try:
            gk.check_quota(key_id)
            return f"Quota OK for key {key_id}"
        except Exception as exc:  # noqa: BLE001
            return f"Quota Violation: {exc}"

    def _gatekeeper_stats(self, key_id: str | None = None) -> str:
        from .gatekeeper import Gatekeeper
        from .keymaster import Keymaster
        km = Keymaster()
        gk = Gatekeeper(keymaster=km)
        if key_id:
            return json.dumps(gk.get_stats(key_id), indent=2)
        return json.dumps(gk.get_all_stats(), indent=2)

    # HyperNix Pipeline Integrations
    def _hypernix_download(self, repo_id: str) -> str:
        from .download import download_model
        p = download_model(repo_id=repo_id)
        return f"Downloaded snapshot to {p}"

    def _hypernix_quantize(self, source: str, output: str, quant_type: str = "q4_k_m") -> str:
        from .quantize import quantize_gguf
        out = quantize_gguf(source_gguf=source, output_gguf=output, quant_type=quant_type)
        return f"Quantized model to {out}"

    def _hypernix_train(self, model_dir: str, dataset: str, out_dir: str, steps: int = 100) -> str:
        from .train import train
        out = train(model_dir=model_dir, dataset=dataset, out_dir=out_dir, steps=steps)
        return f"Training completed: {out}"

    def _hypernix_convert(self, model_dir: str, output: str) -> str:
        from .convert import convert_to_gguf
        out = convert_to_gguf(model_dir=model_dir, output=output)
        return f"Converted GGUF to {out}"

    def _hypernix_assistant(self) -> str:
        from .utils import diagnostic_info
        return json.dumps(diagnostic_info(), indent=2)

    # Skill Creator Tools
    def _create_skill(self, name: str, description: str, code: str) -> str:
        return self.skill_mgr.create_skill(name, description, code)

    def _list_skills(self) -> str:
        skills = self.skill_mgr.list_skills()
        if not skills:
            return "No custom AI skills registered yet."
        return "\n".join(f"• {s['name']}: {s['description']}" for s in skills)

    def _run_skill(self, name: str, args: dict[str, Any] | None = None) -> str:
        return self.skill_mgr.run_skill(name, args or {})

    def _delete_skill(self, name: str) -> str:
        return self.skill_mgr.delete_skill(name)


# ---------------------------------------------------------------------------
# Multi-Provider Model Runner
# ---------------------------------------------------------------------------

class OvenRunner:
    """Unified interface for generating text across Local, OpenAI, Anthropic, REST, and T1 models."""

    def __init__(self, entry: ModelEntry, config: SamplingConfig) -> None:
        self.entry = entry
        self.config = config
        self.local_oven: Any = None

    def load(self) -> None:
        if self.entry.provider == "local":
            from .old_oven import preheat
            self.local_oven = preheat(self.entry.repo_id, quiet=True)

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        provider = self.entry.provider
        if provider == "local" and self.local_oven:
            return self.local_oven.chat(messages, **kwargs)
        elif provider == "openai":
            return self._call_openai(messages, **kwargs)
        elif provider == "anthropic":
            return self._call_anthropic(messages, **kwargs)
        elif provider == "rest":
            return self._call_rest(messages, **kwargs)
        elif provider == "t1":
            return self._call_t1(messages, **kwargs)
        else:
            if self.local_oven:
                return self.local_oven.chat(messages, **kwargs)
            return "[Error: Model runner not properly loaded.]"

    def _call_openai(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        key = self.config.api_key or os.getenv("OPENAI_API_KEY", "")
        base = self.config.api_base or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        if not key:
            return "[Error: OPENAI_API_KEY not set. Use /key <api_key> in hyped.]"
        url = f"{base.rstrip('/')}/chat/completions"
        payload = {
            "model": self.entry.repo_id,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_new_tokens", self.config.max_new_tokens),
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            return f"[OpenAI API Error: {exc}]"

    def _call_anthropic(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        key = self.config.api_key or os.getenv("ANTHROPIC_API_KEY", "")
        if not key:
            return "[Error: ANTHROPIC_API_KEY not set. Use /key <api_key> in hyped.]"
        url = "https://api.anthropic.com/v1/messages"
        sys_prompt = ""
        user_msgs = []
        for m in messages:
            if m["role"] == "system":
                sys_prompt = m["content"]
            else:
                user_msgs.append(m)
        payload: dict[str, Any] = {
            "model": self.entry.repo_id,
            "messages": user_msgs,
            "max_tokens": kwargs.get("max_new_tokens", self.config.max_new_tokens),
        }
        if sys_prompt:
            payload["system"] = sys_prompt
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data["content"][0]["text"]
        except Exception as exc:  # noqa: BLE001
            return f"[Anthropic API Error: {exc}]"

    def _call_rest(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        base = self.config.api_base or "http://localhost:8000/v1/chat"
        payload = {"messages": messages, "sampling": kwargs}
        req = urllib.request.Request(
            base,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("reply", str(data))
        except Exception as exc:  # noqa: BLE001
            return f"[REST API Error: {exc}]"

    def _call_t1(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        t1_key = self.config.t1_key or os.getenv("HNX_T1_KEY", "")
        if not t1_key:
            return "[Error: HNX T1 API Key not set. Use /key <t1_key> or pass --t1-key.]"
        from .gatekeeper import Gatekeeper
        from .keymaster import Keymaster
        km = Keymaster()
        gk = Gatekeeper(keymaster=km)
        meta = gk.authenticate(t1_key)
        gk.check_quota(meta.key_id, endpoint="/chat", tokens_requested=100)
        reply = self._call_openai(messages, **kwargs) if self.config.api_key else (self.local_oven.chat(messages, **kwargs) if self.local_oven else "T1 Chat Response")
        gk.record_usage(meta.key_id, endpoint="/chat", model=self.entry.short, tokens_used=len(reply) // 4 + 1)
        return reply


# ---------------------------------------------------------------------------
# Configurator Screen
# ---------------------------------------------------------------------------

@dataclass
class Configurator:
    color: bool = True
    ascii_only: bool = False
    width: int | None = None
    chosen_model: ModelEntry | None = None
    sampling: SamplingConfig = field(default_factory=SamplingConfig)

    def render_model_picker(self) -> str:
        c = self.color and not self.ascii_only
        rows: list[str] = []
        rows.append("")

        if c:
            for sigil_line in _HYPED_SIGIL:
                rows.append(_render_sigil_line(sigil_line, _SIGIL_COLORS, on=True))
            rows.append(_dim(f"   autonomous tui agent  ·  {HYPED_VERSION}", on=True))
        else:
            rows.append(f"  === hyped · pick a model ({HYPED_VERSION}) ===")
        rows.append("")

        body: list[str] = []
        family_groups: dict[str, list[tuple[int, ModelEntry]]] = {}
        for i, m in enumerate(CURATED_MODELS, 1):
            family_groups.setdefault(m.family, []).append((i, m))

        family_order = ["HyperNix", "Nix", "Qwen 3.5", "Nano", "LLaMA 3", "DeepSeek", "Mistral", "Gemma", "Phi", "OpenAI", "Anthropic"]
        for fam in family_order:
            entries = family_groups.get(fam, [])
            if not entries:
                continue
            body.append(_color(33, f"  {fam}", on=c))
            for idx, m in entries:
                raw_badge = m.badge if not self.ascii_only else ("*" if m.badge else "")
                badge = _color(93, raw_badge, on=c) if raw_badge else " "
                line = f"  {idx:>2}. {badge} {m.short:<26}  {_color(90, m.label, on=c)}"
                body.append(line)
            body.append("")

        body.append(_color(35, "   0. browse all (full KNOWN_MODELS catalog)", on=c))
        body.append("")
        body.append(_color(90, "  Type a number, or use --model <short> to skip.", on=c))

        rows.extend(body)
        return "\n".join(rows)

    def pick_model_interactive(self) -> ModelEntry:
        print(CLEAR + self.render_model_picker())
        while True:
            try:
                raw = input(f"\n  choose [1-{len(CURATED_MODELS)}, 0=all]: ").strip()
            except EOFError:
                raw = "1"
            if not raw:
                continue
            if raw == "0":
                return self._pick_from_all_known()
            try:
                idx = int(raw)
            except ValueError:
                print(_color(31, "  not a number — try again.", on=self.color))
                continue
            if 1 <= idx <= len(CURATED_MODELS):
                return CURATED_MODELS[idx - 1]
            print(_color(31, f"  out of range — pick 0..{len(CURATED_MODELS)}.", on=self.color))

    def _pick_from_all_known(self) -> ModelEntry:
        c = self.color and not self.ascii_only
        items = sorted(KNOWN_MODELS.items())
        print()
        print(_color(96, _bold(" hyped · all known models", on=c), on=c))
        print()
        for i, (short, info) in enumerate(items, 1):
            print(f"  {i:>3}. {short:<28} {_color(90, info.repo_id, on=c)}")
        print()
        while True:
            try:
                raw = input(f"  choose [1-{len(items)}]: ").strip()
            except EOFError:
                raw = "1"
            if not raw:
                continue
            try:
                idx = int(raw)
            except ValueError:
                print(_color(31, "  not a number.", on=self.color))
                continue
            if 1 <= idx <= len(items):
                short, info = items[idx - 1]
                return ModelEntry(short, info.repo_id, info.notes or "", "Known", "", "local")
            print(_color(31, "  out of range.", on=self.color))

    def pick_persona_interactive(self) -> str | None:
        c = self.color and not self.ascii_only
        names = _menu.MENU.names()
        print()
        print(_color(96, _bold(" hyped · pick a persona", on=c), on=c))
        print()
        for i, name in enumerate(names, 1):
            preview = _menu.MENU.get(name)[:60] + ("…" if len(_menu.MENU.get(name)) > 60 else "")
            print(f"  {i:>2}. {name:<14} {_color(90, preview, on=c)}")
        print(_color(35, "   0. (coder — default agentic coding persona)", on=c))
        print()
        while True:
            try:
                raw = input(f"  choose [0-{len(names)}]: ").strip()
            except EOFError:
                raw = "0"
            if raw in ("", "0"):
                return "coder"
            try:
                idx = int(raw)
            except ValueError:
                print(_color(31, "  not a number.", on=self.color))
                continue
            if 1 <= idx <= len(names):
                return names[idx - 1]
            print(_color(31, "  out of range.", on=self.color))

    def run(self) -> tuple[ModelEntry, SamplingConfig]:
        model = self.pick_model_interactive()
        persona = self.pick_persona_interactive()
        self.sampling.persona = persona
        self.sampling.provider = model.provider
        self.chosen_model = model
        return model, self.sampling


# ---------------------------------------------------------------------------
# TUI Chat & Agentic Execution Screen
# ---------------------------------------------------------------------------

@dataclass
class ChatScreen:
    runner: OvenRunner
    model_entry: ModelEntry
    sampling: SamplingConfig
    color: bool = True
    ascii_only: bool = False
    width: int | None = None
    history: list[dict[str, str]] = field(default_factory=list)
    countertop: Any = None
    bell: Any = None
    flour: Any = None
    tool_registry: ToolRegistry = field(default_factory=lambda: ToolRegistry(SkillManager()))
    tool_call_count: int = 0

    def __post_init__(self) -> None:
        from . import bell as _bell_mod
        from . import countertop as _ct_mod
        from . import flour as _flour_mod
        from . import menu as _menu_mod

        system = (
            "You are Hyped, a world-class autonomous AI coding agent. "
            "You have access to 34+ built-in tools (view_file, write_file, replace_file_content, "
            "run_command, web_search, fetch_url, git_status, keymaster_create_key, create_skill, etc.). "
            "Always inspect actual file contents and logs before making code changes. Never hallucinate syntax. "
            "When you need to use a tool, output a JSON tool call block:\n"
            "```json\n"
            '{"tool": "tool_name", "args": {"arg1": "val1"}}\n'
            "```"
        )
        if self.sampling.persona and self.sampling.persona in _menu_mod.MENU.names():
            system += "\n\nPersona Instructions: " + _menu_mod.MENU.get(self.sampling.persona)

        if self.sampling.flour_preset == "smart":
            self.flour = _flour_mod.Flour.smart_default(template="hyper-nix.2")
        else:
            self.flour = _flour_mod.Flour.off()

        self.bell = _bell_mod.Bell(flour=self.flour)
        self.countertop = _ct_mod.Countertop(
            oven=self.runner,
            system=system,
            bell=self.bell,
            flour=self.flour,
            t1_key=self.sampling.t1_key,
            sampling=self.sampling.to_kwargs(),
        )

    def _w(self) -> int:
        return max(60, self.width or _term_width())

    def render(self) -> str:
        w = self._w()
        c = self.color and not self.ascii_only
        persona = self.sampling.persona or "coder"
        provider = self.model_entry.provider.upper()

        status_body = [
            f" model:    {_color(36, self.model_entry.short, on=c):<24}  "
            f"provider: {_color(33, provider, on=c)}  repo: {_color(90, self.model_entry.repo_id, on=c)}",
            f" persona:  {persona:<24}  tools: {_color(82, f'{len(self.tool_registry.tools)} active', on=c)}  "
            f"calls: {_color(220, str(self.tool_call_count), on=c)}",
            f" turns:    {len(self.countertop.history) // 2:<24}  "
            f"skills: {_color(51, str(len(self.tool_registry.skill_mgr.list_skills())), on=c)}",
        ]
        status_panel = _panel(
            f"hyped · agent ({HYPED_VERSION})", status_body, width=w,
            color=c, ascii_only=self.ascii_only, title_color=96, border_color=135,
        )

        conv_body: list[str] = []
        if not self.countertop.history:
            conv_body.append(_color(90, "  (say something or ask Hyped to write code, search the web, or run commands)", on=c))

        for msg in self.countertop.history[-14:]:
            role = msg["role"]
            content = msg["content"]
            label = (
                _color(36, "user>", on=c) if role == "user"
                else _color(33, "agent>", on=c) if role == "assistant"
                else _color(82, "tool>", on=c)
            )
            for line in _wrap(content, max_width=w - 14):
                conv_body.append(f" {label} {line}")
                label = "      "

            conv_body.append("")

        conv_panel = _panel(
            "transcript", conv_body, width=w,
            color=c, ascii_only=self.ascii_only, title_color=33, border_color=51,
        )

        return "\n".join(status_panel + [""] + conv_panel)

    def run(self) -> None:
        c = self.color and not self.ascii_only
        commands_help = _color(
            90,
            " /help  commands · /tools  list 34+ tools · /skills  created skills · "
            "/key <val>  set key · /reset  clear · /quit",
            on=c,
        )
        try:
            while True:
                sys.stdout.write(CLEAR + self.render() + "\n" + commands_help + "\n\n")
                sys.stdout.flush()
                try:
                    user = input("> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if not user:
                    continue
                if user.startswith("/"):
                    if self._handle_command(user):
                        break
                    continue
                self._chat_turn(user)
        finally:
            sys.stdout.write(SHOW_CURSOR)
            sys.stdout.flush()

    def _handle_command(self, line: str) -> bool:
        c = self.color and not self.ascii_only
        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd in ("/quit", "/exit", "/q"):
            return True
        if cmd in ("/reset", "/clear"):
            self.countertop.reset()
            print(_color(90, "  (history cleared)", on=c))
            time.sleep(0.4)
            return False
        if cmd == "/tools":
            print(_color(96, f"\n  Registered Built-in Tools ({len(self.tool_registry.tools)}):", on=c))
            for s in self.tool_registry.schemas:
                print(f"  • {_color(33, s['name'], on=c)}: {s['description']}")
            input("\n  Press Enter to continue...")
            return False
        if cmd == "/skills":
            print(_color(96, "\n  AI Self-Created Skills:", on=c))
            print(self.tool_registry._list_skills())
            input("\n  Press Enter to continue...")
            return False
        if cmd == "/key":
            if not arg:
                print(_color(33, "  Usage: /key <api_key_or_t1_key>", on=c))
            else:
                self.sampling.api_key = arg
                self.sampling.t1_key = arg
                if arg.startswith("T1_"):
                    self.countertop.authenticate_t1(arg)
                print(_color(82, f"  Key updated successfully ({arg[:8]}...)", on=c))
            time.sleep(1.0)
            return False
        if cmd == "/persona":
            if not arg:
                print(_color(33, "  /persona <name> (e.g. chef, coder, security, architect)", on=c))
            else:
                self.sampling.persona = arg
                print(_color(36, f"  Persona updated → {arg}", on=c))
            time.sleep(0.8)
            return False
        if cmd == "/help":
            print(_color(33, "  Commands: /tools /skills /key <val> /persona <name> /save <path> /reset /quit", on=c))
            time.sleep(1.5)
            return False

        print(_color(31, f"  Unknown command {cmd!r}; try /help", on=c))
        time.sleep(0.6)
        return False

    def _chat_turn(self, user: str) -> None:
        c = self.color and not self.ascii_only
        sys.stdout.write(_color(33, "\nagent> thinking…", on=c))
        sys.stdout.flush()

        reply = self.countertop.say(user)
        sys.stdout.write("\r" + " " * 40 + "\r")

        # Check for tool call pattern in response
        tool_matches = re.findall(r"```json\s*(\{\s*\"tool\".*?\})\s*```", reply, flags=re.DOTALL)
        if not tool_matches:
            tool_matches = re.findall(r"(\{\s*\"tool\"\s*:\s*\"[^\"]+\".*?\})", reply, flags=re.DOTALL)

        if tool_matches:
            for match in tool_matches:
                try:
                    call_data = json.loads(match)
                    tool_name = call_data.get("tool")
                    tool_args = call_data.get("args", {})
                    if tool_name and tool_name in self.tool_registry.tools:
                        self.tool_call_count += 1
                        card_body = [
                            f" {_color(220, '[TOOL RUNNING]', on=c)} {_color(36, tool_name, on=c)}",
                            f" args: {json.dumps(tool_args)}",
                        ]
                        card = _panel("tool execution", card_body, width=self._w() - 4, color=c, ascii_only=self.ascii_only, title_color=220, border_color=220)
                        print("\n" + "\n".join(card))

                        output = self.tool_registry.execute_tool(tool_name, tool_args)
                        out_preview = output[:300] + ("…" if len(output) > 300 else "")

                        res_body = [
                            f" {_color(82, '[TOOL SUCCESS]', on=c)} {_color(36, tool_name, on=c)}",
                            f" output: {out_preview}",
                        ]
                        res_card = _panel("tool result", res_body, width=self._w() - 4, color=c, ascii_only=self.ascii_only, title_color=82, border_color=82)
                        print("\n" + "\n".join(res_card))

                        # Observation follow up turn
                        obs_msg = f"Tool '{tool_name}' Output:\n{output}"
                        self.countertop.say(obs_msg)
                except Exception:  # noqa: BLE001
                    pass

        sys.stdout.write(_color(33, f"agent> {self.countertop.history[-1]['content']}\n\n", on=c))
        sys.stdout.flush()
        time.sleep(0.4)


# ---------------------------------------------------------------------------
# Helpers & CLI Entry Point
# ---------------------------------------------------------------------------

def _wrap(text: str, *, max_width: int) -> list[str]:
    out: list[str] = []
    for paragraph in text.splitlines() or [""]:
        if not paragraph:
            out.append("")
            continue
        line = ""
        for word in paragraph.split(" "):
            if len(line) + len(word) + 1 > max_width:
                if line:
                    out.append(line)
                line = word
            else:
                line = (line + " " + word) if line else word
        if line:
            out.append(line)
    return out or [""]


def _resolve_short_name(short: str) -> ModelEntry | None:
    key = short.lower()
    for m in CURATED_MODELS:
        if m.short.lower() == key:
            return m
    info = KNOWN_MODELS.get(key)
    if info is not None:
        return ModelEntry(short, info.repo_id, info.notes or "", "Known", "", "local")
    return None


def cli_main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    color = True
    ascii_only = False
    model_short: str | None = None
    persona: str | None = None
    t1_key: str | None = os.getenv("HNX_T1_KEY", None)

    if "--no-color" in args:
        color = False
        args.remove("--no-color")
    if "--ascii" in args:
        ascii_only = True
        args.remove("--ascii")
    if "--model" in args:
        i = args.index("--model")
        if i + 1 < len(args):
            model_short = args[i + 1]
            del args[i : i + 2]
    if "--persona" in args:
        i = args.index("--persona")
        if i + 1 < len(args):
            persona = args[i + 1]
            del args[i : i + 2]
    if "--t1-key" in args:
        i = args.index("--t1-key")
        if i + 1 < len(args):
            t1_key = args[i + 1]
            del args[i : i + 2]

    if "--help" in args or "-h" in args:
        print(
            f"hyped {HYPED_VERSION} — autonomous TUI AI agent CLI\n"
            "usage: hyped [--model SHORT] [--persona NAME] [--t1-key KEY] [--no-color] [--ascii]\n"
            "  --model     skip the picker and load named model\n"
            "  --persona   use a named system prompt persona\n"
            "  --t1-key    pass HNX1/T1 API key for Gatekeeper quota enforcement\n"
            "  --no-color  disable ANSI colour\n"
            "  --ascii     ASCII fallback",
        )
        return 0

    cfg = Configurator(color=color, ascii_only=ascii_only)
    if model_short:
        entry = _resolve_short_name(model_short)
        if entry is None:
            print(f"hyped: unknown model {model_short!r}", file=sys.stderr)
            return 2
        sampling = SamplingConfig()
        if persona:
            sampling.persona = persona
    else:
        try:
            entry, sampling = cfg.run()
        except KeyboardInterrupt:
            print()
            return 130
        if persona:
            sampling.persona = persona

    if t1_key:
        sampling.t1_key = t1_key

    print(_color(96, _bold(f"\n  initializing agent runner for {entry.short} ({entry.repo_id})…", on=color), on=color))
    runner = OvenRunner(entry, sampling)
    try:
        runner.load()
    except Exception as exc:  # noqa: BLE001
        print(f"hyped: model runner load note: {exc}", file=sys.stderr)

    chat = ChatScreen(
        runner=runner, model_entry=entry, sampling=sampling,
        color=color, ascii_only=ascii_only,
    )
    try:
        chat.run()
    finally:
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.flush()
    print(_color(90, "  goodbye.", on=color))
    return 0


__all__ = [
    "CURATED_MODELS",
    "ChatScreen",
    "Configurator",
    "ModelEntry",
    "OvenRunner",
    "SamplingConfig",
    "SkillManager",
    "ToolRegistry",
    "cli_main",
]
