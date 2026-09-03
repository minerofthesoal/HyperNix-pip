#!/usr/bin/env bash
#
# Turn a sub-bit GGUF into one LM Studio can open as a file.
#
# This is the trade, stated up front: the output is NOT a sub-bit model.
# It is a stock-quantised copy of one, several times larger, carrying the
# error of both quantisations. If you want to keep the tier, use
# serve.sh instead.
#
# Usage: ./wrap-for-lmstudio.sh MODEL.gguf [TARGET_TYPE]
set -euo pipefail

MODEL="${1:?usage: wrap-for-lmstudio.sh MODEL.gguf [TARGET_TYPE]}"
TARGET="${2:-}"

BASE="$(basename "${MODEL%.gguf}")"
OUT_DIR="${LMSTUDIO_HOME:-$HOME/.lmstudio}/models/HyperNix/${BASE}-compat"
mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/${BASE}-compat.gguf"

# --to is optional: each tier has a default, chosen as the narrowest
# upstream type that does not throw away more than the tier already has.
if [ -n "$TARGET" ]; then
  hypernix hyprslug-headers wrap "$MODEL" -o "$OUT" --to "$TARGET"
else
  hypernix hyprslug-headers wrap "$MODEL" -o "$OUT"
fi

echo
echo "LM Studio should list it after a rescan:"
echo "  $OUT"
