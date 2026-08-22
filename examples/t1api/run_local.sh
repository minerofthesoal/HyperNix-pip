#!/usr/bin/env bash
# HyperNix T1 API — local development deployment.
#
# The zero-infrastructure path: SQLite, loopback, no TLS, docs on. Enough
# to develop a client against, and deliberately NOT enough for production
# — `T1_ENVIRONMENT=production` would refuse to start with this config,
# and that refusal lists exactly what's missing.
#
#   ./examples/t1api/run_local.sh
#
set -euo pipefail

export T1_ENVIRONMENT=development
export T1_DB_PATH="${T1_DB_PATH:-$HOME/.hypernix/t1api/t1api.sqlite3}"
export T1_MODULE_STORAGE_DIR="${T1_MODULE_STORAGE_DIR:-$HOME/.hypernix/t1api/modules}"

# A per-run secret is fine locally — scoped tokens simply don't survive a
# restart, which for development is a feature. Production sets a stable one.
export T1_TOKEN_SECRET="${T1_TOKEN_SECRET:-$(python3 -c 'import secrets; print(secrets.token_hex(32))')}"

# Show the shipped placeholder models so there is something to look at.
# They stay non-routable (status "example") — see wiki/T1-API.md.
export T1_ENABLE_EXAMPLE_MODELS="${T1_ENABLE_EXAMPLE_MODELS:-1}"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

python3 -c "import fastapi" 2>/dev/null || {
  echo "The HTTP layer needs the [t1api] extra:" >&2
  echo "    pip install 'hypernix[t1api]'" >&2
  exit 1
}

cat <<BANNER
HyperNix T1 API — local
  docs     http://${HOST}:${PORT}/docs
  health   http://${HOST}:${PORT}/health

Mint a key and point waiter at it:
    gkey create --type admin --scopes admin,read,write
    waiter serv -A -I http://${HOST}:${PORT} -K <the key> -E
    waiter smoke
    waiter tui

BANNER

exec python3 -m uvicorn hypernix.t1api.app:create_app \
  --factory --host "$HOST" --port "$PORT" --reload
