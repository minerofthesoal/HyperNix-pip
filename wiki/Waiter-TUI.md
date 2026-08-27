# waiter — the T1 API TUI/CLI

`waiter` is the official client for the [HyperNix T1 API](T1-API.md).
Console script, installed with base `hypernix` (no `[t1api]` extra
needed — it's a client, built on stdlib `urllib`, not the server).

**Status: Beta 3 — complete.** Every flag in the spec's `serv` list is
wired to real behaviour, and the full curses TUI (`-G`) ships. `waiter`
gets its model list, availability, limits, quota and fallback chain from
the server at request time — it never hard-codes a model list, and it
never decides what you may use.

As of Beta 3 the client sits on [`hypernix.t1sdk`](T1-API.md#the-sdk)
rather than being a second implementation of the same HTTP calls; the
subcommand surface is unchanged.


## Versions, help, and connection failures

```bash
waiter version            # package, waiter, T1 API, key formats, the server
waiter version --json
waiter help               # list the longer help topics
waiter help connect       # pointing waiter at a server
waiter help keys          # which credential to use
waiter help hyperlink     # pairing a phone
waiter help find          # locating a server you did not configure
```

`waiter version` prints four numbers that move independently — the
package, waiter's protocol version, the T1 API (with the oldest client it
speaks to), and the key formats — plus the connected server's version
when one is reachable. Comparing them is how "my key is refused" and "my
client is too old" get diagnosed. The server line is fetched
unauthenticated, and omitted rather than guessed at when the server
cannot be reached.

### When a connection fails

waiter explains an unreachable server instead of restating the errno. It
names the address, **where that address came from**, and the command that
fixes it:

```
✗ Could not reach http://127.0.0.1:1234/hyperlink/pair ([Errno 111] Connection refused)
  Address from: the saved config (~/.hypernix/waiter/waiter.config.jsonl)

Port 1234 is LM Studio's default, not the T1 API's (8000).
  `waiter lmstudio` reaches it through the T1 server, not directly.
  If you meant the T1 API:  waiter serv -A -I http://127.0.0.1:8000 -K <key>
```

The distinction that matters: **LM Studio (1234) and Ollama (11434) are
model backends the T1 server talks to, not addresses waiter should point
at.** `waiter lmstudio` reaches LM Studio *through* the server. Pointing
waiter straight at one gives a connection refused, or a puzzling 404 from
something that is not a T1 API.

On failure waiter probes whether the port accepts a connection at all,
and if it does, what answers there — a T1 API, an OpenAI-compatible
backend, or some other web server — so the three cases get three
different answers:

| What it found | What it says |
| --- | --- |
| Nothing listening | Nothing is listening on `host:port`, and how to start the server |
| A known bridge port | That port belongs to LM Studio / Ollama, and the T1 address to use instead |
| Something that is not a T1 API | What answered, and how to re-point waiter |

These probes deliberately bypass the proxy environment: a diagnostic asks
whether *this* host is up, and a proxy in between answers a different
question. Ordinary API traffic still honours `HTTP_PROXY` as before.

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
| `waiter tui` | Open the full curses dashboard (same as `serv -G`) |
| `waiter cost` | Spend, per-model/server breakdowns, forecasts, and `--estimate-model` |
| `waiter keys` | List keys; `--assign` a plan/account/models; `--import-file` |
| `waiter deploy <id> --to a,b` | Push a module to trusted servers, `--wait` to follow the job |
| `waiter security` | Network policy (`--block`/`--allow`/`--appeal`), forced limits, your own rate-limit budget |
| `waiter audit` | Read the server's audit trail (admin) |
| `waiter doctor` | Check a server's configuration; exits non-zero on production warnings |
| `waiter smoke` | Run smoke tests against a server (`--write` for a self-cleaning write test) |
| `waiter version` | Package, waiter, T1 API and key format versions; `--json` |
| `waiter help <topic>` | Longer help — `connect`, `keys`, `hyperlink`, `find` |

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
| `-L` | Local/Tailscale/localhost-only mode | ✅ chooses the URL scheme; the server-side counterpart is `T1_ALLOW_UNLISTED_CLIENTS=0` plus an allowlisted tailnet — see `examples/t1api/run_tailscale.sh` |
| `-P <port>` | Server port | ✅ full |
| `-H <url>` | Home page URL | ✅ stored |
| `-R` | Quick refresh: re-validate + re-fetch models | ✅ full |
| `-Rf` | Force full refresh | ✅ full — models, servers, modules, events, and the server's config |
| `-y` | Synchronize local config against the server | ✅ full — mirrors the server's `/config` and model count into the local config so `waiter config` reflects the server rather than what was typed weeks ago |
| `-g` | Open an interactive CLI session | ✅ REPL (`models`/`status`/`usage`/`whoami`/`quit`) |
| `-G` | Open the full TUI | ✅ full — see [The TUI](#the-tui) |
| `-B <ip\|cidr>` | Blacklist an address or range (repeatable) | ✅ full — applied to the server (admin key required) *and* saved locally |
| `-W <ip\|cidr>` | Allowlist an address or range (repeatable) | ✅ full — same |
| `-r <subject>=<n>/<window>` | Force a limit on a key/server, e.g. `key:abc123=60/60s` or `server:s1=1000t/1h` | ✅ full — `t` suffix means tokens; only ever tightens |
| `-a <ip\|cidr>` | Appeal: remove an entry from the server's lists | ✅ full |
| `-C <key>=<value>` | Additional configuration settings (repeatable) | ✅ stored locally; `-y` populates it from the server's own settings |
| `--promote-admin` | After validating, request admin promotion for this key | ✅ full — requires the *authenticating* key to already be admin-scoped (`POST /auth/t1/admin/rotate`); not in the original flag list, added as the operational hook for the "-K supports conversion to admin" requirement |
| `-h` | Help | ✅ (argparse default) |

`-B`/`-W`/`-a`/`-r` write to the server **and** to the local config. That
is deliberate rather than redundant: the local copy is what `waiter
config` shows and what a re-run of `waiter serv -A` re-applies against a
rebuilt server, and it is the only record available when your key is not
admin — in which case the server call is refused and the CLI says so
plainly instead of pretending it worked.

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

## The TUI

```bash
waiter tui                 # or: waiter serv -G
```

Eight panes, `TAB` between them, everything sourced from the API:

| Pane | Shows |
|---|---|
| **Models** | every registered model, availability, input/output limits, minimum plan — `ENTER` selects one |
| **Quota** | per-model input and output bars, with `EXHAUSTED` when a cap is hit |
| **Usage** | window and all-time totals, spend, account balance, forecast, per-model breakdown |
| **Jobs** | recent jobs with live progress; `c` cancels the selected one |
| **Servers** | registered servers, trust level, status, address |
| **Modules** | modules with status and size; `u` uploads a local file, `d` deploys to a server |
| **Events** | live event tail |
| **Settings** | server version, backend, which protections are on, your key's scopes, and any production warnings the server reports |

The Models pane also renders the **fallback chain** — the cascade the
server actually walked on the last routing decision, with each step marked
`EXHAUSTED`, skipped, or selected. That comes from `POST /models/route`'s
own `considered` list; the TUI never reconstructs a chain from registry
`fallback_model` fields, because the plan's policy decides the order, not
the model entry.

`a` toggles automatic routing. Turning it on immediately asks the server
to route, so the header shows the model that would actually be used rather
than the last one you picked by hand. Selecting an exhausted model tells
you it is exhausted rather than silently substituting another — the server
returns `MODEL_QUOTA_EXHAUSTED` and the TUI reports it.

Refreshes happen on a background thread, so an unreachable server shows
stale data with an error banner rather than freezing the terminal.

`?` lists the keys. `q` quits.

**Windows:** `curses` is not in the standard library there. `waiter tui`
says so and points at the one-shot subcommands, which work everywhere;
`pip install windows-curses` enables the TUI.

## Checking a server

```bash
waiter doctor      # configuration: what would block a production start
waiter smoke       # behaviour: auth enforced, registry gated, limits on
waiter smoke --write   # also creates and removes a scratch module
```

`doctor` reads `GET /status` and prints every production warning the
server reports, exiting non-zero on a production server with warnings — so
it works as a deployment gate. `smoke` treats *expected refusals as
passes*: a non-admin key being refused `/audit` is a pass, and being
served it is a failure.

## Errors

`waiter` surfaces the T1 API's stable error codes directly (e.g.
`MODEL_NOT_SUPPORTED`, `MODEL_QUOTA_EXHAUSTED`, `AUTH_INVALID_KEY`,
`IP_BLOCKED`, `RATE_LIMITED`) rather than a generic "request failed" — see
[T1-API.md#endpoint-reference](T1-API.md#endpoint-reference).

Underneath, the SDK maps those codes to an exception hierarchy, so code
built on `hypernix.t1sdk` can catch `T1QuotaError` or `T1AuthError`
instead of matching strings. `waiter`'s own `T1ClientError` is an alias
for the SDK's base `T1Error`, so a single `except` still catches
everything.
