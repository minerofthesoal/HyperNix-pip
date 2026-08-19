# HyperNix T1 API

A controlled HTTP gateway into HyperNix-pip. Built as `hypernix.t1api`,
mountable into any Python server. The client requests an operation; the
server decides what exists, what's available, and how much is left — see
[Design principle](#design-principle).

**Status: Beta 1** (`0.71.5b1`). This page is the living contract for
what's actually implemented vs. planned — cross-reference against the
[Roadmap](#roadmap) before assuming an endpoint exists.

## Contents

- [Quickstart](#quickstart)
- [Installation](#installation)
- [Architecture](#architecture)
- [Model registry](#model-registry)
- [Authentication](#authentication)
- [Quota & usage](#quota--usage)
- [Endpoint reference (Beta 1)](#endpoint-reference-beta-1)
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

## Endpoint reference (Beta 1)

All responses include `request_id`. Errors use the envelope shown in
[Model registry](#model-registry) above with a code from
`hypernix.t1api.errors.T1ErrorCode`.

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
- Admin operations (`/auth/t1/admin/rotate`) require the *requester* to
  already hold `KeyType.ADMIN` + `KeyScope.ADMIN` — checked before
  anything else runs.
- SSRF/path-traversal prevention, mTLS, IP allow/blacklists, and rate
  limiting middleware are Beta 2/3 — Beta 1 relies on
  `Gatekeeper`'s existing per-key quota enforcement
  (`T1AuthService.check_quota`) and doesn't yet add T1-API-specific
  network-level guardrails.

## Roadmap

Matches the spec's own beta breakdown exactly — nothing here is
renumbered or reinterpreted.

| Beta | Scope | Status |
|---|---|---|
| **1** | Core FastAPI server, T1 auth + scoped tokens, model registry, basic per-key/model usage tracking, `/health` `/status` `/models` + auth/usage/config endpoints, basic `waiter` CLI, SQLite, OpenAPI docs | **Shipped** (this doc) |
| **2** | Module registry, module upload/sync, server registry, async jobs, event streaming, quota cascade, model routing engine, billing/payment-token support, encrypted secrets beyond Keymaster's existing, Tailscale/local deployment guide | Not started |
| **3** | Production hardening, PostgreSQL backend, complete audit logging, mTLS, advanced rate limiting, remote multi-server deployment, full `waiter` TUI (curses-style `-G`), complete SDK, complete test suite, deployment docs, security audit checklist | Not started |
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
