#!/usr/bin/env bash
# install_macos_legacy.sh — set up hypernix on an old Intel Mac that
# can't run PyTorch 2.x.
#
# Targets:
#   * macOS 10.15 Catalina / 11 Big Sur on Intel
#   * Python 3.8 / 3.9 / 3.10 (torch 1.13 does not support 3.11+)
#   * No Apple Silicon / no MPS (this is the Intel-only path)
#
# What it does:
#   1. Creates (or reuses) a virtualenv at .venv/
#   2. Pins torch==1.13.1 from the PyPI CPU wheel
#   3. Installs hypernix with the [legacy-torch] extra, which loosens
#      numpy / safetensors / huggingface-hub / tqdm / sentencepiece
#      to versions known to work alongside torch 1.13.
#   4. Runs `python -c "import hypernix; print(hypernix.torch_compat.describe())"`
#      as a smoke check.
#
# Caveats:
#   * GGUF quantization still needs `llama-quantize`; the auto-fetch
#     path downloads an x86_64 mac binary from ggml-org/llama.cpp.
#     If that's missing on your macOS version, build it from source
#     first: `brew install llama.cpp`.
#   * `torch.compile`, `torch.nn.functional.scaled_dot_product_attention`,
#     and `nn.RMSNorm` are NOT in torch 1.13 — hypernix.torch_compat
#     provides fallbacks for the latter two.  `torch.compile` is
#     disabled on legacy torch.

set -euo pipefail

PY="${PY:-python3}"
VENV=".venv"

if ! command -v "$PY" >/dev/null; then
    echo "error: $PY not found on PATH" >&2
    exit 1
fi

if [ ! -d "$VENV" ]; then
    echo "[legacy] creating venv at $VENV"
    "$PY" -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

python -m pip install --upgrade "pip<24" "wheel"

# torch 1.13.1 CPU — pinned.  Do NOT let pip resolve torch from the
# main hypernix install line; install it first and reuse.
python -m pip install \
    --index-url https://download.pytorch.org/whl/cpu \
    "torch==1.13.1"

# Core hypernix + the legacy-torch extra.  --no-deps for hypernix
# itself to avoid pip yanking torch 1.13 out from under us when it
# sees the main pin of torch>=2.7 in the wheel metadata.
python -m pip install "hypernix[legacy-torch]" --no-deps
python -m pip install \
    "numpy>=1.21,<2" \
    "safetensors>=0.3.1" \
    "huggingface-hub>=0.16" \
    "gguf>=0.10.0" \
    "tqdm>=4.64" \
    "sentencepiece>=0.1.99"

echo
echo "[legacy] smoke-testing hypernix.torch_compat:"
python - <<'PY'
import hypernix
from hypernix import torch_compat

desc = torch_compat.describe()
print(desc)
assert desc["is_legacy_torch"], "torch_compat should report legacy mode"
print("hypernix", hypernix.__version__, "on torch", desc["torch_version"])
PY

echo
echo "[legacy] done.  Activate with:  source $VENV/bin/activate"
