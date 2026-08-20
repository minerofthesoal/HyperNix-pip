# HyperNix T1 API

A controlled HTTP gateway into HyperNix-pip. Built as `hypernix.t1api`,
mountable into any Python server. The client requests an operation; the
server decides what exists, what's available, and how much is left — see
[Design principle](#design-principle).

**Status: Beta 2** (`0.71.5b2`). This page is the living contract for
what's actually implemented vs. planned — cross-reference against the
[Roadmap](#roadmap) before assuming an endpoint exists.

## Contents

- [Quickstart](#quickstart)
- [Installation](#installation)
- [Architecture](#architecture)
- [Model registry](#model-registry)
- [Authentication](#authentication)
- [Quota & usage](#quota--usage)
- [Model routing & quota cascade](#model-routing--quota-cascade)
- [Servers](#servers)
- [Modules](#modules)
- [Jobs](#jobs)
- [Events](#events)
- [Billing](#billing)
- [Endpoint reference](#endpoint-reference)
- [Configuration](#configuration)
- [Security](#security)
- [Roadmap](#roadmap)
- [Design principle](#design-principle)

## Quickstart

```bash
pip install 'hypernix[t1api]'
cp .env.t1api.example .env   # fill in T1_TOKEN_SECRET at minimum
python3 -m uvicorn hypernix.t1api.app:create_app --factory --reload
# → http://127.0.0.1:8000/docs (Swagger UI)
```

Mint yourself a T1 key with the existing `gkey` CLI (T1 keys are
`hypernix.keymaster` keys — the T1 API doesn't create its own key format):

```bash
gkey create --type admin --scopes admin,read,write
```

Then drive the server with `waiter` (see
[wiki/Waiter-TUI.md](Waiter-TUI.md)):

```bash
waiter serv -A -I http://127.0.0.1:8000 -K <the T1 key from gkey create> -E
waiter models
```

## Installation

`hypernix.t1api`'s **core** (registry, storage, usage, auth, config,
errors) is pure Python + stdlib and imports fine with a base `hypernix`
install — same as `hypernix.keymaster` / `hypernix.gatekeeper`, which it
wraps rather than duplicates. The **HTTP layer**
(`hypernix.t1api.create_app`, the routers, Pydantic schemas) needs the
optional extra:

```bash
pip install 'hypernix[t1api]'   # fastapi, uvicorn, pydantic, python-dotenv
```

Importing `hypernix.t1api.create_app` without the extra raises a clear
`ImportError` telling you to install it, instead of failing deep inside
FastAPI's own import chain.

### Local / Tailscale deployment

No separate deployment mode needed — a Tailscale or LAN deployment is the
same `create_app()` + `uvicorn` command as anything else. Two things
change:

1. **Bind to the Tailscale/LAN interface**, not just loopback:
   ```bash
   uvicorn hypernix.t1api.app:create_app --factory --host 0.0.0.0 --port 8000
   ```
2. **Pass `allow_private_address=True`** wherever you register something
   at a private address — `POST /servers/register`'s
   `allow_private_address` field, or `ServerRegistry.register(...,
   allow_private_address=True)` directly. Without it, `t1api.security`'s
   SSRF guard rejects RFC1918/loopback/Tailscale (`100.64.0.0/10`)
   addresses by default (see [Security](#security)) — that's the correct
   default for "register a remote server" in general, and the explicit
   opt-in is what makes a local deployment's private addresses expected
   rather than suspicious.

`waiter serv -L` (`--local-only`) records this intent client-side in the
saved config (see [Waiter-TUI.md](Waiter-TUI.md)) but doesn't itself
change server-side behavior — the two flags above are what actually
matter on the server.

## Architecture

```
hypernix/t1api/
  errors.py     stable T1ErrorCode enum + T1APIError            (stdlib only)
  registry.py   ModelRegistry / ModelEntry — the model registry (stdlib only)
  storage.py    UsageStore — SQLite usage events                (stdlib only)
  usage.py      UsageMeter — per-key/model usage + exhaustion    (stdlib only)
  auth.py       T1AuthService — wraps Keymaster + Gatekeeper     (stdlib only)
  config.py     T1APIConfig — env-var configuration              (stdlib only)
  schemas.py    Pydantic request/response models                 (needs [t1api])
  deps.py       FastAPI Depends() wiring                          (needs [t1api])
  app.py        create_app() factory                              (needs [t1api])
  routers/      health, auth, models, usage, config                (needs [t1api])
```

The core/HTTP split is deliberate: routing, quota math, and registry
enforcement are testable (and reusable, e.g. from `waiter` or a future
non-HTTP embedding) without pulling in FastAPI. `tests/test_t1api_core.py`
and `tests/test_t1api_auth.py` exercise the core directly and need no
extra beyond base `hypernix`; only `tests/test_t1api_http.py` needs
`pip install hypernix[t1api-test]` (fastapi/pydantic/uvicorn *and* httpx,
which Starlette's `TestClient` requires and which plain `[t1api]` doesn't
pull in).

### Mounting into an existing server

```python
from hypernix.t1api import create_app

# Standalone
app = create_app()

# Mounted under a prefix inside an existing FastAPI app
existing_app.mount("/t1", create_app(mount_prefix="/t1"))

# Or merge routes directly into an existing app's own router
t1 = create_app()
for route in t1.routes:
    existing_app.router.routes.append(route)
```

Every dependency (`Keymaster`, `Gatekeeper`, `ModelRegistry`,
`UsageStore`) is injectable into `create_app(...)` — useful for tests, or
for sharing one `Keymaster` instance between the T1 API and another
service in the same process.

## Model registry

**Hard requirement: the T1 API only exposes models explicitly registered
in the model registry.** Nothing discovers models from HyperNix-pip's
checkpoint cache, HuggingFace Hub, or a client-supplied path. An
unregistered `model_id` always fails the same way:

```json
{"error": {"code": "MODEL_NOT_SUPPORTED", "message": "...", "details": {"model_id": "..."}}, "request_id": "..."}
```

### Example registry data

`hypernix/t1api/data/model_registry.example.json` ships the nine models
from the original T1 API spec (HyperNix 1, Ryiver 1, nanoNix, ...). The
spec is explicit that these are placeholders, so every seed entry loads
with `status: "example"` / `is_example_entry: true` and **is invisible**
to `GET /models`, `require()`, etc. unless:

- `T1_ENABLE_EXAMPLE_MODELS=1` is set, or
- the registry is constructed with `ModelRegistry.load(include_examples=True)`.

This is what makes the "only registered models" rule mean something in
practice — until you swap in real entries, the registry is empty from the
API's point of view, not silently populated with spec placeholders.

### Adding real models

Data change, not a code change. Either:

1. Write a JSON file in the same shape as `model_registry.example.json`
   and point `T1_MODEL_REGISTRY_PATH` (or `ModelRegistry.load(path=...)`)
   at it, or
2. Call `registry.register(entry)` from an admin-only code path (the
   registry itself doesn't check scopes — the caller must).

Required fields, per the spec: `model_id` (a stable slug — **never** a
parameter-count string, e.g. `nanonix-mini-lite` not `85b-25.25b`),
`display_name`, `version`, `total_parameters`, `active_parameters`,
`architecture`, `supported_tasks`, `availability`, `minimum_plan`,
`free_tier_available`, `api_available`, `local_available`,
`remote_available`, `context_limit`, `input_token_limit`,
`output_token_limit`, `tool_call_limit`, `pricing`, `routing_priority`,
`fallback_model`, `license`, `status`.

`routing_priority` and `fallback_model` are recorded starting in Beta 1
but not yet *acted on* — the router/cascade engine that walks the
fallback chain is Beta 2 (see [Roadmap](#roadmap)).

## Authentication

Two credential types, both accepted on every authenticated route via
`Authorization: Bearer <credential>`:

1. **Raw T1 keys** — `hypernix.keymaster.Keymaster` keys (`T1_...`
   strings), created with `gkey create` or `Keymaster.create()`.
   `POST /auth/t1/validate` checks one without consuming it for anything
   else.
2. **Scoped tokens** — short-lived, obtained by exchanging a raw key via
   `POST /auth/token`. Format: `T1S.<payload_b64>.<sig_b64>`, HMAC-SHA256
   signed with `T1_TOKEN_SECRET`. Deliberately *not* a full JWT — no new
   required dependency for something this small. A token's scopes must be
   a subset of the underlying key's scopes (narrowing only, never
   widening). Rotating `T1_TOKEN_SECRET` invalidates every outstanding
   token immediately — that's the revocation story for a stateless token.

### Admin rotate / promote

`POST /auth/t1/admin/rotate` is admin-only (`AUTH_ADMIN_REQUIRED`
otherwise) and implements the spec's "convert a normal T1 token into an
admin token only when the authenticated user has the required
permission": the *requester* must already hold an admin-scoped key. It
rotates the target key (never mutates a live key's scopes in place —
consistent with how `Keymaster.rotate()` already treats rotation as
"replace, don't mutate") and, if `promote_to_admin: true`, reissues it as
`KeyType.ADMIN`.

## Quota & usage

Beta 1 ships **basic per-key/per-model usage tracking**, not the full
routing/cascade engine (Beta 2). What's enforced today:

- Every usage record validates its `model_id` against the registry first
  — you cannot record usage against an unregistered model.
- A model's allowance is **fully exhausted** the moment *either* its input
  token cap *or* its output token cap is reached — independently, not
  averaged. `assert_not_exhausted()` raises `MODEL_QUOTA_EXHAUSTED`;
  `GET /usage/remaining` reports it without raising.
- Accounting is per-key **and** per-model — exhausting one model never
  touches another model's quota, matching the spec's "each model has
  independent accounting."
- The reset window is a fixed rolling period (`T1_USAGE_RESET_PERIOD_SECONDS`,
  default 24h) — a config value, not hard-coded logic.

**Not yet implemented** (Beta 2): automatic fallback when a model is
exhausted, plan-aware cascade hierarchies (free vs. paired-plan fallback
chains), manual-selection-of-an-exhausted-model handling beyond the raw
error, multi-tier reset windows.

## Model routing & quota cascade

`hypernix.t1api.routing` — not in the spec's literal endpoint list, but
its "MODEL ROUTING" / "QUOTA CASCADE" sections describe the engine in
detail, so Beta 2 gives it one: `POST /models/route`.

```bash
curl -X POST $HOST/models/route -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"plan": "free", "input_tokens": 2000}'
# → {"model_id": "nanonix-mini-plus", "reason": "...", "cascade_position": 0, ...}
```

Cascades are data, not code — `t1api/data/routing_policies.example.json`
ships the spec's own free-tier and paired-plan examples verbatim (short
prompts route to `nanonanonano-n3`, long prompts to `nanonix-mini-lite`,
then `nanonix-nano`, then `nanonanonanonano-n4`; the paired plan falls
back to `nanonix-mini` instead of `nanonix-mini-lite` after N^3). Point
`T1_MODEL_REGISTRY_PATH`/a custom `RoutingTable.load(path=...)` at your
own file to replace it.

Manual selection (`model_id` set in the request body) never silently
substitutes a different model — an exhausted model raises
`MODEL_QUOTA_EXHAUSTED` unless `automatic_fallback: true` is set, in
which case it walks the cascade starting after the requested model's
position. Every model, whether reached automatically or manually, still
goes through `ModelRegistry.require()` — a routing request can't name an
unregistered model any more than any other endpoint can.

## Servers

`hypernix.t1api.servers` — tracks which servers exist and whether
they're trusted. A server starts `untrusted` on registration; only an
admin can promote it (`PATCH /servers/{id}`) to `trusted`, or mark it
`local` at registration time for the operator's own loopback/Tailscale
address. `require_trusted()` is the enforcement point other subsystems
(module sync) call before treating a server as a valid target — see
[Security](#security) for the SSRF guard on `address`.

## Modules

`hypernix.t1api.modules` — module creation, local upload, remote-source
*registration* (not fetching — see below), versioning (`(name, version)`
is unique), and sync-tracking against the server registry.

**What "sync" means in this beta**: `POST /modules/{id}/sync` queues a
`module_sync` job. The handler checks the target server is trusted
(`ServerRegistry.require_trusted`) and then records the association
(`deployed_servers`) — there is no real network transport pushing module
bytes to a live remote server, because Beta 2 has no second real server
to test that against safely. The trust-gating and job-tracking pipeline
is real and tested end-to-end (`tests/test_t1api_http_beta2.py`); actual
byte transport is Beta 3 scope.

**What "remote upload" means in this beta**: `POST /modules/upload/remote`
validates the source URL (SSRF guard, same as server registration) and
marks the module `pending_fetch`. It does not fetch the URL. Fetching is
deliberately not wired to a job kind yet — there's no safe way to exercise
an actual outbound HTTP fetch in the sandbox this was built in, and doing
it without testing it felt worse than shipping the validation/tracking
half honestly and leaving the fetch itself for Beta 3.

The registry never executes anything it stores — see the module docstring
in `t1api/modules.py` for why that's a hard design constraint, not an
oversight.

## Jobs

`hypernix.t1api.jobs` — `queued → running → succeeded|failed|cancelled`,
exactly the state machine the spec specifies. Job *kinds* are a plugin-
style handler registry (`JobQueue.register_handler`); submitting an
unregistered kind returns `NOT_SUPPORTED` rather than inventing behavior.
Beta 2 registers exactly one real handler, `module_sync` (composed in
`t1api/app.py` from `ModuleRegistry` + `ServerRegistry`, since it's the
one place allowed to depend on both).

Execution is a small in-process `ThreadPoolExecutor`, not an external task
queue — consistent with "SQLite for development" scale. Cancellation is
cooperative (`threading.Event`) and was tested against a real
in-flight background job, not just simulated.

## Events

`hypernix.t1api.events` — an in-process pub/sub bus. `GET /events`
matches the spec's literal endpoint (polling, with `since_id`/`type`/
`limit` filters). `GET /events/stream` is an addition beyond the spec's
list — a Server-Sent-Events live tail, since "event streaming" reads most
naturally as a stream and a pure poll can't be that.

Every job state transition auto-publishes a `job.<status>` event with no
per-handler code required (`JobQueue(event_bus=...)`); server/module
mutations publish from their routers directly
(`server.registered`, `module.uploaded`, etc). `GET /events` therefore
gives a unified timeline across all of Beta 2's subsystems, not one feed
per subsystem.

## Billing

`hypernix.t1api.billing` — **an internal ledger, not a payment processor
integration.** There is no Stripe/card-network call anywhere in this
module. A "payment token" is an admin-minted, single-use redeemable
credit code (think: a gift-card code), matching the spec's own wording
("payment token"). Real money-in (charging an actual card) is a
different, much larger integration this spec doesn't describe and this
implementation doesn't attempt.

- `POST /billing/payment-token` (admin-only) mints a token and returns
  the raw value exactly once — it is never retrievable again; only its
  SHA-256 hash is persisted.
- `POST /billing/redeem` credits an account and marks the token spent;
  redeeming twice returns `PAYMENT_TOKEN_ALREADY_REDEEMED`.
- `POST /billing/add-balance` (admin-only) is a direct credit with no
  token trail — the most trusted operation in this module.
- Every transaction is masked in API responses (`txn_abcd1234…`) — see
  `Transaction.to_dict()` / `PaymentTokenRecord.to_dict()`.
- `BillingLedger.charge()` exists (a debit that raises
  `INSUFFICIENT_BALANCE` rather than going negative) but is **not**
  automatically wired to usage metering yet — cost-per-request billing
  integration (the spec's "actual cost"/"estimated cost" usage endpoints)
  is Beta 3 scope.

## Endpoint reference

All responses include `request_id`. Errors use the envelope shown in
[Model registry](#model-registry) above with a code from
`hypernix.t1api.errors.T1ErrorCode`.

**Beta 1**

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/health` | none | liveness |
| GET | `/status` | none | version, model count, storage backend |
| GET | `/config` | none | explicit allowlist only — never secrets |
| POST | `/auth/t1/validate` | none (key in body) | validate a raw T1 key |
| POST | `/auth/token` | none (key in body) | exchange a key for a scoped token |
| POST | `/auth/t1/rotate` | bearer | rotate the caller's own key |
| POST | `/auth/t1/admin/rotate` | bearer, admin | rotate/promote another key |
| GET | `/models` | none | list registry entries |
| GET | `/models/{model_id}` | none | full entry detail |
| GET | `/models/{model_id}/availability` | none | registry-level availability |
| GET | `/models/{model_id}/usage` | bearer | caller's usage for this model |
| GET | `/usage/current` | bearer | all-time + current-window totals |
| GET | `/usage/remaining?model_id=` | bearer | remaining allowance for one model |

**Beta 2**

| Method | Path | Auth | Notes |
|---|---|---|---|
| POST | `/models/route` | bearer | routing/quota-cascade decision (addition, not in the spec's literal list) |
| GET | `/servers` | bearer | list registered servers |
| POST | `/servers/register` | bearer | register a server (starts `untrusted`) |
| PATCH | `/servers/{server_id}` | bearer, admin | trust-level/status/capability changes |
| DELETE | `/servers/{server_id}` | bearer, admin | deregister |
| GET | `/modules` | bearer | list modules (own, or all for admins) |
| POST | `/modules/create` | bearer | create a draft module entry |
| POST | `/modules/upload/local?module_id=` | bearer | multipart file upload, activates the module |
| POST | `/modules/upload/remote?module_id=` | bearer | register (not fetch) a remote source |
| GET | `/modules/{module_id}` | bearer | module detail |
| PATCH | `/modules/{module_id}` | bearer, owner/admin | metadata/status |
| DELETE | `/modules/{module_id}` | bearer, owner/admin | delete entry + stored file |
| POST | `/modules/{module_id}/sync` | bearer, owner/admin | queues a `module_sync` job |
| POST | `/jobs` | bearer | submit a job (`NOT_SUPPORTED` for unregistered kinds) |
| GET | `/jobs/{job_id}` | bearer | job status/result/error |
| POST | `/jobs/{job_id}/cancel` | bearer | cooperative cancellation |
| GET | `/events` | bearer | poll recent events (`since_id`/`type`/`limit`) |
| GET | `/events/stream` | bearer | SSE live tail (addition, not in the spec's literal list) |
| GET | `/billing/balance` | bearer | caller's own balance |
| GET | `/billing/transactions` | bearer | caller's own transaction history |
| POST | `/billing/payment-token` | bearer, admin | mint a redeemable token |
| POST | `/billing/redeem` | bearer | redeem a token into an account |
| POST | `/billing/add-balance` | bearer, admin | direct credit |

Note the two `module_id`-as-query-parameter endpoints
(`/modules/upload/local`, `/modules/upload/remote`) — deliberate, matching
the spec's literal paths (`POST /modules/upload/local`, no `{module_id}`
in the template), unlike every other module endpoint which puts
`module_id` in the path.

Full request/response examples: run the server and open `/docs` (Swagger
UI, auto-generated from `schemas.py`) — that's the canonical, always-in-sync
source rather than a hand-maintained example file that can drift.

## Configuration

See `.env.t1api.example` for every variable — each maps 1:1 to a
`T1APIConfig` field. Nothing under `T1APIConfig.public_dict()` (what
`GET /config` returns) can leak a secret: it's an explicit allowlist, not
"everything except a blocklist," specifically so a newly-added secret
field can't accidentally start being served.

## Security

- API keys/tokens are never logged. The exception-handling path logs the
  error *code*, not the credential.
- `GET /config` is an allowlist (see above).
- Scoped tokens can only narrow a key's scopes, never widen them.
- Admin operations (`/auth/t1/admin/rotate`, server trust promotion,
  billing mint/add-balance) require the *requester* to already hold
  `KeyType.ADMIN` + `KeyScope.ADMIN` — checked before anything else runs.
- **SSRF guard** (`t1api.security.validate_remote_address`): only
  `http`/`https` schemes are ever accepted; the cloud-metadata SSRF target
  (`169.254.169.254`) is always rejected; private/loopback/link-local
  addresses require explicit `allow_private=True` (surfaced as
  `allow_private_address` on server registration, `allow_private` on
  remote module source registration) — the knob a Tailscale/local
  deployment needs, without silently allowing SSRF for everyone else.
- **Path-traversal guard** (`t1api.security.sanitize_module_path`): every
  local module upload resolves its filename against a fixed storage
  directory and rejects anything that would escape it.
- **No code execution**: the module system never imports, executes, or
  interprets anything it stores — see the module docstring in
  `t1api/modules.py`.
- **Server trust gating**: `ServerRegistry.require_trusted()` blocks
  module sync to any server that isn't `trusted`/`local` — a fresh
  registration is always `untrusted` until an admin promotes it.
- mTLS, IP allow/blacklists, and rate-limiting middleware beyond
  `Gatekeeper`'s existing per-key quota enforcement are Beta 3.

## Roadmap

Matches the spec's own beta breakdown exactly — nothing here is
renumbered or reinterpreted.

| Beta | Scope | Status |
|---|---|---|
| **1** | Core FastAPI server, T1 auth + scoped tokens, model registry, basic per-key/model usage tracking, `/health` `/status` `/models` + auth/usage/config endpoints, basic `waiter` CLI, SQLite, OpenAPI docs | **Shipped** |
| **2** | Module registry, module upload/sync, server registry, async jobs, event streaming, quota cascade, model routing engine, billing/payment-token support, Tailscale/local deployment guide | **Shipped** (this doc) — encrypted secrets beyond Keymaster's existing pattern (module content at rest, payment token hashing) partially covered; a dedicated at-rest encryption pass for module blobs specifically is still open |
| **3** | Production hardening, PostgreSQL backend, complete audit logging, mTLS, advanced rate limiting, remote multi-server deployment (real module byte transport + remote-source fetch), full `waiter` TUI (curses-style `-G`), complete SDK, complete test suite, deployment docs, security audit checklist, cost-per-request billing integration | Not started |
| **4** | `hyped-pro` T1-key support against a local T1 API server; `hyped-pro` auto-displaying the current public release version; `qwen3.8-27b` registry entry | Not started |

## Design principle

> The T1 API is a controlled gateway into HyperNix. The client must
> never be trusted to decide what it is allowed to access.

The server determines which models exist, which are available, which
limits apply, which fallbacks are allowed, how much usage remains, and
what an operation costs. The client only requests an operation — Beta 1's
`ModelRegistry.require()` and `UsageMeter.assert_not_exhausted()` are the
two enforcement points that currently make that true; Beta 2 adds the
routing/server/module counterparts.
