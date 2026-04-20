"""Run ``llama-quantize`` to produce k-quant GGUFs."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

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


def _find_llama_quantize(explicit: Optional[str] = None) -> str:
    """Locate the llama-quantize binary.

    Search order:
      1. ``--llama-quantize`` arg / ``explicit`` parameter.
      2. ``LLAMA_QUANTIZE`` env var.
      3. ``llama-quantize`` or ``quantize`` on PATH.
      4. Common paths inside an installed ``llama-cpp-python`` wheel.
    """
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    env = os.environ.get("LLAMA_QUANTIZE")
    if env:
        candidates.append(env)
    for name in ("llama-quantize", "quantize"):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    try:
        import llama_cpp  # type: ignore

        pkg_root = Path(llama_cpp.__file__).parent
        for rel in ("llama-quantize", "quantize", "bin/llama-quantize", "bin/quantize"):
            maybe = pkg_root / rel
            if maybe.exists() and os.access(maybe, os.X_OK):
                candidates.append(str(maybe))
    except Exception:
        pass

    for c in candidates:
        if c and Path(c).exists() and os.access(c, os.X_OK):
            return c
    raise QuantizerNotFoundError(
        "Could not find llama-quantize. Install it via:\n"
        "  pip install 'hypernix[llama-cpp]'\n"
        "or build llama.cpp and put the binary on PATH, or pass --llama-quantize=/path/to/llama-quantize."
    )


def quantize_gguf(
    source_gguf: Path | str,
    output_gguf: Path | str,
    quant_type: str,
    threads: Optional[int] = None,
    llama_quantize_bin: Optional[str] = None,
    extra_args: Optional[list[str]] = None,
) -> Path:
    """Run llama-quantize to produce ``output_gguf`` from ``source_gguf``.

    ``source_gguf`` should be an fp32 or fp16 GGUF produced by
    :func:`hypernix.convert.convert_to_gguf`.
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

    binary = _find_llama_quantize(llama_quantize_bin)
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
