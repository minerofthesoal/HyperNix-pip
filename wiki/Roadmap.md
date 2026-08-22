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

## 0.72.0 (Next Milestone)

- Advanced multi-agent orchestration & subagent execution protocols
- Enhanced quantization formats & Pascal sm_61 auto-tuning
- and more

---

See [Changelog](Changelog.md) for shipped history.
