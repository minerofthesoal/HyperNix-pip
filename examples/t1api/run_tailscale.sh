#!/usr/bin/env bash
# HyperNix T1 API — Tailscale / LAN deployment.
#
# A tailnet deployment is the same server as any other; two things change,
# and both are deliberate rather than incidental:
#
#   1. Bind to the tailnet interface, not just loopback. This script picks
#      up the machine's 100.x address from `tailscale ip -4` so the bind
#      address is the tailnet one rather than 0.0.0.0 — the API is then
#      reachable from the tailnet and from nowhere else, without relying
#      on a firewall rule staying in place.
#
#   2. Tell the server that private addresses are expected here. The SSRF
#      guard rejects RFC1918/loopback/CGNAT (100.64.0.0/10, which is
#      Tailscale's range) by default, because for a general "register a
#      remote server" call a private target is a red flag. On a tailnet it
#      is the whole point, so T1_ALLOW_PRIVATE_DEPLOY_TARGETS says so
#      explicitly, and `POST /servers/register` still needs
#      `allow_private_address: true` per registration.
#
# Restricting access to the tailnet is then one more step, and worth
# taking: the allowlist below means a machine that somehow reaches the
# port from outside the tailnet is refused before its credential is even
# examined.
#
#   ./examples/t1api/run_tailscale.sh
#
set -euo pipefail

command -v tailscale >/dev/null || { echo "tailscale not found in PATH" >&2; exit 1; }

TS_IP="$(tailscale ip -4 | head -1)"
[ -n "$TS_IP" ] || { echo "no Tailscale IPv4 address — is this machine logged in?" >&2; exit 1; }

export T1_ENVIRONMENT="${T1_ENVIRONMENT:-development}"
export T1_TOKEN_SECRET="${T1_TOKEN_SECRET:?set T1_TOKEN_SECRET (python3 -c 'import secrets;print(secrets.token_hex(32))')}"
export T1_DB_PATH="${T1_DB_PATH:-$HOME/.hypernix/t1api/t1api.sqlite3}"
export T1_MODULE_STORAGE_DIR="${T1_MODULE_STORAGE_DIR:-$HOME/.hypernix/t1api/modules}"

# Private deploy targets are expected on a tailnet.
export T1_ALLOW_PRIVATE_DEPLOY_TARGETS=1

# Accept only allowlisted clients, and allowlist the tailnet.
export T1_ALLOW_UNLISTED_CLIENTS=0

PORT="${PORT:-8000}"

cat <<BANNER
HyperNix T1 API — Tailscale
  bind     ${TS_IP}:${PORT}
  tailnet  100.64.0.0/10 (allowlisted below)

From another machine on the tailnet:
    waiter serv -A -L -I http://${TS_IP}:${PORT} -K <key> -E

Allowlist the tailnet once the server is up (admin key required):
    waiter security --allow 100.64.0.0/10 --reason tailnet
    waiter security --allow 127.0.0.1/32  --reason localhost

Register a peer server for module deployment — note the private-address
opt-in, which the SSRF guard requires for a 100.x target:
    waiter servers --register peer-01 --address http://100.x.y.z:8000 --allow-private

BANNER

exec python3 -m uvicorn hypernix.t1api.app:create_app \
  --factory --host "$TS_IP" --port "$PORT"
