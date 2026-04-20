#!/usr/bin/env bash
# Quantize ray0rf1re/hyper-nix.1 to GGUF on an Intel i7-7660U (Kaby Lake, 2C/4T)
# or anything equivalent-or-better. Tuned for low-memory ultrabook laptops:
#   - 4 worker threads (matches HT topology on 7660U)
#   - fp16 intermediate only (no fp32 copy on disk unless you ask for it)
#   - single-quant-at-a-time to keep resident set small
#   - niceness + ionice so the machine stays responsive
#
# Usage:
#   ./scripts/quantize_i7_7660u.sh                      # default quants, no upload
#   ./scripts/quantize_i7_7660u.sh --upload             # also push to HF
#   ./scripts/quantize_i7_7660u.sh --out ./myout        # custom output dir
#   HF_TOKEN=hf_xxx ./scripts/quantize_i7_7660u.sh --upload
#
# Requires: python3.12, `pip install "hypernix[llama-cpp]"`
set -euo pipefail

OUT_DIR="./hypernix-gguf"
REPO_ID="ray0rf1re/hyper-nix.1"
TARGET_REPO="ray0rf1re/HyperNix.1-gguf"
UPLOAD=0
QUANTS=(fp16 q8_0 q6_k q4_k_m)   # fp32 skipped by default — it's ~4x larger
THREADS=4                          # i7-7660U = 2 cores / 4 threads
KEEP_FP16=1                        # keep the fp16 intermediate as a release artifact

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out)        OUT_DIR="$2"; shift 2 ;;
    --repo-id)    REPO_ID="$2"; shift 2 ;;
    --target)     TARGET_REPO="$2"; shift 2 ;;
    --upload)     UPLOAD=1; shift ;;
    --threads)    THREADS="$2"; shift 2 ;;
    --with-fp32)  QUANTS=(fp32 fp16 q8_0 q6_k q4_k_m); shift ;;
    --no-keep-fp16) KEEP_FP16=0; shift ;;
    -h|--help)
      sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

mkdir -p "$OUT_DIR"

echo "[i7-7660u] repo=$REPO_ID threads=$THREADS quants=${QUANTS[*]} out=$OUT_DIR"

# Run at reduced priority so the laptop stays usable.
NICE="nice -n 10"
if command -v ionice >/dev/null 2>&1; then
  NICE="ionice -c2 -n7 $NICE"
fi

CMD=(hypernix
  --repo-id "$REPO_ID"
  --output-dir "$OUT_DIR"
  --threads "$THREADS"
  --quants "${QUANTS[@]}"
)
if [[ "$KEEP_FP16" -eq 1 ]]; then
  CMD+=(--keep-intermediate)
fi
if [[ "$UPLOAD" -eq 1 ]]; then
  CMD+=(--upload-to "$TARGET_REPO")
fi

# Cap BLAS/OpenMP to the chosen thread count — the 7660U has no AVX-512 and
# benefits from avoiding oversubscription on its 4 logical cores.
export OMP_NUM_THREADS="$THREADS"
export MKL_NUM_THREADS="$THREADS"
export OPENBLAS_NUM_THREADS="$THREADS"
export TOKENIZERS_PARALLELISM=false

echo "[i7-7660u] $ ${CMD[*]}"
exec $NICE "${CMD[@]}"
