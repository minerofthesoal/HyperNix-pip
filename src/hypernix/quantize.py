"""Run ``llama-quantize`` to produce k-quant GGUFs."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import fetcher

_HYPERNIX_VERSION = "0.70.5a1"

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
        "  pip install 'hypernix[llama-cpp]'           # works on most platforms\n"
        "  # or build llama.cpp from source and put the binary on $PATH\n"
        "  # or pass --llama-quantize /path/to/llama-quantize"
    )
    if sys.platform == "win32":
        win = (
            "Windows install options (pick one):\n"
            "  pip install 'hypernix[llama-cpp]'           # easiest\n"
            "  scoop install llama.cpp                     # if you use Scoop\n"
            "  choco install llama.cpp                     # if you use Chocolatey\n"
            "  # or download the win-x64 zip from https://github.com/ggml-org/llama.cpp/releases"
        )
        return f"{win}\nFallback:\n{generic}"
    if sys.platform == "darwin":
        mac = (
            "macOS install options (pick one):\n"
            "  brew install llama.cpp                      # Homebrew\n"
            "  pip install 'hypernix[llama-cpp]'"
        )
        return f"{mac}\nFallback:\n{generic}"
    distro = _detect_distro_id()
    if distro and distro in _DISTRO_HINTS:
        return f"{_DISTRO_HINTS[distro]}\nFallback:\n{generic}"
    return generic

# Canonical friendly name -> llama-quantize enum string.  v0.51.3
# expanded the catalog from the original 6 types (F32 / F16 / Q8_0 /
# Q6_K / Q4_K_M / Q5_K_M) to cover every type llama.cpp's
# ``llama-quantize`` driver currently accepts.  See :data:`CATALOG`
# for richer per-type metadata (bits-per-weight, category, notes).
QUANT_TYPES: dict[str, str] = {
    # ---- floats ----
    "fp32": "F32", "f32": "F32",
    "fp16": "F16", "f16": "F16",
    "bf16": "BF16",
    # ---- legacy quants (round-to-nearest) ----
    "q4_0": "Q4_0", "q4-0": "Q4_0",
    "q4_1": "Q4_1", "q4-1": "Q4_1",
    "q5_0": "Q5_0", "q5-0": "Q5_0",
    "q5_1": "Q5_1", "q5-1": "Q5_1",
    "q8":   "Q8_0", "q8_0": "Q8_0", "q8-0": "Q8_0",
    # ---- k-quants ----
    "q2_k":   "Q2_K",   "q2km":  "Q2_K",
    "q2_k_s": "Q2_K_S", "q2ks":  "Q2_K_S",
    "q3_k_s": "Q3_K_S", "q3ks":  "Q3_K_S",
    "q3_k_m": "Q3_K_M", "q3km":  "Q3_K_M",
    "q3_k_l": "Q3_K_L", "q3kl":  "Q3_K_L",
    "q4_k_s": "Q4_K_S", "q4ks":  "Q4_K_S",
    "q4_k_m": "Q4_K_M", "q4km":  "Q4_K_M",
    "q5_k_s": "Q5_K_S", "q5ks":  "Q5_K_S",
    "q5_k_m": "Q5_K_M", "q5km":  "Q5_K_M",
    "q6":     "Q6_K",   "q6_k":  "Q6_K",   "q6km":  "Q6_K",
    # ---- IQ-quants (importance-matrix friendly, newer in llama.cpp) ----
    "iq1_s":   "IQ1_S",
    "iq1_m":   "IQ1_M",
    "iq2_xxs": "IQ2_XXS",
    "iq2_xs":  "IQ2_XS",
    "iq2_s":   "IQ2_S",
    "iq2_m":   "IQ2_M",
    "iq3_xxs": "IQ3_XXS",
    "iq3_xs":  "IQ3_XS",
    "iq3_s":   "IQ3_S",
    "iq3_m":   "IQ3_M",
    "iq4_nl":  "IQ4_NL",
    "iq4_xs":  "IQ4_XS",
}


class QuantizerNotFoundError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Quant catalog (v0.51.3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QuantSpec:
    """Metadata for one llama-quantize target type.

    Attributes:
        name:          The canonical llama.cpp enum string (e.g. ``"Q4_K_M"``).
        bits_per_weight: Approximate bits per weight, including k/iq overhead.
        category:      One of ``"float" / "legacy" / "k" / "iq"``.
        size_factor:   Resulting GGUF size relative to fp16 (≈ bpw / 16).
        notes:         Short human-readable summary.
        recommended:   ``True`` if this is on the short-list of "use this"
                       types we surface in :func:`recommended`.
    """

    name: str
    bits_per_weight: float
    category: str
    notes: str
    recommended: bool = False

    @property
    def size_factor(self) -> float:
        return self.bits_per_weight / 16.0


#: Canonical metadata for every llama-quantize target.  Keys are the
#: llama.cpp enum strings (the values in :data:`QUANT_TYPES`).
CATALOG: dict[str, QuantSpec] = {
    # ---- floats ----
    "F32":  QuantSpec("F32",  32.0, "float",  "fp32 — reference / lossless"),
    "F16":  QuantSpec("F16",  16.0, "float",  "fp16 — half-precision baseline", recommended=True),
    "BF16": QuantSpec("BF16", 16.0, "float",  "bfloat16 — better range than F16"),
    # ---- legacy quants ----
    "Q4_0": QuantSpec("Q4_0",  4.5, "legacy", "4-bit RTN, smallest legacy quant"),
    "Q4_1": QuantSpec("Q4_1",  5.0, "legacy", "4-bit RTN with non-zero offset"),
    "Q5_0": QuantSpec("Q5_0",  5.5, "legacy", "5-bit RTN"),
    "Q5_1": QuantSpec("Q5_1",  6.0, "legacy", "5-bit RTN with offset"),
    "Q8_0": QuantSpec("Q8_0",  8.5, "legacy", "8-bit RTN — near-lossless", recommended=True),
    # ---- k-quants ----
    "Q2_K":   QuantSpec("Q2_K",   2.625, "k", "smallest k-quant — significant quality loss"),
    "Q2_K_S": QuantSpec("Q2_K_S", 2.5,   "k", "Q2_K small variant — tightest fit"),
    "Q3_K_S": QuantSpec("Q3_K_S", 3.5,   "k", "3-bit k-quant, small"),
    "Q3_K_M": QuantSpec("Q3_K_M", 3.75,  "k", "3-bit k-quant, medium — better ppl than Q3_K_S"),
    "Q3_K_L": QuantSpec("Q3_K_L", 4.0,   "k", "3-bit k-quant, large"),
    "Q4_K_S": QuantSpec("Q4_K_S", 4.5,   "k", "4-bit k-quant, small — strong size/quality"),
    "Q4_K_M": QuantSpec("Q4_K_M", 4.83,  "k", "4-bit k-quant, medium — sweet spot for chat",
                        recommended=True),
    "Q5_K_S": QuantSpec("Q5_K_S", 5.5,   "k", "5-bit k-quant, small"),
    "Q5_K_M": QuantSpec("Q5_K_M", 5.83,  "k", "5-bit k-quant, medium — minimal quality loss",
                        recommended=True),
    "Q6_K":   QuantSpec("Q6_K",   6.56,  "k", "6-bit k-quant — very close to fp16",
                        recommended=True),
    # ---- IQ-quants (newer, importance-matrix friendly) ----
    "IQ1_S":   QuantSpec("IQ1_S",   1.5625, "iq", "1.5-bit IQ — extreme size reduction"),
    "IQ1_M":   QuantSpec("IQ1_M",   1.75,   "iq", "1.75-bit IQ"),
    "IQ2_XXS": QuantSpec("IQ2_XXS", 2.0625, "iq", "2-bit IQ XXS — needs imatrix"),
    "IQ2_XS":  QuantSpec("IQ2_XS",  2.3125, "iq", "2-bit IQ XS — needs imatrix"),
    "IQ2_S":   QuantSpec("IQ2_S",   2.5,    "iq", "2-bit IQ S — better than Q2_K at the same size"),
    "IQ2_M":   QuantSpec("IQ2_M",   2.7,    "iq", "2-bit IQ M"),
    "IQ3_XXS": QuantSpec("IQ3_XXS", 3.06,   "iq", "3-bit IQ XXS"),
    "IQ3_XS":  QuantSpec("IQ3_XS",  3.3,    "iq", "3-bit IQ XS"),
    "IQ3_S":   QuantSpec("IQ3_S",   3.44,   "iq", "3-bit IQ S — beats Q3_K_M at similar size"),
    "IQ3_M":   QuantSpec("IQ3_M",   3.66,   "iq", "3-bit IQ M"),
    "IQ4_NL":  QuantSpec("IQ4_NL",  4.5,    "iq", "4-bit IQ non-linear"),
    "IQ4_XS":  QuantSpec("IQ4_XS",  4.25,   "iq", "4-bit IQ XS — recommended sub-Q4_K_M tier"),
}


def resolve_spec(quant_type: str) -> QuantSpec:
    """Look up a :class:`QuantSpec` from any accepted alias.

    Accepts the canonical enum (``"Q4_K_M"``), short forms
    (``"q4km"``), and case-insensitive variants (``"q4_K_m"``).
    Raises ``ValueError`` for unknown aliases.
    """
    key = quant_type.lower().replace("-", "_")
    target = QUANT_TYPES.get(key) or QUANT_TYPES.get(key.upper().lower())
    if target is None and quant_type.upper() in CATALOG:
        target = quant_type.upper()
    if target is None:
        raise ValueError(
            f"Unknown quant type {quant_type!r}. Valid: {sorted(set(QUANT_TYPES))}",
        )
    return CATALOG[target]


def recommended() -> list[QuantSpec]:
    """Return the curated short-list (``F16``, ``Q8_0``, ``Q6_K``,
    ``Q5_K_M``, ``Q4_K_M``) — the types most users actually want."""
    return [s for s in CATALOG.values() if s.recommended]


def by_category(category: str) -> list[QuantSpec]:
    """Return every spec in a category (``"float" / "legacy" / "k" / "iq"``),
    sorted by bits-per-weight ascending."""
    cat = category.lower()
    out = [s for s in CATALOG.values() if s.category == cat]
    return sorted(out, key=lambda s: s.bits_per_weight)


def for_size(target_size_bytes: int, fp16_size_bytes: int) -> QuantSpec:
    """Pick the largest quant spec that fits inside ``target_size_bytes``,
    given the model's fp16 GGUF size.  Falls back to the smallest IQ
    type if even that doesn't fit.
    """
    if fp16_size_bytes <= 0:
        raise ValueError("fp16_size_bytes must be > 0")
    candidates = sorted(
        (s for s in CATALOG.values() if s.category != "float"),
        key=lambda s: s.bits_per_weight, reverse=True,
    )
    for spec in candidates:
        if spec.size_factor * fp16_size_bytes <= target_size_bytes:
            return spec
    # Nothing fit — return the smallest available.
    return min(CATALOG.values(), key=lambda s: s.bits_per_weight)


def estimate_size(quant_type: str, fp16_size_bytes: int) -> int:
    """Estimate the resulting GGUF size for ``quant_type`` given the
    fp16 reference size.  Pure arithmetic; doesn't run llama-quantize."""
    spec = resolve_spec(quant_type)
    return int(round(spec.size_factor * fp16_size_bytes))


def list_types() -> list[str]:
    """Sorted list of every canonical type name in :data:`CATALOG`."""
    return sorted(CATALOG.keys())


def _candidate_binary_names() -> list[str]:
    # llama.cpp renamed `quantize` -> `llama-quantize` in mid-2024; keep both
    # for compatibility with older distro packages. Some Arch/Fedora builds
    # also suffix architecture (e.g. `llama-quantize-x86_64`).
    arch = platform.machine()
    base = [
        "llama-quantize",
        "llama-cpp-quantize",
        "quantize",
        f"llama-quantize-{arch}",
    ]
    if sys.platform == "win32":
        # shutil.which respects PATHEXT, but direct ``root / name`` lookups
        # don't — list ``.exe`` variants explicitly so the manual search
        # finds binaries on Windows too.
        return [*base, *(f"{n}.exe" for n in base)]
    return base


def _system_search_paths() -> list[Path]:
    """Directories to probe for ``llama-quantize``. OS-aware."""
    home = Path.home()
    paths: list[Path] = [
        fetcher.cache_dir(),              # Binaries auto-fetched from GitHub releases.
    ]

    if sys.platform == "win32":
        # Typical Windows install roots. %USERPROFILE% layouts only —
        # %ProgramFiles% needs admin to write to, so manual installers
        # tend to land in user-scoped dirs.
        localappdata = os.environ.get("LOCALAPPDATA")
        programfiles = os.environ.get("ProgramFiles")
        programfiles_x86 = os.environ.get("ProgramFiles(x86)")
        for root in (localappdata, programfiles, programfiles_x86):
            if not root:
                continue
            r = Path(root)
            paths += [
                r / "llama.cpp",
                r / "llama.cpp" / "bin",
                r / "Programs" / "llama.cpp",
                r / "Programs" / "llama.cpp" / "bin",
            ]
        # Scoop and Chocolatey shims pick this up via shutil.which + PATH,
        # but list the default shim dirs anyway for non-PATH installs.
        paths += [
            home / "scoop" / "apps" / "llama.cpp" / "current",
            home / "scoop" / "shims",
            Path("C:/ProgramData/chocolatey/bin"),
            home / "llama.cpp" / "build" / "bin" / "Release",
            home / "llama.cpp" / "bin",
        ]
    else:
        paths += [
            Path("/usr/local/bin"),
            Path("/usr/bin"),
            Path("/usr/lib/llama.cpp"),       # Arch puts the binary here sometimes
            Path("/usr/lib/llama-cpp"),
            Path("/opt/llama.cpp"),
            Path("/opt/llama.cpp/build/bin"),
            Path("/opt/homebrew/bin"),        # macOS arm64 homebrew
            Path("/usr/local/Cellar"),        # macOS x86_64 homebrew (scanned shallowly)
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
        rels = [
            "llama-quantize", "quantize",
            "bin/llama-quantize", "bin/quantize",
            "lib/llama-quantize", "lib/quantize",
        ]
        if sys.platform == "win32":
            rels = [*rels, *(f"{r}.exe" for r in rels)]
        for rel in rels:
            maybe = pkg_root / rel
            if maybe.exists():
                yield str(maybe)
    except Exception:
        pass


def _pip_install_llama_cpp_python(quiet: bool = False) -> None:
    """Best-effort ``pip install llama-cpp-python`` used by --auto.

    Tries ``--user`` first (works inside PEP 668 externally-managed envs like
    Arch's system Python), then falls back to a plain install. Failures are
    swallowed — the caller rechecks the candidate list afterwards.
    """
    base = [sys.executable, "-m", "pip", "install"]
    if quiet:
        base.append("--quiet")
    base.append("llama-cpp-python")

    print("[hypernix] --auto: trying `pip install --user llama-cpp-python`", file=sys.stderr)
    for extra in (["--user"], []):
        cmd = [*base[:-1], *extra, base[-1]]
        try:
            proc = subprocess.run(cmd, check=False)
            if proc.returncode == 0:
                return
        except Exception as exc:  # noqa: BLE001
            print(f"[hypernix] pip install attempt failed: {exc}", file=sys.stderr)


def _find_llama_quantize(
    explicit: str | None = None,
    *,
    auto_fetch: bool = True,
    auto: bool = False,
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
    ``ggml-org/llama.cpp`` GitHub release (walking back through recent
    releases if the latest tag has no matching asset) and caches it.

    When ``auto`` is also true, a further fallback of
    ``pip install llama-cpp-python`` is attempted — handy on distros where
    upstream's release assets skip the current arch.
    """
    for c in _iter_candidates(explicit):
        if c and Path(c).exists() and os.access(c, os.X_OK):
            return c

    gh_error: Exception | None = None
    if auto_fetch and not explicit and not os.environ.get("LLAMA_QUANTIZE"):
        try:
            fetched = fetcher.fetch_llama_quantize(quiet=quiet)
            if fetched.exists() and os.access(fetched, os.X_OK):
                return str(fetched)
        except Exception as exc:  # noqa: BLE001
            gh_error = exc
            if not auto:
                raise QuantizerNotFoundError(
                    "Could not locate a llama-quantize binary and the auto-fetch "
                    f"fallback failed: {exc}\n" + _install_hint()
                ) from exc

    if auto:
        _pip_install_llama_cpp_python(quiet=quiet)
        for c in _iter_candidates(explicit):
            if c and Path(c).exists() and os.access(c, os.X_OK):
                print(f"[hypernix] --auto: resolved via PyPI -> {c}", file=sys.stderr)
                return c
        suffix = f" (GitHub fetch error: {gh_error})" if gh_error else ""
        raise QuantizerNotFoundError(
            "--auto could not resolve llama-quantize via $PATH, the llama.cpp "
            f"GitHub releases, or `pip install llama-cpp-python`.{suffix}\n"
            + _install_hint()
        )

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
    auto: bool = False,
) -> Path:
    """Run llama-quantize to produce ``output_gguf`` from ``source_gguf``.

    ``source_gguf`` should be an fp32 or fp16 GGUF produced by
    :func:`hypernix.convert.convert_to_gguf`. If ``auto_fetch`` is true
    (default) and no binary is found locally, a CPU-only prebuilt
    ``llama-quantize`` is downloaded from the upstream ``ggml-org/llama.cpp``
    GitHub release and cached under ``~/.cache/hypernix/bin``.

    When ``auto`` is true, a final PyPI fallback
    (``pip install llama-cpp-python``) is attempted if the GitHub release
    fetch fails.
    """
    source = Path(source_gguf)
    output = Path(output_gguf)
    output.parent.mkdir(parents=True, exist_ok=True)

    target = resolve_spec(quant_type).name

    # Try native llama_cpp python binding first if available
    try:
        from llama_cpp import llama_model_quantize, llama_model_quantize_params
        
        print(f"[hypernix] using native llama_cpp python binding to quantize {target}", file=sys.stderr)
        params = llama_model_quantize_params()
        # Find enum value for target
        ftype_map = {
            "Q4_0": 2, "Q4_1": 3, "Q5_0": 8, "Q5_1": 9, "Q8_0": 7,
            "Q2_K": 10, "Q3_K_S": 11, "Q3_K_M": 12, "Q3_K_L": 13,
            "Q4_K_S": 14, "Q4_K_M": 15, "Q5_K_S": 16, "Q5_K_M": 17,
            "Q6_K": 18, "IQ2_XXS": 19, "IQ2_XS": 20, "IQ3_XXS": 21,
            "IQ1_S": 24, "IQ4_NL": 25, "IQ3_S": 26, "IQ2_S": 27,
            "IQ4_XS": 28, "IQ2_M": 29, "IQ3_M": 30, "IQ1_M": 31
        }
        if target in ftype_map:
            params.ftype = ftype_map[target]
            if threads and threads > 0:
                params.nthread = threads
            
            # encode strings to bytes
            src_bytes = str(source).encode('utf-8')
            out_bytes = str(output).encode('utf-8')
            
            # The python binding returns 0 on success
            ret = llama_model_quantize(src_bytes, out_bytes, params)
            if ret == 0:
                return output
            else:
                print(f"[hypernix] native quantization failed with code {ret}, falling back to binary", file=sys.stderr)
    except ImportError:
        pass
    except Exception as e:
        print(f"[hypernix] native quantization error: {e}, falling back to binary", file=sys.stderr)

    binary = _find_llama_quantize(llama_quantize_bin, auto_fetch=auto_fetch, auto=auto)
    cmd: list[str] = [binary]
    if threads and threads > 0:
        cmd += ["--threads", str(threads)]
    if extra_args:
        cmd += list(extra_args)
    cmd += [str(source), str(output), target]

    print(f"[hypernix] running: {' '.join(cmd)}", file=sys.stderr)
    try:
        proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"llama-quantize exited with status {proc.returncode} (target {target}).\n"
                f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
            )
    except FileNotFoundError as err:
        raise RuntimeError(f"Binary {binary} not found or not executable.") from err
    
    return output


# ---------------------------------------------------------------------------
# HyperNix quantize facade (v0.70.3b2)
# ---------------------------------------------------------------------------

_USE_CASE_PROFILES: dict[str, tuple[str, ...]] = {
    "chat": ("q4_k_m", "q5_k_m", "q6_k"),
    "code": ("q5_k_m", "q6_k", "q8_0"),
    "edge": ("q4_k_m", "iq4_xs", "q3_k_m"),
    "quality": ("q6_k", "q8_0", "f16"),
    "reference": ("f16", "f32"),
}


@dataclass
class QuantJob:
    """One quantize target in a batch run."""

    alias: str
    output: Path
    spec: QuantSpec


class HyperNixQuantizer:
    """High-level GGUF quantizer with profiles, batch runs, and size planning."""

    def __init__(
        self,
        *,
        llama_quantize_bin: str | None = None,
        threads: int | None = None,
        auto_fetch: bool = True,
        auto: bool = False,
    ) -> None:
        self.llama_quantize_bin = llama_quantize_bin
        self.threads = threads
        self.auto_fetch = auto_fetch
        self.auto = auto

    def recommend(self, use_case: str = "chat") -> list[QuantSpec]:
        """Return recommended specs for a use case (``chat``, ``code``, ``edge``, …)."""
        key = use_case.lower().replace("-", "_")
        aliases = _USE_CASE_PROFILES.get(key)
        if aliases is None:
            raise ValueError(
                f"unknown use_case {use_case!r}; choose from {sorted(_USE_CASE_PROFILES)}"
            )
        return [resolve_spec(a) for a in aliases]

    def plan_batch(
        self,
        source_gguf: Path | str,
        out_dir: Path | str,
        aliases: Iterable[str],
    ) -> list[QuantJob]:
        """Build a batch of quant jobs from alias names."""
        src = Path(source_gguf)
        dest = Path(out_dir)
        dest.mkdir(parents=True, exist_ok=True)
        jobs: list[QuantJob] = []
        for alias in aliases:
            spec = resolve_spec(alias)
            slug = alias.lower().replace("/", "_").replace("-", "_")
            out = dest / f"{src.stem}-{slug}.gguf"
            jobs.append(QuantJob(alias=alias, output=out, spec=spec))
        return jobs

    def run_batch(
        self,
        source_gguf: Path | str,
        out_dir: Path | str,
        aliases: Iterable[str],
        *,
        extra_args: list[str] | None = None,
    ) -> list[Path]:
        """Quantize ``source_gguf`` into multiple targets under ``out_dir``."""
        jobs = self.plan_batch(source_gguf, out_dir, aliases)
        written: list[Path] = []
        for job in jobs:
            written.append(
                quantize_gguf(
                    source_gguf,
                    job.output,
                    job.alias,
                    threads=self.threads,
                    llama_quantize_bin=self.llama_quantize_bin,
                    extra_args=extra_args,
                    auto_fetch=self.auto_fetch,
                    auto=self.auto,
                )
            )
        return written

    def format_catalog(self, *, category: str | None = None) -> str:
        """Return a human-readable catalog table for CLI / webui display."""
        specs = by_category(category) if category else sorted(CATALOG.values(), key=lambda s: s.name)
        lines = [f"HyperNix quantize catalog (hypernix {_HYPERNIX_VERSION})", "-" * 56]
        for spec in specs:
            flag = "*" if spec.recommended else " "
            lines.append(
                f"{flag} {spec.name:8s}  {spec.bits_per_weight:5.2f} bpw  "
                f"[{spec.category:6s}]  {spec.notes}"
            )
        lines.append("* = recommended")
        return "\n".join(lines)


def recommend_profile(use_case: str = "chat") -> list[QuantSpec]:
    """Shortcut for :meth:`HyperNixQuantizer.recommend`."""
    return HyperNixQuantizer().recommend(use_case)


def batch_quantize(
    source_gguf: Path | str,
    out_dir: Path | str,
    aliases: Iterable[str],
    **kwargs: Any,
) -> list[Path]:
    """Shortcut for :meth:`HyperNixQuantizer.run_batch`."""
    return HyperNixQuantizer(**kwargs).run_batch(source_gguf, out_dir, aliases)
