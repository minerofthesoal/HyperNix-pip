"""Environment diagnostic for the hypernix package."""
from __future__ import annotations

import importlib
import platform
import shutil
import sys
from pathlib import Path
from typing import List, Tuple

from .quantize import _detect_distro_id, _find_llama_quantize  # noqa: PLC2701


def _check_python() -> Tuple[bool, str]:
    v = sys.version_info
    ok = (v.major, v.minor) == (3, 12)
    return ok, f"python {v.major}.{v.minor}.{v.micro} ({'ok' if ok else 'needs 3.12'})"


def _check_os() -> Tuple[bool, str]:
    uname = platform.uname()
    ok = uname.system == "Linux"
    distro = _detect_distro_id() or "unknown"
    return ok, f"{uname.system} {uname.release} ({uname.machine}) distro={distro}"


def _check_import(mod: str, minver: str | None = None) -> Tuple[bool, str]:
    try:
        m = importlib.import_module(mod)
    except Exception as exc:
        return False, f"{mod} import failed: {exc}"
    ver = getattr(m, "__version__", "?")
    return True, f"{mod} {ver}"


def _check_torch_version() -> Tuple[bool, str]:
    try:
        import torch
    except Exception as exc:
        return False, f"torch import failed: {exc}"
    ok = torch.__version__.startswith("2.7.1")
    return ok, f"torch {torch.__version__} ({'ok' if ok else 'expected 2.7.1'})"


def _check_llama_quantize() -> Tuple[bool, str]:
    try:
        path = _find_llama_quantize()
        return True, f"llama-quantize: {path}"
    except Exception as exc:
        return False, f"llama-quantize: not found\n    {exc}"


def _check_tool(name: str) -> Tuple[bool, str]:
    path = shutil.which(name)
    return (bool(path), f"{name}: {path or 'missing (optional)'}")


def run() -> int:
    checks: List[Tuple[str, Tuple[bool, str]]] = [
        ("OS", _check_os()),
        ("Python", _check_python()),
        ("torch", _check_torch_version()),
        ("gguf", _check_import("gguf")),
        ("huggingface_hub", _check_import("huggingface_hub")),
        ("safetensors", _check_import("safetensors")),
        ("sentencepiece", _check_import("sentencepiece")),
        ("llama-quantize", _check_llama_quantize()),
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
