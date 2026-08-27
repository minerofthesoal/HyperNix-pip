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

# A tailnet deployment needs a *stable* token secret, unlike run_local.sh
# which is happy to mint a throwaway one per run. Scoped tokens are signed
# with it, so a secret that changes on restart silently invalidates every
# outstanding token — tolerable on a laptop you are developing against,
# not on a server other machines are pointed at.
#
# Three places are checked, in order, before giving up: the environment,
# then the .env that install-t1.sh writes (which already contains a
# generated secret, so an installed deployment needs no further setup),
# then nothing — and "nothing" is a message you can act on rather than a
# bare parameter-expansion error.
T1_CONFIG_DIR="${T1_CONFIG_DIR:-$HOME/.hypernix/t1api}"
if [ -z "${T1_TOKEN_SECRET:-}" ] && [ -r "$T1_CONFIG_DIR/.env" ]; then
  # Read the one assignment rather than sourcing the file: sourcing runs
  # whatever is in it and would also import every other setting, which is
  # not what this script is asking for.
  T1_TOKEN_SECRET="$(sed -n "s/^T1_TOKEN_SECRET=//p" "$T1_CONFIG_DIR/.env" | tail -1)"
  # Tolerate a quoted value.
  T1_TOKEN_SECRET="${T1_TOKEN_SECRET%\'}"; T1_TOKEN_SECRET="${T1_TOKEN_SECRET#\'}"
  T1_TOKEN_SECRET="${T1_TOKEN_SECRET%\"}"; T1_TOKEN_SECRET="${T1_TOKEN_SECRET#\"}"
  [ -n "$T1_TOKEN_SECRET" ] && echo "Using the token secret from $T1_CONFIG_DIR/.env" >&2
fi

if [ -z "${T1_TOKEN_SECRET:-}" ]; then
  # Deliberately not a ${VAR:?...} expansion. That form strips the quotes
  # from its own message before printing it, so the command it suggests
  # arrives unpasteable — `python3 -c import secrets;print(...)` is a
  # syntax error in both the shell and Python.
  cat >&2 <<'NEEDSECRET'
T1_TOKEN_SECRET is not set.

A tailnet deployment needs a stable one: it signs the scoped tokens, so a
secret that changes on restart invalidates every token already issued.

Generate one and keep it:

    mkdir -p ~/.hypernix/t1api
    printf 'T1_TOKEN_SECRET=%s\n' \
      "$(python3 -c 'import secrets; print(secrets.token_hex(32))')" \
      >> ~/.hypernix/t1api/.env
    chmod 600 ~/.hypernix/t1api/.env

This script reads that file, so re-running it afterwards is all that is
needed. Or set it for one run:

    export T1_TOKEN_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"

install-t1.sh writes this file for you, along with the rest of the
configuration.
NEEDSECRET
  exit 1
fi
export T1_TOKEN_SECRET
export T1_DB_PATH="${T1_DB_PATH:-$HOME/.hypernix/t1api/t1api.sqlite3}"
export T1_MODULE_STORAGE_DIR="${T1_MODULE_STORAGE_DIR:-$HOME/.hypernix/t1api/modules}"

# Private deploy targets are expected on a tailnet.
export T1_ALLOW_PRIVATE_DEPLOY_TARGETS=1

# Accept only allowlisted clients, and allowlist the tailnet.
export T1_ALLOW_UNLISTED_CLIENTS=0

PORT="${PORT:-8000}"

python3 -c "import fastapi" 2>/dev/null || {
  echo "The HTTP layer needs the [t1api] extra:" >&2
  echo "    pip install 'hypernix[t1api]'" >&2
  exit 1
}

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
