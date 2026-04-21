"""Environment diagnostic for the hypernix package."""
from __future__ import annotations

import importlib
import platform
import shutil
import sys
from pathlib import Path

from . import deps
from .fetcher import cache_dir, cached_binary
from .quantize import _detect_distro_id, _find_llama_quantize  # noqa: PLC2701

# Packages hypernix expects at runtime, grouped by whether doctor --fix
# is allowed to install them. ``torch`` is intentionally absent — see
# deps.PROTECTED.
_RUNTIME_DEPS: tuple[str, ...] = (
    "numpy>=1.26,<3",
    "safetensors>=0.4.3",
    "huggingface-hub>=0.24",
    "gguf>=0.10.0",
    "tqdm>=4.66",
    "sentencepiece>=0.2.1",
)
# Optional — needed for HF tokenizer / training.
_OPTIONAL_DEPS: tuple[str, ...] = (
    "tokenizers>=0.20",
    "transformers>=4.44",
)


def _check_python() -> tuple[bool, str]:
    v = sys.version_info
    ok = (v.major == 3) and (10 <= v.minor <= 13)
    # 3.10–3.13 are all supported; 3.12 is the main CI target but there's
    # no quality difference for users.
    return ok, f"python {v.major}.{v.minor}.{v.micro} ({'ok' if ok else 'expected 3.10–3.13'})"


def _check_os() -> tuple[bool, str]:
    """OS check is informational — hypernix runs on Linux, macOS, and Windows."""
    uname = platform.uname()
    supported = {"Linux", "Darwin", "Windows"}
    ok = uname.system in supported
    extra = ""
    if uname.system == "Linux":
        distro = _detect_distro_id() or "unknown"
        extra = f" distro={distro}"
    return ok, f"{uname.system} {uname.release} ({uname.machine}){extra}"


def _check_import(mod: str, minver: str | None = None) -> tuple[bool, str]:
    try:
        m = importlib.import_module(mod)
    except Exception as exc:
        return False, f"{mod} import failed: {exc}"
    ver = getattr(m, "__version__", None)
    if ver is None:
        # Some libs (gguf) don't expose __version__; fall back to dist metadata.
        try:
            from importlib.metadata import PackageNotFoundError, version
            ver = version(mod)
        except (PackageNotFoundError, Exception):  # noqa: BLE001
            ver = "?"
    return True, f"{mod} {ver}"


def _check_torch_version() -> tuple[bool, str]:
    try:
        import torch
    except Exception as exc:
        return False, f"torch import failed: {exc}"
    # Accept any 2.7+ minor/patch (CPU, CUDA 11.8, CUDA 12.x, ROCm — local
    # tag is whatever follows ``+``). Reject 2.6 and earlier, which don't
    # ship ``nn.RMSNorm``.
    base = torch.__version__.split("+", 1)[0]
    parts = base.split(".")
    try:
        major, minor = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return False, f"torch {torch.__version__} (unparseable version)"
    ok = (major, minor) >= (2, 7) and major < 3
    cuda = getattr(torch.version, "cuda", None)
    tag = f"cuda={cuda}" if cuda else "cpu"
    return ok, f"torch {torch.__version__} ({tag}) ({'ok' if ok else 'expected >=2.7,<3'})"


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


def run(*, fix: bool = False) -> int:
    """Run the environment check. If ``fix`` is True, pip-install missing deps.

    ``fix`` will NOT install or reinstall torch (see ``deps.PROTECTED``) —
    users pick their CUDA / CPU flavour manually.
    """
    if fix:
        print("[hypernix] doctor --fix: installing / upgrading runtime deps")
        deps.ensure(list(_RUNTIME_DEPS), upgrade=True)
        deps.ensure(list(_OPTIONAL_DEPS), upgrade=True)
        # Optional platform-specific extras.
        if sys.platform != "win32":  # nice/ionice are POSIX-only utilities
            pass

    # Optional tool checks vary by OS — nice/ionice are POSIX-only.
    optional_tools: list[tuple[str, tuple[bool, str]]] = []
    if sys.platform != "win32":
        optional_tools = [
            ("nice (optional)", _check_tool("nice")),
            ("ionice (optional)", _check_tool("ionice")),
        ]

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
        *optional_tools,
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
    if not all_ok and not fix:
        print()
        print("tip: run `hypernix doctor --fix` to pip-install missing runtime deps")
        print("     (torch is never auto-installed; pick your own CUDA/CPU flavour)")
    return 0 if all_ok else 1
