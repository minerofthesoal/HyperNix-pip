"""utils — small cross-module helpers added in v0.61.1.

* :func:`healthcheck`   — diagnostic snapshot for bug reports +
                           "is my install wired correctly?" checks.
* :func:`list_models`   — tabular print of every entry in
                           :data:`hypernix.KNOWN_MODELS`, optionally
                           filtered by substring.
* :func:`session_dir`   — ``~/.cache/hypernix/sessions/<timestamp>``
                           (auto-created), the default save path
                           used by ``hyped``.
* :func:`diagnostic_info` — structured ``dict`` form of
                             :func:`healthcheck` for programmatic
                             callers / CI.

Zero hard deps; everything degrades gracefully when an optional
backend (psutil, transformers, nvidia-smi, llama-quantize) isn't
present.
"""
from __future__ import annotations

import importlib
import os
import platform
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# diagnostic_info / healthcheck
# ---------------------------------------------------------------------------

@dataclass
class HealthReport:
    hypernix_version: str = ""
    python_version: str = ""
    platform: str = ""
    torch_version: str | None = None
    cuda_available: bool = False
    cuda_device_count: int = 0
    cuda_device_names: list[str] = field(default_factory=list)
    optional_deps: dict[str, str | None] = field(default_factory=dict)
    binaries: dict[str, str | None] = field(default_factory=dict)
    known_models_count: int = 0

    def is_ok(self) -> bool:
        """Returns True when every *required* dep is present."""
        return self.python_version != "" and self.torch_version is not None

    def summary(self) -> str:
        lines = [
            f"hypernix {self.hypernix_version} on Python {self.python_version} ({self.platform})",
            f"torch {self.torch_version or '(missing)'}  "
            f"cuda={self.cuda_available} devices={self.cuda_device_count}",
        ]
        for name in self.cuda_device_names:
            lines.append(f"  · {name}")
        present_opt = [k for k, v in self.optional_deps.items() if v]
        missing_opt = [k for k, v in self.optional_deps.items() if not v]
        if present_opt:
            lines.append(
                "optional deps present: "
                + ", ".join(f"{k}={self.optional_deps[k]}" for k in present_opt)
            )
        if missing_opt:
            lines.append("optional deps missing: " + ", ".join(missing_opt))
        present_bin = [k for k, v in self.binaries.items() if v]
        missing_bin = [k for k, v in self.binaries.items() if not v]
        if present_bin:
            lines.append("binaries on PATH: " + ", ".join(present_bin))
        if missing_bin:
            lines.append("binaries missing: " + ", ".join(missing_bin))
        lines.append(f"KNOWN_MODELS entries: {self.known_models_count}")
        return "\n".join(lines)


def diagnostic_info() -> dict[str, Any]:
    """Collect a structured diagnostic snapshot — useful for bug
    reports and CI smoke checks."""
    from . import __version__ as hypernix_version
    from .download import KNOWN_MODELS

    info: dict[str, Any] = {
        "hypernix_version": hypernix_version,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "torch_version": None,
        "cuda_available": False,
        "cuda_device_count": 0,
        "cuda_device_names": [],
        "optional_deps": {},
        "binaries": {},
        "known_models_count": len(KNOWN_MODELS),
    }

    try:
        import torch  # type: ignore
        info["torch_version"] = torch.__version__
        info["cuda_available"] = bool(torch.cuda.is_available())
        if info["cuda_available"]:
            info["cuda_device_count"] = int(torch.cuda.device_count())
            info["cuda_device_names"] = [
                torch.cuda.get_device_name(i)
                for i in range(info["cuda_device_count"])
            ]
    except Exception:  # noqa: BLE001
        pass

    for name in (
        "transformers", "accelerate", "safetensors", "huggingface_hub",
        "gguf", "tqdm", "sentencepiece", "psutil", "datasets",
        "matplotlib",
    ):
        try:
            mod = importlib.import_module(name)
            info["optional_deps"][name] = getattr(mod, "__version__", "(installed)")
        except Exception:  # noqa: BLE001
            info["optional_deps"][name] = None

    for name in ("nvidia-smi", "llama-quantize", "xset", "wlopm", "pmset"):
        path = shutil.which(name)
        info["binaries"][name] = path

    return info


def healthcheck(*, verbose: bool = False) -> HealthReport:
    """Convenience wrapper around :func:`diagnostic_info` that
    returns a :class:`HealthReport`.  Pass ``verbose=True`` to also
    print the report's summary to stdout."""
    info = diagnostic_info()
    report = HealthReport(
        hypernix_version=info["hypernix_version"],
        python_version=info["python_version"],
        platform=info["platform"],
        torch_version=info["torch_version"],
        cuda_available=info["cuda_available"],
        cuda_device_count=info["cuda_device_count"],
        cuda_device_names=info["cuda_device_names"],
        optional_deps=info["optional_deps"],
        binaries=info["binaries"],
        known_models_count=info["known_models_count"],
    )
    if verbose:
        print(report.summary())
    return report


# ---------------------------------------------------------------------------
# list_models
# ---------------------------------------------------------------------------

def list_models(
    *,
    filter_substring: str | None = None,
    arch: str | None = None,
) -> list[tuple[str, str, str]]:
    """Return ``[(short_name, repo_id, notes), ...]`` for every entry
    in :data:`hypernix.KNOWN_MODELS`, optionally filtered.

    ``filter_substring`` matches against the short name *or* the
    repo id (case-insensitive).  ``arch`` matches the registered
    architecture string exactly (e.g. ``"hypernix"`` / ``"llama"``
    / ``"qwen2"`` / ``"auto"``).
    """
    from .download import KNOWN_MODELS
    out: list[tuple[str, str, str]] = []
    needle = filter_substring.lower() if filter_substring else None
    for short, info in sorted(KNOWN_MODELS.items()):
        if needle and needle not in short.lower() and needle not in info.repo_id.lower():
            continue
        if arch is not None and info.arch != arch:
            continue
        out.append((short, info.repo_id, info.notes or ""))
    return out


def print_models(
    *,
    filter_substring: str | None = None,
    arch: str | None = None,
    file: Any = sys.stdout,
) -> None:
    """Print :func:`list_models` in a tabular layout."""
    rows = list_models(filter_substring=filter_substring, arch=arch)
    if not rows:
        print("(no models match)", file=file)
        return
    short_w = max(len(r[0]) for r in rows)
    repo_w = max(len(r[1]) for r in rows)
    header = f"{'short':<{short_w}}  {'repo':<{repo_w}}  notes"
    print(header, file=file)
    print("-" * len(header), file=file)
    for short, repo, notes in rows:
        print(f"{short:<{short_w}}  {repo:<{repo_w}}  {notes}", file=file)


# ---------------------------------------------------------------------------
# session_dir
# ---------------------------------------------------------------------------

def session_dir(*, label: str | None = None) -> Path:
    """Return ``~/.cache/hypernix/sessions/<timestamp>[--<label>]``,
    auto-creating the directory.  Used by ``hyped`` and other
    interactive tools as a default save location."""
    base = Path(os.environ.get("HYPERNIX_CACHE_DIR") or (Path.home() / ".cache" / "hypernix"))
    sessions = base / "sessions"
    stamp = time.strftime("%Y-%m-%dT%H-%M-%S")
    name = f"{stamp}--{label}" if label else stamp
    target = sessions / name
    target.mkdir(parents=True, exist_ok=True)
    return target


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def is_module_available(name: str) -> bool:
    """Best-effort check that an optional Python module is
    importable.  Doesn't actually import; uses ``importlib.util``.
    """
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:  # noqa: BLE001
        return False


def has_binary(name: str) -> bool:
    """Wrapper around :func:`shutil.which` that returns ``bool``."""
    return shutil.which(name) is not None


# ---------------------------------------------------------------------------
# v0.61.1: hyper-Nix.2 undertrained warning
# ---------------------------------------------------------------------------

#: Repos / aliases that should trigger the MAJOR undertrained warning.
HYPER_NIX_2_ALIASES: frozenset[str] = frozenset({
    "ray0rf1re/hyper-nix.2",
    "hyper-nix.2", "hypernix.2", "hyper-nix2", "hypernix2",
    # Bare ``hyper-nix`` / ``hypernix`` resolve to v2 in 0.51.x+.
    "hyper-nix", "hypernix",
})

_WARNED_REPOS: set[str] = set()


def is_hyper_nix_2(repo_or_short: str) -> bool:
    """Return ``True`` if the given short name / repo id resolves to
    the chat-tuned ``ray0rf1re/hyper-Nix.2`` checkpoint."""
    if not repo_or_short:
        return False
    key = repo_or_short.lower().strip()
    if key in HYPER_NIX_2_ALIASES:
        return True
    # Match the resolved repo id form regardless of casing.
    return key.endswith("/hyper-nix.2")


def warn_hyper_nix_2(repo_or_short: str, *, force: bool = False) -> bool:
    """Emit a MAJOR undertrained warning when the user touches
    hyper-Nix.2.  Idempotent per process unless ``force=True``.

    Returns ``True`` if a warning was emitted this call, ``False``
    otherwise.  Suppress entirely by setting
    ``HYPERNIX_SUPPRESS_HYPERNIX2_WARNING=1``.
    """
    if not is_hyper_nix_2(repo_or_short):
        return False
    if os.environ.get("HYPERNIX_SUPPRESS_HYPERNIX2_WARNING") == "1":
        return False
    key = repo_or_short.lower().strip()
    if not force and key in _WARNED_REPOS:
        return False
    _WARNED_REPOS.add(key)

    # ANSI red+bold + a clear box so the warning is impossible to miss.
    csi = "\x1b["
    red = csi + "1;31m"
    yellow = csi + "33m"
    reset = csi + "0m"
    on_tty = bool(getattr(sys.stderr, "isatty", lambda: False)())
    if on_tty:
        opener = f"{red}╔══════════════════════════════════════════════════════════════════╗{reset}"
        bar = f"{red}║{reset}"
        closer = f"{red}╚══════════════════════════════════════════════════════════════════╝{reset}"
        title = f"{red}║   ⚠   MAJOR WARNING: hyper-Nix.2 is INSANELY UNDERTRAINED   ⚠   ║{reset}"
    else:
        opener = "+==================================================================+"
        bar = "|"
        closer = "+==================================================================+"
        title = "|   !   MAJOR WARNING: hyper-Nix.2 is INSANELY UNDERTRAINED   !    |"
    body = [
        opener,
        title,
        bar + " " * 66 + bar,
        bar + "  ray0rf1re/hyper-Nix.2 has shipped publicly but its training run".ljust(67) + bar,
        bar + "  was cut SHORT — outputs are often nonsensical, repetitive, or".ljust(67) + bar,
        bar + "  incoherent.  Treat this checkpoint as a placeholder, NOT a".ljust(67) + bar,
        bar + "  production-ready chat model.".ljust(67) + bar,
        bar + " " * 66 + bar,
        bar + ("  Recommended alternatives until v2 is fully retrained:".ljust(67)) + bar,
        bar + ("    · " + yellow + "Nix-ai/Nix-2.7a" + reset + "  — solid Qwen2-shape 2B chat").ljust(67 + (len(yellow) + len(reset))) + bar,
        bar + ("    · " + yellow + "Qwen/Qwen2.5-7B-Instruct" + reset + "  — fully trained baseline").ljust(67 + (len(yellow) + len(reset))) + bar,
        bar + ("    · " + yellow + "ray0rf1re/hyper-nix.1" + reset + "  — original v1 (base, no chat tune)").ljust(67 + (len(yellow) + len(reset))) + bar,
        bar + " " * 66 + bar,
        bar + "  Suppress this warning with HYPERNIX_SUPPRESS_HYPERNIX2_WARNING=1".ljust(67) + bar,
        closer,
    ]
    print("\n".join(body), file=sys.stderr)
    return True


def reset_warnings() -> None:
    """Clear the per-process "already warned" memo so the next
    :func:`warn_hyper_nix_2` call re-emits.  Mostly for tests."""
    _WARNED_REPOS.clear()


__all__ = [
    "HYPER_NIX_2_ALIASES",
    "HealthReport",
    "diagnostic_info",
    "has_binary",
    "healthcheck",
    "is_hyper_nix_2",
    "is_module_available",
    "list_models",
    "print_models",
    "reset_warnings",
    "session_dir",
    "warn_hyper_nix_2",
]
