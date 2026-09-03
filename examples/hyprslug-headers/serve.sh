#!/usr/bin/env bash
#
# Serve a sub-bit GGUF to LM Studio without converting it.
#
# The model stays at whatever tier it was quantised to; only the boundary
# moves, from "a file LM Studio opens" to "an endpoint LM Studio calls".
#
# Usage: ./serve.sh MODEL.gguf [PORT]
set -euo pipefail

MODEL="${1:?usage: serve.sh MODEL.gguf [PORT]}"
PORT="${2:-1234}"

# Loopback on purpose. --host 0.0.0.0 publishes an unauthenticated
# inference endpoint to every network this machine is on, which is a
# decision rather than a default.
HOST="${HYPRSLUG_HOST:-127.0.0.1}"

# Memory to spend keeping weights decoded. Empty means "hold everything
# packed", which is the point of a sub-bit tier and also its slowest
# setting; a few gigabytes buys most of the speed back.
CACHE="${HYPRSLUG_CACHE_BYTES:-0}"

echo "hyprslug-headers: $MODEL -> http://$HOST:$PORT/v1"
exec hypernix hyprslug-headers serve "$MODEL" \
  --host "$HOST" --port "$PORT" --cache-bytes "$CACHE"
