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

## 0.72.0 (Next Milestone)

- Advanced multi-agent orchestration & subagent execution protocols
- Enhanced quantization formats & Pascal sm_61 auto-tuning
- and more

---

See [Changelog](Changelog.md) for shipped history.
