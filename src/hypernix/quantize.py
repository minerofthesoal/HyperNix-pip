"""Run ``llama-quantize`` to produce k-quant GGUFs."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

from . import fetcher

# Distro-specific install hints surfaced when llama-quantize is missing.
# Detected by reading ``ID`` / ``ID_LIKE`` from /etc/os-release.
_DISTRO_HINTS: dict[str, str] = {
    "arch":        "sudo pacman -S llama.cpp     # Arch / Manjaro / EndeavourOS",
    "ubuntu":      "pip install 'hypernix[llama-cpp]'     # Ubuntu / Debian / Mint / Pop!_OS",
    "debian":      "pip install 'hypernix[llama-cpp]'     # Debian",
    "fedora":      "sudo dnf install llama-cpp   # Fedora / RHEL / Alma / Rocky",
    "rhel":        "sudo dnf install llama-cpp   # RHEL / Alma / Rocky",
    "opensuse":    "sudo zypper install llama.cpp   # openSUSE (or `pip install 'hypernix[llama-cpp]'`)",
    "suse":        "sudo zypper install llama.cpp   # SUSE",
    "alpine":      "apk add llama-cpp            # Alpine (edge/community)",
    "nixos":       "nix-shell -p llama-cpp",
    "gentoo":      "sudo emerge sci-libs/llama-cpp",
}


def _detect_distro_id() -> str | None:
    try:
        with open("/etc/os-release", encoding="utf-8") as fh:
            data = dict(
                line.strip().split("=", 1)
                for line in fh
                if "=" in line and not line.startswith("#")
            )
    except OSError:
        return None
    for key in ("ID", "ID_LIKE"):
        raw = data.get(key, "").strip('"').strip("'")
        for token in raw.split():
            if token in _DISTRO_HINTS:
                return token
    return None


def _install_hint() -> str:
    generic = (
        "Install options (pick one):\n"
        "  pip install 'hypernix[llama-cpp]'           # works on most distros\n"
        "  # or build llama.cpp from source and put the binary on $PATH\n"
        "  # or pass --llama-quantize /path/to/llama-quantize"
    )
    distro = _detect_distro_id()
    if distro and distro in _DISTRO_HINTS:
        return f"{_DISTRO_HINTS[distro]}\nFallback:\n{generic}"
    return generic

# Canonical friendly name -> llama-quantize enum string.
QUANT_TYPES: dict[str, str] = {
    "fp32": "F32",
    "f32": "F32",
    "fp16": "F16",
    "f16": "F16",
    "q8": "Q8_0",
    "q8_0": "Q8_0",
    "q6": "Q6_K",
    "q6_k": "Q6_K",
    "q4km": "Q4_K_M",
    "q4_k_m": "Q4_K_M",
    "q5km": "Q5_K_M",
    "q5_k_m": "Q5_K_M",
}


class QuantizerNotFoundError(RuntimeError):
    pass


def _candidate_binary_names() -> list[str]:
    # llama.cpp renamed `quantize` -> `llama-quantize` in mid-2024; keep both
    # for compatibility with older distro packages. Some Arch/Fedora builds
    # also suffix architecture (e.g. `llama-quantize-x86_64`).
    arch = platform.machine()
    return [
        "llama-quantize",
        "llama-cpp-quantize",
        "quantize",
        f"llama-quantize-{arch}",
    ]


def _system_search_paths() -> list[Path]:
    home = Path.home()
    paths = [
        fetcher.cache_dir(),              # Binaries auto-fetched from GitHub releases.
        Path("/usr/local/bin"),
        Path("/usr/bin"),
        Path("/usr/lib/llama.cpp"),       # Arch puts the binary here sometimes
        Path("/usr/lib/llama-cpp"),
        Path("/opt/llama.cpp"),
        Path("/opt/llama.cpp/build/bin"),
        home / ".local" / "bin",
        home / "llama.cpp" / "build" / "bin",
        home / "llama.cpp" / "bin",
        home / "src" / "llama.cpp" / "build" / "bin",
    ]
    # Respect GGUF_QUANTIZE_PATH to let users add arbitrary search roots.
    extra = os.environ.get("GGUF_QUANTIZE_PATH", "")
    for entry in extra.split(os.pathsep):
        if entry:
            paths.append(Path(entry))
    return paths


def _iter_candidates(explicit: str | None) -> Iterable[str]:
    if explicit:
        yield explicit
    env = os.environ.get("LLAMA_QUANTIZE")
    if env:
        yield env
    for name in _candidate_binary_names():
        found = shutil.which(name)
        if found:
            yield found
    for root in _system_search_paths():
        if not root.exists():
            continue
        for name in _candidate_binary_names():
            maybe = root / name
            if maybe.exists():
                yield str(maybe)
    # llama-cpp-python ships its own prebuilt binary.
    try:
        import llama_cpp  # type: ignore

        pkg_root = Path(llama_cpp.__file__).parent
        for rel in (
            "llama-quantize", "quantize",
            "bin/llama-quantize", "bin/quantize",
            "lib/llama-quantize", "lib/quantize",
        ):
            maybe = pkg_root / rel
            if maybe.exists():
                yield str(maybe)
    except Exception:
        pass


def _find_llama_quantize(
    explicit: str | None = None,
    *,
    auto_fetch: bool = True,
    quiet: bool = False,
) -> str:
    """Locate the llama-quantize binary across common Linux layouts.

    Search order (first match wins):
      1. ``--llama-quantize`` argument (``explicit``).
      2. ``$LLAMA_QUANTIZE`` env var.
      3. ``llama-quantize`` / ``quantize`` on ``$PATH``.
      4. Distro paths (Arch, Debian/Ubuntu, Fedora, openSUSE, Alpine, NixOS).
      5. User-local builds in ``~/.local/bin`` and ``~/llama.cpp/build/bin``.
      6. ``$GGUF_QUANTIZE_PATH`` (colon-separated extra directories).
      7. The binary bundled by ``llama-cpp-python``.
      8. ``~/.cache/hypernix/bin`` populated by :func:`fetcher.fetch_llama_quantize`.

    When ``auto_fetch`` is true (default) and nothing is found locally, the
    resolver downloads a prebuilt CPU binary from the upstream
    ``ggml-org/llama.cpp`` GitHub release and caches it before returning.
    """
    for c in _iter_candidates(explicit):
        if c and Path(c).exists() and os.access(c, os.X_OK):
            return c

    if auto_fetch and not explicit and not os.environ.get("LLAMA_QUANTIZE"):
        try:
            fetched = fetcher.fetch_llama_quantize(quiet=quiet)
        except Exception as exc:  # noqa: BLE001
            raise QuantizerNotFoundError(
                "Could not locate a llama-quantize binary and the auto-fetch "
                f"fallback failed: {exc}\n" + _install_hint()
            ) from exc
        if fetched.exists() and os.access(fetched, os.X_OK):
            return str(fetched)

    raise QuantizerNotFoundError(
        "Could not locate a llama-quantize binary.\n" + _install_hint()
    )


def quantize_gguf(
    source_gguf: Path | str,
    output_gguf: Path | str,
    quant_type: str,
    threads: int | None = None,
    llama_quantize_bin: str | None = None,
    extra_args: list[str] | None = None,
    auto_fetch: bool = True,
) -> Path:
    """Run llama-quantize to produce ``output_gguf`` from ``source_gguf``.

    ``source_gguf`` should be an fp32 or fp16 GGUF produced by
    :func:`hypernix.convert.convert_to_gguf`. If ``auto_fetch`` is true
    (default) and no binary is found locally, a CPU-only prebuilt
    ``llama-quantize`` is downloaded from the upstream ``ggml-org/llama.cpp``
    GitHub release and cached under ``~/.cache/hypernix/bin``.
    """
    source = Path(source_gguf)
    output = Path(output_gguf)
    output.parent.mkdir(parents=True, exist_ok=True)

    key = quant_type.lower().replace("-", "_")
    target = QUANT_TYPES.get(key)
    if target is None:
        raise ValueError(
            f"Unknown quant type {quant_type!r}. Valid: {sorted(set(QUANT_TYPES))}"
        )

    binary = _find_llama_quantize(llama_quantize_bin, auto_fetch=auto_fetch)
    cmd: list[str] = [binary]
    if threads and threads > 0:
        cmd += ["--threads", str(threads)]
    if extra_args:
        cmd += list(extra_args)
    cmd += [str(source), str(output), target]

    print(f"[hypernix] running: {' '.join(cmd)}", file=sys.stderr)
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"llama-quantize exited with status {proc.returncode} (target {target})."
        )
    return output
