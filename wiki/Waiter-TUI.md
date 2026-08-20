# waiter — the T1 API TUI/CLI

`waiter` is the official client for the [HyperNix T1 API](T1-API.md).
Console script, installed with base `hypernix` (no `[t1api]` extra
needed — it's a client, built on stdlib `urllib`, not the server).

**Status: Beta 1 CLI surface, now talking to a Beta 2 server.** The full
curses-style TUI (`-G`) is Beta 3 per the spec's own breakdown; this ships
the CLI subcommands plus a minimal interactive session (`-g`) that just
re-issues the same subcommands without re-typing `-I`/`-K` every time.
`waiter` gets its model list from `GET /models` at request time — it
never hard-codes a model list.

## Quickstart

```bash
waiter serv -A -I "https://myserver.ts.net:8000" -K "T1_..." -E
waiter models
waiter model nanonix-nano
waiter usage
waiter route --plan free --input-tokens 2000
```

`-A` validates the key against the server and saves the config in one
step; `-E` encrypts it at rest (Fernet, same pattern as
`hypernix.keymaster`'s own key-storage encryption — falls back to plain
JSON with a warning if `cryptography` isn't installed;
`pip install hypernix[security]` to enable it).

Config is saved to `~/.hypernix/waiter/waiter.config.jsonl` by default;
override with `-F <path>`.

## Subcommands

| Command | Does |
|---|---|
| `waiter serv` | One-shot setup / refresh / sync — see [flags](#serv-flags) |
| `waiter models` | List models visible in the registry |
| `waiter model <id>` | Detail + availability + your usage for one model |
| `waiter route` | Ask the routing engine which model to use — `--plan`, `--model` (manual), `--input-tokens`, `--auto-fallback` |
| `waiter status` | Server status (version, model count, storage backend) |
| `waiter health` | Liveness check |
| `waiter whoami` | Validate the configured key, show scopes |
| `waiter usage` | Usage summary; `--model <id>` for remaining allowance on one model |
| `waiter servers` | List servers, or `--register NAME --address ADDR [--allow-private]` |
| `waiter modules` | List modules, or `--create NAME [--version]` / `--upload ID --file PATH` / `--sync ID --server-id ID` |
| `waiter jobs get\|cancel <job_id>` | Check or cancel an async job |
| `waiter events` | Poll recent events — `--limit`, `--since <event_id>` |
| `waiter billing` | Balance, or `--transactions`, or `--redeem <token>` |
| `waiter config` | Show the locally saved config (key masked) |

Every subcommand accepts `-I`/`-K`/`-F`/`-P`/`-H` to override the saved
config for just that call, and `--json` for raw JSON instead of a table.

`waiter modules --upload` sends a real multipart/form-data body built by
hand with the standard library (no `requests` dependency) — see
`T1Client.upload_module_local` in `hypernix/waiter/client.py` if you're
curious how; it was tested against a real HTTP server, not mocked.

## `serv` flags

| Flag | Meaning | Status |
|---|---|---|
| `-A` | Automatic configuration: validate + save in one step | ✅ full |
| `-I <addr>` | Server IP / Tailscale IP / public or localhost URL | ✅ full |
| `-K <token>` | T1 token | ✅ full |
| `-E` | Encrypt local config/secrets at rest | ✅ full |
| `-F <path>` | Local config file path | ✅ full |
| `-s` | Save current server/local config to a `.jsonl` file | ✅ full |
| `-L` | Local/Tailscale/localhost-only mode | ✅ stored + used for URL scheme; no separate network enforcement layer yet |
| `-P <port>` | Server port | ✅ full |
| `-H <url>` | Home page URL | ✅ stored |
| `-R` | Quick refresh: re-validate + re-fetch models | ✅ full |
| `-Rf` | Force full refresh | ⚠️ falls back to `-R` behavior + a warning — Beta 2 didn't add a server-push mechanism this could hook into; still Beta 3 scope |
| `-y` | Synchronize local config against the server | ⚠️ syncs against the single configured server's `/config`; the Beta 2 server registry (`waiter servers`) is a related but separate concept — deeper multi-server `-y` integration is Beta 3 |
| `-g` | Open an interactive CLI session | ✅ minimal REPL (`models`/`status`/`usage`/`whoami`/`quit`) |
| `-G` | Open the full TUI | ❌ prints a pointer to Beta 3 — no curses UI yet |
| `-B <ip>` | Blacklist an IP (repeatable) | ⚠️ stored locally only — Beta 2 didn't add this endpoint; Beta 3 |
| `-W <ip>` | Whitelist an IP (repeatable) | ⚠️ stored locally only — Beta 2 didn't add this endpoint; Beta 3 |
| `-r <key_or_server_id>=<limit>` | Force a usage limit on a specific key/server ID | ⚠️ stored locally only — Beta 2 didn't add this endpoint; Beta 3 |
| `-a <ip>` | Appeal/remove an IP from the blacklist | ⚠️ stored locally only — Beta 2 didn't add this endpoint; Beta 3 |
| `-C <key>=<value>` | Additional configuration settings (repeatable) | ⚠️ stored locally only — no server config endpoint consumes it yet |
| `--promote-admin` | After validating, request admin promotion for this key | ✅ full — requires the *authenticating* key to already be admin-scoped (`POST /auth/t1/admin/rotate`); not in the original flag list, added as the operational hook for the "-K supports conversion to admin" requirement |
| `-h` | Help | ✅ (argparse default) |

Flags marked ⚠️/❌ are parsed and accepted so scripts written against this
CLI don't break across betas — they store intent locally and print a
clear message rather than silently no-op'ing or pretending to call an
endpoint that doesn't exist yet.

## Interactive session (`-g`)

```
waiter serv -g -F ~/.hypernix/waiter/waiter.config.jsonl
waiter> models
waiter> usage
waiter> whoami
waiter> quit
```

Not the full TUI — a thin REPL over the same one-shot subcommands, useful
when you're going to run several commands against the same server back to
back.

## Errors

`waiter` surfaces the T1 API's stable error codes directly (e.g.
`MODEL_NOT_SUPPORTED`, `MODEL_QUOTA_EXHAUSTED`, `AUTH_INVALID_KEY`) rather
than a generic "request failed" — see
[T1-API.md#endpoint-reference-beta-1](T1-API.md#endpoint-reference-beta-1)
for the full code list.
