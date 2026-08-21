"""hypernix.hyped_pro_tools — real file creation/editing/search tools for
hyped-pro's agentic chat loop.

Every tool here does exactly what it says — there's no simulated or
stubbed path. All operations are scoped to a workspace root (the
directory hyped-pro was launched from, or ``HYPED_PRO_WORKSPACE`` if set)
and every resolved path is checked to stay inside it before anything
touches disk; a path that would escape the workspace (``../../etc/passwd``,
an absolute path elsewhere, a symlink pointing out) is refused rather than
followed.

Definitions here are vendor-neutral (name, description, a JSON-schema
``parameters`` block) and converted to whichever wire format a given
backend needs — Anthropic's ``tools``/``input_schema`` shape, or the
OpenAI-compatible ``tools``/``function``/``parameters`` shape used by
OpenAI, DashScope (Qwen), Moonshot (Kimi), and llama-cpp-python's own
``create_chat_completion(tools=...)`` for GGUF models whose chat template
supports function calling.

Every tool call is logged to stderr as it executes — real-time, visible
on the same terminal the rest of this codebase already prints backend
logs to — so file operations a model makes are never silent.
"""
from __future__ import annotations

import fnmatch
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ToolError(RuntimeError):
    """A real, reportable tool failure — fed back to the model as the
    tool result (so it can react/retry), never swallowed."""

    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


def _log(msg: str) -> None:
    print(f"[hypernix.tools] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Workspace scoping — every tool call resolves through this first.
# ---------------------------------------------------------------------------


def workspace_root() -> Path:
    override = os.environ.get("HYPED_PRO_WORKSPACE")
    return Path(override).expanduser().resolve() if override else Path.cwd().resolve()


def _resolve_safe_path(rel_path: str) -> Path:
    root = workspace_root()
    candidate = (root / rel_path).resolve() if not Path(rel_path).is_absolute() else Path(rel_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ToolError(
            "TOOL-PATH-001",
            f"{rel_path!r} resolves outside the workspace ({root}) — refusing. "
            f"Set HYPED_PRO_WORKSPACE to widen it if this is intentional.",
        ) from exc
    return candidate


# ---------------------------------------------------------------------------
# Real implementations
# ---------------------------------------------------------------------------

_MAX_READ_BYTES = 512_000    # ~512KB — enough for any real source file, not a whole log dump
_MAX_SEARCH_MATCHES = 200
_MAX_SEARCH_FILES = 5000


def create_file(path: str, content: str) -> str:
    dest = _resolve_safe_path(path)
    if dest.exists():
        raise ToolError("TOOL-CREATE-001", f"{path!r} already exists — use edit_file to modify it, not create_file.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    _log(f"create_file: wrote {len(content)} bytes -> {dest}")
    return f"Created {path} ({len(content)} bytes)."


def edit_file(path: str, old_str: str, new_str: str) -> str:
    dest = _resolve_safe_path(path)
    if not dest.exists():
        raise ToolError("TOOL-EDIT-001", f"{path!r} does not exist — use create_file for a new file.")
    if dest.is_dir():
        raise ToolError("TOOL-EDIT-002", f"{path!r} is a directory, not a file.")
    text = dest.read_text(encoding="utf-8")
    count = text.count(old_str)
    if count == 0:
        raise ToolError("TOOL-EDIT-003", f"old_str not found in {path!r} — it must match the file's current content exactly, including whitespace.")
    if count > 1:
        raise ToolError("TOOL-EDIT-004", f"old_str matches {count} places in {path!r} — it must be unique. Include more surrounding context.")
    new_text = text.replace(old_str, new_str, 1)
    dest.write_text(new_text, encoding="utf-8")
    delta = len(new_str) - len(old_str)
    _log(f"edit_file: replaced {len(old_str)} chars with {len(new_str)} chars in {dest} ({delta:+d})")
    return f"Edited {path} ({delta:+d} chars)."


def read_file(path: str, start_line: int | None = None, end_line: int | None = None) -> str:
    src = _resolve_safe_path(path)
    if not src.exists():
        raise ToolError("TOOL-READ-001", f"{path!r} does not exist.")
    if src.is_dir():
        raise ToolError("TOOL-READ-002", f"{path!r} is a directory — use list_directory instead.")
    size = src.stat().st_size
    if size > _MAX_READ_BYTES and start_line is None and end_line is None:
        raise ToolError(
            "TOOL-READ-003",
            f"{path!r} is {size} bytes, over the {_MAX_READ_BYTES}-byte read limit — "
            f"pass start_line/end_line to read a slice instead of the whole file.",
        )
    try:
        text = src.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ToolError("TOOL-READ-004", f"{path!r} isn't valid UTF-8 text: {exc}") from exc
    if start_line is None and end_line is None:
        _log(f"read_file: {dest_repr(src)} ({len(text)} chars)")
        return text
    lines = text.splitlines()
    s = max(1, start_line or 1)
    e = min(len(lines), end_line or len(lines))
    _log(f"read_file: {dest_repr(src)} lines {s}-{e}")
    numbered = "\n".join(f"{i}\t{lines[i - 1]}" for i in range(s, e + 1))
    return numbered


def dest_repr(p: Path) -> str:
    try:
        return str(p.relative_to(workspace_root()))
    except ValueError:
        return str(p)


def list_directory(path: str = ".") -> str:
    d = _resolve_safe_path(path)
    if not d.exists():
        raise ToolError("TOOL-LIST-001", f"{path!r} does not exist.")
    if not d.is_dir():
        raise ToolError("TOOL-LIST-002", f"{path!r} is a file, not a directory.")
    entries = sorted(d.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    lines = []
    for e in entries:
        if e.name.startswith(".git") or e.name == "__pycache__" or e.name == "node_modules":
            continue
        marker = "/" if e.is_dir() else ""
        size = "" if e.is_dir() else f"  ({e.stat().st_size}B)"
        lines.append(f"{e.name}{marker}{size}")
    _log(f"list_directory: {dest_repr(d)} ({len(lines)} entries)")
    return "\n".join(lines) if lines else "(empty directory)"


def search_files(query: str, path: str = ".", mode: str = "content", glob: str | None = None) -> str:
    root = _resolve_safe_path(path)
    if not root.exists():
        raise ToolError("TOOL-SEARCH-001", f"{path!r} does not exist.")

    skip_dirs = {".git", "__pycache__", "node_modules", ".pytest_cache", ".ruff_cache", "dist", "build"}

    def walk() -> list[Path]:
        out: list[Path] = []
        stack = [root] if root.is_dir() else [root.parent]
        start = root if root.is_file() else None
        if start is not None:
            return [start]
        while stack and len(out) < _MAX_SEARCH_FILES:
            cur = stack.pop()
            try:
                children = list(cur.iterdir())
            except OSError:
                continue
            for c in children:
                if c.name in skip_dirs:
                    continue
                if c.is_dir():
                    stack.append(c)
                else:
                    if glob and not fnmatch.fnmatch(c.name, glob):
                        continue
                    out.append(c)
        return out

    files = walk()

    if mode == "filename":
        matches = [f for f in files if fnmatch.fnmatch(f.name, query)]
        _log(f"search_files(filename): {query!r} under {dest_repr(root)} -> {len(matches)} matches")
        return "\n".join(dest_repr(f) for f in matches[:_MAX_SEARCH_MATCHES]) or "(no matches)"

    if mode != "content":
        raise ToolError("TOOL-SEARCH-002", f"unknown mode {mode!r} — use 'content' or 'filename'.")

    try:
        pattern = re.compile(query)
    except re.error as exc:
        raise ToolError("TOOL-SEARCH-003", f"invalid regex {query!r}: {exc}") from exc

    results: list[str] = []
    for f in files:
        if len(results) >= _MAX_SEARCH_MATCHES:
            break
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                results.append(f"{dest_repr(f)}:{i}: {line.strip()[:200]}")
                if len(results) >= _MAX_SEARCH_MATCHES:
                    break
    _log(f"search_files(content): {query!r} under {dest_repr(root)} -> {len(results)} matches ({len(files)} files scanned)")
    return "\n".join(results) or "(no matches)"


# ---------------------------------------------------------------------------
# Tool registry — one source of truth, converted to each vendor's wire format.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolDef:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema
    fn: Callable[..., str]


TOOLS: list[ToolDef] = [
    ToolDef(
        name="create_file",
        description="Create a new file with the given content. Fails if the file already exists — use edit_file to modify an existing one.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to the workspace root."},
                "content": {"type": "string", "description": "Full file content to write."},
            },
            "required": ["path", "content"],
        },
        fn=create_file,
    ),
    ToolDef(
        name="edit_file",
        description="Replace one exact occurrence of old_str with new_str in an existing file. old_str must match the file's current content exactly (including whitespace) and appear exactly once — read_file first if unsure of the exact text.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to the workspace root."},
                "old_str": {"type": "string", "description": "Exact text to replace; must be unique in the file."},
                "new_str": {"type": "string", "description": "Replacement text. Empty string deletes old_str."},
            },
            "required": ["path", "old_str", "new_str"],
        },
        fn=edit_file,
    ),
    ToolDef(
        name="read_file",
        description="Read a file's contents, optionally a specific line range (1-indexed, inclusive). Reading a range returns line-numbered output.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to the workspace root."},
                "start_line": {"type": "integer", "description": "First line to read (1-indexed). Omit to read from the start."},
                "end_line": {"type": "integer", "description": "Last line to read (inclusive). Omit to read to the end."},
            },
            "required": ["path"],
        },
        fn=read_file,
    ),
    ToolDef(
        name="list_directory",
        description="List the contents of a directory (non-recursive). Directories are marked with a trailing /.",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Path relative to the workspace root. Defaults to the workspace root itself."}},
            "required": [],
        },
        fn=list_directory,
    ),
    ToolDef(
        name="search_files",
        description="Search files under a directory. mode='content' (default) treats query as a regex searched line-by-line across file contents. mode='filename' treats query as a glob pattern (e.g. '*.py') matched against filenames.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Regex (content mode) or glob pattern (filename mode)."},
                "path": {"type": "string", "description": "Directory to search under. Defaults to the workspace root."},
                "mode": {"type": "string", "enum": ["content", "filename"], "description": "Search mode. Defaults to 'content'."},
                "glob": {"type": "string", "description": "Optional filename glob to restrict which files are scanned in content mode, e.g. '*.py'."},
            },
            "required": ["query"],
        },
        fn=search_files,
    ),
]

_TOOLS_BY_NAME: dict[str, ToolDef] = {t.name: t for t in TOOLS}


def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    """Run a tool by name with the given arguments, returning its result as
    a string (always — this is what gets fed back to the model as the tool
    result message). Raises ToolError on failure; callers should catch it
    and feed .message back to the model as an error result rather than
    aborting the whole turn, so the model can see what went wrong and
    adjust — same as how a real coding agent would surface a failed edit.
    """
    tool = _TOOLS_BY_NAME.get(name)
    if tool is None:
        raise ToolError("TOOL-CFG-001", f"unknown tool {name!r}. Available: {', '.join(_TOOLS_BY_NAME)}")
    try:
        return tool.fn(**arguments)
    except ToolError:
        raise
    except TypeError as exc:
        raise ToolError("TOOL-CFG-002", f"bad arguments for {name}: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ToolError("TOOL-EXEC-001", f"{name} failed: {exc}") from exc


def anthropic_tools_schema() -> list[dict[str, Any]]:
    return [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in TOOLS]


def openai_tools_schema() -> list[dict[str, Any]]:
    return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}} for t in TOOLS]
