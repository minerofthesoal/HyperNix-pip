"""Environment diagnostic for the hypernix package."""
from __future__ import annotations

import importlib
import platform
import shutil
import sys
from pathlib import Path

from .fetcher import cache_dir, cached_binary
from .quantize import _detect_distro_id, _find_llama_quantize  # noqa: PLC2701


def _check_python() -> tuple[bool, str]:
    v = sys.version_info
    ok = (v.major == 3) and (10 <= v.minor <= 13)
    recommended = "3.12 recommended" if v.minor != 12 else "ok"
    return ok, f"python {v.major}.{v.minor}.{v.micro} ({recommended})"


def _check_os() -> tuple[bool, str]:
    uname = platform.uname()
    ok = uname.system == "Linux"
    distro = _detect_distro_id() or "unknown"
    return ok, f"{uname.system} {uname.release} ({uname.machine}) distro={distro}"


def _check_import(mod: str, minver: str | None = None) -> tuple[bool, str]:
    try:
        m = importlib.import_module(mod)
    except Exception as exc:
        return False, f"{mod} import failed: {exc}"
    ver = getattr(m, "__version__", "?")
    return True, f"{mod} {ver}"


def _check_torch_version() -> tuple[bool, str]:
    try:
        import torch
    except Exception as exc:
        return False, f"torch import failed: {exc}"
    # Accept 2.7.x (any patch / local tag like +cpu / +cu121).
    ok = torch.__version__.split("+", 1)[0].startswith("2.7.")
    return ok, f"torch {torch.__version__} ({'ok' if ok else 'expected 2.7.x'})"


def _check_llama_quantize() -> tuple[bool, str]:
    try:
        # Don't trigger an auto-fetch inside `doctor`; just report what's
        # already resolvable.
        path = _find_llama_quantize(auto_fetch=False)
        return True, f"llama-quantize: {path}"
    except Exception as exc:
        return False, f"llama-quantize: not found\n    {exc}"


def _check_fetch_cache() -> tuple[bool, str]:
    cached = cached_binary()
    cdir = cache_dir()
    if cached is not None:
        return True, f"cache: {cached}"
    return True, f"cache: (empty) -> {cdir}"


def _check_tool(name: str) -> tuple[bool, str]:
    path = shutil.which(name)
    return (bool(path), f"{name}: {path or 'missing (optional)'}")


def run() -> int:
    checks: list[tuple[str, tuple[bool, str]]] = [
        ("OS", _check_os()),
        ("Python", _check_python()),
        ("torch", _check_torch_version()),
        ("gguf", _check_import("gguf")),
        ("huggingface_hub", _check_import("huggingface_hub")),
        ("safetensors", _check_import("safetensors")),
        ("sentencepiece", _check_import("sentencepiece")),
        ("llama-quantize", _check_llama_quantize()),
        ("auto-fetch cache", _check_fetch_cache()),
        ("nice (optional)", _check_tool("nice")),
        ("ionice (optional)", _check_tool("ionice")),
    ]

    mandatory = {"OS", "Python", "torch", "gguf", "huggingface_hub", "safetensors", "llama-quantize"}
    all_ok = True
    for label, (ok, msg) in checks:
        icon = "[ok]" if ok else ("[--]" if label not in mandatory else "[!!]")
        print(f"  {icon} {label:<24} {msg}")
        if not ok and label in mandatory:
            all_ok = False

    print()
    print(f"hypernix executable: {shutil.which('hypernix') or 'not on PATH'}")
    print(f"working dir: {Path.cwd()}")
    return 0 if all_ok else 1
