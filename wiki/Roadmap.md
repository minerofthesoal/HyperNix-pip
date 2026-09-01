# Roadmap

## 0.71.4b2 (Shipped)

- `hyped+` (`hyped-pro`) Node.js TUI based on OpenClaw, Qwen Code CLI, and Claude Desktop
- Updated Hyped Model Catalog (Kimi K3, Claude Sonnet 4.6/5, Opus 4.8, Haiku 4.5, Fable 5, GPT-4o, GPT-5.6 Terra/Sol, GPT-5.5, DeepSeek R1/V4 Flash, Qwen 3.7 Plus, Gemma 4)
- Unified model directory (`~/.hypernix/models`) & HuggingFace token support
- Brewer 33.6429M parameter architecture preset (`hypernix0x_v2_33m`) & Vision model support
- Slash command auto-completion, price estimator, prompt compaction, auto context compaction, and `hyper-Nix.2` warning banner

## 0.71.4b6 (Shipped)

- `hyped+`/`hyped-pro` real provider dispatch (cloud HTTP calls, local inference, T1 Gatekeeper) via `hypernix.hyped_pro_core` + `hyped_pro_bridge`, replacing the old mocked chat reply
- Qwen and Kimi K3 reclassified as `cloud` with real, documented provider info (DashScope / Moonshot AI)
- Automatic local-model downloads on `/model` selection and `/download`
- `/gui` desktop mode: Qt6 (X11 + Wayland) via PySide6, GTK4 fallback, coded terminal logging on both
- Real `/key` persistence to `~/.hypernix/config.json`
- Dropped OpenClaw-inspired branding

## 0.71.5b1 → b3 — HyperNix T1 API (Shipped)

A controlled HTTP gateway into HyperNix-pip (`hypernix.t1api`), its client
SDK (`hypernix.t1sdk`), and the `waiter` TUI/CLI. Delivered in three
betas; see [T1-API.md](T1-API.md) for the contract and
[Waiter-TUI.md](Waiter-TUI.md) for the client.

- **b1** — core FastAPI server, T1 auth + scoped tokens, the model
  registry, per-key/per-model usage tracking, SQLite, OpenAPI docs, the
  basic `waiter` CLI
- **b2** — module registry and upload/sync, server registry, async jobs,
  event streaming, the quota-cascade routing engine, billing and payment
  tokens, Tailscale/local deployment
- **b3** — production hardening: PostgreSQL, audit logging, mTLS,
  advanced rate limiting, IP allow/blocklists, real remote multi-server
  module transport, the key directory, cost/estimates/forecasts, the
  complete SDK, the full curses TUI, production configuration validation,
  deployment examples, and a security audit checklist

Open, deliberately: module blobs are checksummed but not encrypted at
rest — see [T1-API.md#known-limitation](T1-API.md#known-limitation).

## 0.71.5rc2 — Beta 4 (Shipped)

- `POST /usage/report`: the endpoint that lets a client report the tokens
  it actually spent, so the server's quota cascade advances for clients
  that run inference themselves
- `hyped-pro` T1-key support against a local or remote T1 API server
  (`t1api` vendor, `t1-routed` model, `/t1api` command)
- `hyped-pro` auto-displaying the current public release version
  (`hypernix.system.release`, `/version`)
- `qwen3.8-27b` registry entry
- `hypernix path`: automatic, reversible `PATH` setup for the console
  scripts (`hypernix.system.pathfix`)

## 0.72.0 — T1 v1.0.26.8.0.1 (Shipped)

- The `waiter bridge` LM Studio bridge (localhost, LAN with CORS, or
  Tailscale) and `hyped-pro` over it
- **HyperLink**, the iOS client: chat, images, file upload, code, and
  Hugging Face GGUF downloads from a model page merged with a direct
  file link, on and off the local network
- The six-part T1 version scheme (`api.major.year.month.feature.fix`)

## 0.72.1 — T1 v1.0.26.8.1.0 (Shipped)

- **T2 keys**: access levels, admin passwords, SSPKID, and T2S for
  HyperLink. T1-compatible in both directions
- **noodle** — multi-agent orchestration and subagent execution across
  nine providers, inside `hyped-pro`
- **scriptgen** — the training-script GUI
- **steamroller** — the llama.cpp quantiser, and the expanded quant
  format table
- Pascal sm_61 auto-tuning with a hard FP32 fallback
- `waiter -F`, the web TUI live stream, auth undo/redo, and backups

## 0.72.2 — the installer (Shipped)

- **`install-t1.sh`** — interactive setup and installer for the T1 API:
  bind address, key policy, T2 admin password, connection allowlist,
  rate limits, cost accounting, model source, HyperLink, and the
  `waiter` manager TUI, written out as a matching configuration
- `T1_ACCEPT_T1_KEYS`, the other half of the key-family policy — "T2
  only" is now enforced rather than merely recorded
- `T1_KEYMASTER_DIR`, so a deployment's key store lives with the rest of
  its configuration instead of always in `~/.hypernix/keymaster`

## 0.72.3 — T1 v1.0.2026.8.1.1 (Shipped)

- **Payment connections on a T2 key.** A **T2P** key carries a billing
  binding — a provider's customer and method references, a currency, and
  a spend cap — so a key can be issued to someone who pays for their own
  usage instead of drawing on the operator's budget. Access level and
  billing stay separate concerns: a level-9 key with no binding is still
  free to use, and a level-2 key with one is still level 2. A T2P key is
  never an administrator.

  How the design notes landed:

  - The binding references a provider's customer/method token. Card
    details never reach the server: the store refuses anything shaped
    like a 13–19 digit card number at the boundary, and the binding is
    not carried in the credential — keys land in shell history.
  - Spend caps are checked against the *estimated* cost before any model
    work happens, so an over-cap request is refused rather than billed
    and refunded.
  - Revoking a key releases its binding, and rotating one moves the
    binding — with its recorded spend — to the key that replaced it. Both
    run off Keymaster lifecycle hooks, because revocation happens in the
    security layer, which knows nothing about billing.
  - T2C keys stay reserved, as planned.

- **A server can refuse them.** `T1_BILLING_KEY_POLICY` is `allow`
  (default), `deny` — with a `T1_PAYMENT_URL` to point at, for an
  operator who sells access through their own site — or `separate`,
  which requires the payment key in `X-Payment-Key` so the credential
  that identifies a caller and the one that spends money have separate
  lifetimes. Enforced at authentication.

- **The bootstrap key.** A new server mints itself one admin key on first
  start: usable only from that machine, expired after three days, minted
  once. An empty key store plus admin-only key routes was a closed loop,
  and it is why `waiter hyperlink pair` could not run on a fresh install.

- **`hypernix-t1`** — one dependency-free executable for the whole server
  lifecycle: start, stop, kill, restart, status, logs, create, configure,
  test, key, autostart, remove.

- **HyperLink connects.** The advertised port is the one the request
  arrived on; `ts.net` is an ATS exception domain, since Tailscale's
  100.64.0.0/10 is shared address space and not one of the RFC 1918
  ranges `NSAllowsLocalNetworking` exempts; a missing tailnet now names
  its cause. The app takes a T2S key as well as a pairing code.

- **Consent before the agent runs anything** (`HYPERNIX_TOOL_POLICY`) —
  tool calls are parsed out of the model's own reply, so anything that
  can influence that reply could otherwise run shell commands.

- **CI and the public release gate on a live server.** Two jobs each mint
  their own T2 key, drive a real API and a booted iPhone simulator
  against a fake model, and delete every key they made. Nothing publishes
  until both are green.

## 1.xx.0 — the T2 API

The T2 API itself does not release until 1.xx.0. At that point the T2
API supports T2 and T2S keys only, plus T2C once its key derivation is
resolved. Until then T2 keys are recognised and validated by the T1
API — which is what 0.72.1 shipped — and the T2 API is not exposed.

---

See [Changelog](Changelog.md) for shipped history.
