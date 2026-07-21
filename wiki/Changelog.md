# Changelog

Full per-release notes for `hypernix`. The top-level `wiki/Home.md`
keeps a running "recent highlights" list; this page is the canonical
history. Semver-ish: minor bumps add features, patch bumps are bug
fixes and UX papercuts. Dates are `YYYY-MM-DD` for PyPI-published
releases; in-branch commits between releases are grouped under the
next release header.

## Legend

- ✨ new feature
- 🐛 bug fix
- 🛡️ UX / error-message polish
- 📚 documentation
- 🔧 internal / plumbing



## 0.71.1

✨ **`hnx map`** — a new steampunk schematic TUI. Dials represent parameter
counts (per-layer, scaled by a configurable `acc` value), pipes represent
layer connections, animated steam represents live data flow, and steam
engines represent prompt/dataset input. A dedicated throttle dial sweeps
only while a training run is actually active (via `checkpoints/train.log`
telemetry). Detail level (`poly`: 16/32/64/128) scales dial resolution,
pipe-joint richness, and steam-animation frame count. Reads architecture
from a single `.safetensors` file, a full model folder (auto-discovering
sharded weights, or falling back to an analytical estimate from
`config.json` if no weights are present yet), or runs with just live
`train.log` telemetry and no architecture breakdown. Move the mouse into
the bottom-right corner for a legend (falls back to `?` on terminals
without mouse-motion reporting). Configured via `hnx map config poly|acc|
main use-gpu|main tps|main file model <1|2|3> [-f|-F PATH]`; see
`hnx map --help`.

✨ **`UniversalCooker` / `universal_cooker()` now default to the V5S
optimizer tier** instead of the legacy CPU/CUDA device tiers. Pass
`variant="v5"` / `"v5-plus"` / `"v5s"` (default) / `"legacy"` to choose;
a CUDA device detected as pre-Volta (Pascal, sm_61/6.2) still
auto-selects the matching `Aged*` tier (`Agedcookerv5`,
`ULTRAagedcookerv5`, `Agedcookerv5s`) exactly as the old device-tier
logic did for `InductionCooker`. `variant="legacy"` restores the
pre-0.71.1 selection behavior unchanged.

🐛 **Fixed corrupted borders in `tvtop++` and `cctvtop`.** The Hardware
Vitals / GPU Details panels' bar gauges and history graphs embedded raw
ANSI escape codes directly into Rich `Text` objects; Rich has no way to
know those bytes aren't visible characters, so its cell-width
measurement came out wrong and the panel's right-hand border got drawn
in the wrong column (stray "│" characters floating outside the box).
Fixed by routing that content through `Text.from_ansi` instead, which
parses the escape codes into proper zero-width style spans.

🔧 Internal: `pressure_cooker.py`'s `UniversalCooker` gained a
`_select_legacy` / `_select_v5_family` split; existing tests that
exercised the old default now pass `variant="legacy"` explicitly.



## 0.70.6-3

✨ **all imports are now lazy, speeding the intire package up.**



## 0.70.6

✨ **Pressure Cooker v5S.** Added new oscillation resistant cosin 3d, pressure diffusion low power optimizer `PressureCookerV5S`. It targets a 2.1x speedup over AdamW while using less RAM.
✨ **CLI Optimization.** Drastically improved CLI startup speed by deferring heavy PyTorch imports across all subcommands via an updated fast-path check.
✨ **Automated Release Timeline.** Added a GitHub Action step to automatically generate and append a Mermaid.js horizontal release timeline to the wiki on every public release.
✨ **New CLI Subcommands.** Added `wiki`, `vera`, `scavenger`, and `config` to the main `hnx` interface.
🐛 **Log Tailing Fixes.** Fixed `cctvtop` and `tvtop++` auto-detecting Chromium binary logs by aggressively filtering out `.config`, `.cache`, and non-text files.
🐛 **cctvtop VNC.** Fixed the VNC logic in `cctvtop` to correctly use the `$DISPLAY` variable and spawn `x11vnc` with `-shared`.
📚 **Documentation Updates.** Expanded the "Learn" page on the website and added new documentation and wikis for V5S, Vera, and Scavenger.

## 0.70.5b2

✨ **Net Module.** New `hypernix.net` module for distributed network operations and Tailscale integration. Features: `config`, `auto-setup`, `m-setup`, `connect`, `status`, `m-ip`, `a-il` (auto-connect), `mutli-a-port`, `ex-port`, `s-storage` (distributed storage sharing), `onef-all`, `tail acheck` (automatic Python script checks over Tailscale SSH), and `tail stop`. Accessible via `hnx net <cmd>`. Fully implemented using `subprocess` with `tailscale` and `ssh` commands without relying on mocked stubs.

✨ **Protect Module.** New `hypernix.protect` module for hardware health and monitor protection. Configurable via `hnx prot bind [set|reset] <word>`. Sleeps the monitor via `xset dpms force off` and uses raw terminal input modes to invisibly wait for the wake word (default: "bon") before waking the monitor via `xset dpms force on`.

🐛 **cctvtop Python Rewrite.** Completely rewrote the buggy C++ `cctvtop_ext` wrapper (`cctvtop.py`) into a pure Python 2D interface using `rich.live.Live` with `screen=True`. Fixes terminal scrolling artifacts, duplicate text, and lockups, cleanly tracking and rendering the latest `.log` file in a robust layout.

🛡️ **CLI Default Polish.** Running `hypernix` or `hnx` with no valid subcommand or just invalid flags now cleanly prints the usage menu instead of silently falling back to the legacy `all` (download -> convert -> quantize) pipeline.

## 0.70.5b1

✨ **Brewer Module.** New `hypernix.brewer` module for building fully custom transformer architectures from scratch with no base model. Features: `BrewerConfig` dataclass, `BrewerModel` (RMSNorm + RoPE + GQA + SwiGLU + optional sliding-window), the **hyperNix0x-v2** preset family (Small 9L/ctx=20482, Medium 18L/ctx=40964, Large 36L/ctx=103724), training loop with cosine LR schedule, PyTorch + GGUF export, auto-registration into `KNOWN_MODELS`, and full CLI via `hnx brew`.

✨ **WebUI Overhaul.** Complete rewrite of the web dashboard with in-depth controls for every HyperNix module: Training (PressureCookerV4 params), Brewer (architecture builder + registry), Camouflage (RLHF/RLAF config), Fizzle (model fusion), Download, Quantize (30+ quant types), Tupperware (round planner), Pans/Data Prep, Pressure Cooker (code gen), Abbicus (curriculum config), Hyper-Log (code gen), Upload, Ethanol (GPU controls), Script Builder (now exports Python), Network, and Settings. All panels generate real CLI snippets.

✨ **Autofix Scripts.** New standalone scripts in `scripts/`:
  - `autofix-B` — bash script for CI failures: runs `ruff --fix` + `--unsafe-fixes`, commits with `[autofix-B]` message.
  - `autofix-E` — Python script for public release failures: fixes dup imports, bare `except:`, `from __future__ import annotations` gaps, empty tests, type-checking guards, then `py_compile`-validates every file.

✨ **GitHub Actions — Python 3.14 + macOS M-series.** Updated `ci.yml` to test against Python 3.11/3.12/3.13/3.14 (`allow-prereleases` for 3.14) on `ubuntu-latest`, `ubuntu-22.04`, and `macos-latest` (Apple Silicon). Torch installs routed by OS.

🐛 **tvtop++ Border Artifacts Fixed.** Refactored `run()` to build the Rich `Layout` tree once and only call `.update()` on named slots each tick, eliminating ghost border artifacts from repeated full layout reconstruction.

✨ **tvtop++ All-Process Monitor.** `_get_active_processes` now shows the top 12 system-wide processes by CPU (all processes, not just python/train), adds a STATUS column, and uses a `show_all` toggle.

🐛 **Chromium Log Filter.** `_autodetect_log` in `tv.py` now skips any `.log` file with `chromium` or `chrome` in the name to prevent auto-tailing browser debug logs.

🔧 **CLI `brew` → Brewer.** `hnx brew` now routes to `brewer.cli_main` instead of `instant_pot.brew`.

## 0.70.5a2

✨ **Massive Model Support Expansion.** Added support for GLM 5.2, Nex-N2, more Nemo models, LFM 2.5, SmolLM 3, Z Image, all Whisper models, DeepSeekV4, Kimi K2.5+, more Gemma 4, more Qwen, and Mimo models. Added explicit support for "Model Families" grouping.
✨ **Camouflage (RLHF/RLAF).** Added a new module `hypernix.camouflage` with CLI support via `hnx camo`. Includes AI-assisted modes `-Ai` and full scaffolding for RLHF loops.
✨ **Fizzle Image Models.** `fizzle` now automatically supports Vision/Image models using `AutoImageProcessor` to construct multi-modal architectures seamlessly.
✨ **Hyper-Log TUI.** New premium dashboard (`hyper_log`) providing consistent, styled console logs for training with deep metrics: 5-decimal grad norm, learning rate, epoch progress, GPU telemetry, ETA, and emergency stop features.
✨ **Pressure Cooker V4 Enhancements.** Fleshed out quantization scaling stubs, added Sophia clipping approximation, and enhanced Pascal architectural warnings.
✨ **Spinner Consistency.** Brought the new `spinner` animations across `tvtop++`, `tvtop` (old), and `cctvtop`.
📚 **Documentation Updates.** Expanded GitHub Pages docs to highlight Camouflage and Hyper-Log, plus corresponding Wiki entries.

## 0.70.4b11

✨ **`qa` — Q&A dataset formatter.** New module (`hypernix.qa.QAProcessor`)
turns structured datasets (JSONL, lists of dicts, plain text files) into raw
text strings for causal LM training. Supports `question_answer` mode
(`Question: {q}\nAnswer: {a}`) and `predict_next` concatenation mode.
Optionally integrates with `salt_shaker` and `pepper_shaker` — seasoning is
applied to the raw fields *before* templating so the `Question:` / `Answer:`
keywords are never corrupted. Automatic key fallbacks handle `instruction` /
`completion` / `prompt` / `response` naming conventions.

✨ **`stml` — Short Term Memory Loss context manager.** New module
(`hypernix.stml`) with two components:
- **`calculate_vram_context`** — estimates the maximum safe trained context
  length from VRAM, model size, batch size, and precision. Returns a multiple
  of 128. Accessible via `hypernix stml --vram N --params N` CLI.
- **`STML`** — training-time context manager that enforces an `untrained_max_context`
  hard cap and folds long sequences into the batch dimension using
  `segment_length`-sized chunks `(batch × num_segments, segment_length)`,
  so the model trains on all the data rather than just a truncated slice.
  Accepts an optional `regulator` (`Abbicus` / `TurboAbbicus`) that is applied
  first. Compatible with `old_oven.CodeOven.train()` and `hypernix.train.train()`.

✨ **`TurboAbbicus` — exponential curriculum regulator.** New curriculum
class (`hypernix.abbicus.TurboAbbicus`) configured via `TurboAbbicusConfig`.
- **Exponential growth** — context grows as `base × exp(k × progress)` from
  25% of base to `hard_cap` (vs. linear Abbicus).
- **Configurable `hard_cap`** — absolute maximum context in tokens.
- **Sine-wave oscillation** — when the cap is reached, context oscillates
  around `hard_cap` using `sin(step × frequency) × amplitude`, adjusted by
  host CPU load. GPU utilisation is never used as a change factor.
- **VRAM safeguard** — on each `step()`, VRAM allocation is checked; if it
  exceeds `vram_safety_threshold` (default 90%), context is scaled back 10%.
  It recovers +5% per step when pressure eases.

✨ **`tvtop++` layout, color, and resize fixes.**
- Fixed a layout-tree bug where `layout["body"].split_column()` was called
  *after* a `split_row()`, causing border shifting on every refresh. The
  layout is now rebuilt as a clean static tree (`body → top/bottom → left/right`).
- Fixed hardware panel colors to match original `tvtop` (CPU=green,
  RAM=magenta, GPU=red; was all-default before).
- Fixed `Console` being created with a hardcoded `width=term_width` that
  prevented the dashboard from adapting when the terminal was resized.
- Made graph width and log-tail line width dynamic (scale with `console.width`).
- Log tail now shows 8 lines (was 6).

✨ **`hypernix stml` CLI subcommand.** New `hypernix stml` command exposes
`calculate_vram_context` from the shell with `--vram`, `--params`,
`--batch-size`, `--precision`, `--num-layers`, `--num-heads`, `--head-dim`.

✨ **`hypernix train run` curriculum flags.** Added `--use-abbicus`,
`--use-turbo-abbicus`, `--use-stml`, `--untrained-max-context`,
`--segment-length` to `hypernix train run`.

🔧 **Version bump.** `0.70.4b11`.

📚 **Documentation.** Updated `Abbicus.md` with full TurboAbbicus reference.
New `STML.md` wiki page. Added `qa` section to `Kitchen.md`. Updated `Home.md`.

🛡️ **59 new tests** in `tests/test_v0704b11_features.py` covering all new
modules, config classes, CLI integration, layout correctness, and train/oven
signatures. Tests are version-resilient (check APIs and behaviour, not
internal details).

---

## 0.70.5b2

✨ **Net Module.** New `hypernix.net` module for distributed network operations and Tailscale integration. Features: `config`, `auto-setup`, `m-setup`, `connect`, `status`, `m-ip`, `a-il` (auto-connect), `mutli-a-port`, `ex-port`, `s-storage` (distributed storage sharing), `onef-all`, `tail acheck` (automatic Python script checks over Tailscale SSH), and `tail stop`. Accessible via `hnx net <cmd>`. Fully implemented using `subprocess` with `tailscale` and `ssh` commands without relying on mocked stubs.

✨ **Protect Module.** New `hypernix.protect` module for hardware health and monitor protection. Configurable via `hnx prot bind [set|reset] <word>`. Sleeps the monitor via `xset dpms force off` and uses raw terminal input modes to invisibly wait for the wake word (default: "bon") before waking the monitor via `xset dpms force on`.

🐛 **cctvtop Python Rewrite.** Completely rewrote the buggy C++ `cctvtop_ext` wrapper (`cctvtop.py`) into a pure Python 2D interface using `rich.live.Live` with `screen=True`. Fixes terminal scrolling artifacts, duplicate text, and lockups, cleanly tracking and rendering the latest `.log` file in a robust layout.

🛡️ **CLI Default Polish.** Running `hypernix` or `hnx` with no valid subcommand or just invalid flags now cleanly prints the usage menu instead of silently falling back to the legacy `all` (download -> convert -> quantize) pipeline.

## 0.70.5b1

✨ **`hnx` CLI Shortcut.** Added a new CLI shortcut alias `hnx` which matches all capability of the main `hypernix` command.

✨ **`tvtop++` / `tvtoppp` Live Dashboard.** Created a premium, highly-styled console training monitor featuring rounded boxes, interactive spinning loaders, deep color palettes, a comprehensive **Process Monitor** panel (tracking python/training PIDs, CPU%, memory, and command names), and extended GPU telemetry.

✨ **Resilient Log Parser.** Overhauled the log parser (both for `tvtop` and `tvtop++`) to recursively check and parse irregular format log files (tqdm, JSON, Lightning) for loss (e.g. `loss=`, `loss:`), step count/fractions, learning rate, and throughput.

✨ **Asymptotic Loss Decay Curve.** Replaced simple linear extrapolation of loss predictions with a dampened exponential decay simulation that curves asymptotically, avoiding divergent loss lines.

✨ **Block-Style Hardware History.** Added color-coded Unicode density blocks (`░▒▓█`) representing hardware history for CPU, RAM, and GPU.

🛡️ **14 new tests.** Added tests for `lazy_suzan` (v0.70.3 additional tests) and the updated log parser, block history, loss curve estimations, and `tvtop++` dashboard.

🔧 **Version Bump.** Updated all version files across the package to `0.70.4b1`.

---

## 0.70.3b2

✨ **Web UI ground-up rebuild.** Replaced the monolithic inline HTML dashboard with a modular static frontend (`webui_static/`) served by a threaded HTTP server. Tailscale is now **opt-in only** via `-T` / `--tailscale`; local-only is the default. Fixed the `WebUIServer` constructor mismatch that broke CLI launches.

✨ **`Tupperware` — automated dataset round splitting.** New module splits a chosen dataset into N training rounds with automatic step budgets, per-round optimal LR (scale-aware heuristic), warmup/cooldown ratios, and optional evaluation at the end of each round. Integrates with `new_fridge.plot_round_losses` for multi-round loss charts.

✨ **`StovetopV3CookerPlus` (v0.70.3).** Pascal-safe V3Plus variant with forced sm_61 kernels, adaptive gradient clipping, EMA shadow weights, and optional QAT via `QuantConfig`.

✨ **`HyperNixQuantizer` — quantize facade.** Remade the quantize surface with use-case profiles (`chat`, `code`, `edge`, `quality`, `reference`), batch planning/runs, and a formatted catalog printer. Existing `quantize_gguf` / `CATALOG` API unchanged.

📚 **Wiki expansion.** Dedicated pages for Pressure Cooker v3, Abbicus, Frameworks, Tupperware, and a Roadmap (0.70.4 → 0.70.6 → 0.71.2). Updated Ovens, Fridges, and Home index.

🔧 **`old_fridge` / `old_oven` distributed unwrap.** `unwrap_model()` now peels DDP, FSDP, and DataParallel wrappers; `CodeOven.train` binds optimizers to the unwrapped core.

---

## 0.70.3

✨ **`lazy_suzan` — High-efficiency decentralized multi-GPU linking.** A new module allowing linking of multiple GPUs without a physical NVLink, utilizing fp8/int8/topk gradient compression, overlapped backward-pass communication, and a custom P2P ring topology to bypass standard NCCL bottlenecks.

✨ **`PressureCookerV3` Variants.** Added `StovetopV3Cooker` for safe backwards compatibility on older CUDA 6.1 (Pascal) hardware by disabling fused/foreach kernels. Added `CookerLite` for a heavily optimized CPU-only training loop. Aliased the legacy `peak_lr` parameter to the standard PyTorch `lr` naming convention.

🐛 **`ComputeFramework` Crash Fix.** Fixed string-based instantiation crashes in `instant_pot.py` when initializing `ComputeFramework`, and properly added `backward()` and `step()` bindings to allow seamless hookups with the `lazy_suzan` auto-synchronizer.

---

## 0.70.1

✨ **WebUI Design Rewrite.** Completely rebuilt the `webui.py` frontend using a premium glassmorphism aesthetic. Removed generic styles in favor of vibrant gradients, deep blurred backgrounds, dynamic hover animations, and a sleek dark mode. The UI now looks strictly modern and state-of-the-art.

✨ **`tvtop` Instant Boot & Hardware Telemetry.** `tvtop` now starts up instantly due to lazy loading heavy modules (`abbicus`, `train`) in `hypernix/__init__.py`. Added historical line-graphs (up to 120 ticks) for CPU, RAM, and GPU utilisation directly in the TUI. Added a predictive loss curve extending the current loss trajectory into the future for easy estimation of convergence. Fixed a parsing error with `nvidia-smi` on certain GPU names that broke VRAM stats.

✨ **`workshop` Conversational Streaming.** Rewrote the `ASRToLLMToTTS` pipeline in `workshop.py` to stream generator-based sentences for real-time conversational flow, heavily reducing time-to-first-audio-byte compared to the previous blocking implementation.

✨ **`instant_pot` Modernization.** The one-shot `brew()` trainer now gracefully supports `PressureCookerV3`, automatically regulates context windows with `Abbicus`, and implements multi-device distributions via `ComputeFramework`. Upgraded `old_oven` and `old_fridge` to support seamlessly unwrapping models bound to FSDP/DDP topologies.

🐛 **`PressureCookerV3` LR Floor Fix.** Added a `1e-6` minimum floor to the scheduled learning rate drop to prevent catastrophic model collapse or stalled training when the LR scheduler zeroes out near the end of the steps.

🛡️ **Mixed-Precision Test Suite.** Vastly expanded unit testing in `tests/` specifically benchmarking `PressureCookerV3` memory savings across FP8, FP64, Q5.5, and Q4M variants vs `AdamW`.

---

## 0.70.0

✨ **`abbicus` — Automatic token regulation and curriculum tuning.** New
module that dynamically modifies max sequence length and token
padding/truncation strategies during training based on model size,
context length, dataset complexity, and current global step. Supports
model sizes from 0.5B to 72B with automatic size-based multipliers.
Configurable curriculum steps, dynamic padding, and dataset-type
awareness.

✨ **`compute_framework` — Hardware-agnostic multi-device training.**
Abstracts away CUDA, MPS, CPU, and TPU backends with automatic DDP /
ZeRO wrapping. `ComputeFramework` class handles PyTorch DDP
initialization, device placement, and fallback logic automatically.
Supports distributed training with `local_rank`, `world_size`, `use_ddp`,
`use_fsdp`, and `zero_stage` parameters. Auto-detects available compute
backend and sets up the appropriate device.

✨ **`pressure_cooker` V2 rewrite — Quantization-aware training.** Full
V2 implementation with fp16/bf16/fp64 mixed-precision, automatic dtype
detection, and quantization-aware training (QAT) hooks for Q8/Q6/Q5.5/Q4M.
10 major upgrades: gradient checkpointing integration, adaptive gradient
clipping with per-layer scaling, EMA weight shadowing, distributed
training awareness (DDP/FSDP compatible), dynamic loss scaling with
backoff on overflow, parameter freezing/unfreezing callbacks, learning
rate finder utility, and training metrics streaming to tvtop dashboard.
Device-specific tiers (`StovetopCooker`, `ElectricCooker`,
`InductionCooker`, `ProCooker`) all upgraded to V2 standards.

✨ **`pressure_cooker_v3` — ZeRO-optimized V3 optimizer.** Replaces V2
with full ZeRO-1/2 optimizations, FP8 support, and zero bugs. New
`QuantDtype` enum (FP8/FP16/FP32/FP64/Q8/Q6/Q5_5/Q4M) and `QuantConfig`
dataclass for fine-grained quantization control. `PressureCookerV3`
class with advanced ZeRO stage support, improved memory efficiency, and
heavily tested quantization paths.

✨ **`workshop` — Model frameworks and TTS/ASR pipelines.** New room for
building model frameworks with pre-built templates for TTS, ASR, LLM,
and Vision models. `WorkshopFramework` base class with
`FrameworkConfig` dataclass. Full compatibility with
ray0rf1re/nano-nano collection and 30+ additional architectures including
LiquidAI LFM2.5, MiniCPM5, Gemma 4 family, Qwen3.5 series, Phi-4,
DeepSeek-V2.5, GLM-Edge/MoE, GPT-OSS, Nemotron, Llama-3.2, Mistral-Nemo,
Mixtral-8x22B. Includes `TTSEngine`, `ASREngine`, `ASRToTTS` (direct
speech-to-speech), and `ASRToLLMToTTS` (full conversational pipeline).

🔧 **`tvtop` backwards-compatibility shim.** All tvtop functionality
moved to `hypernix.tv`; this module now re-exports everything so
`import hypernix.tvtop` continues to work. Console script `tvtop` still
registered and points at `hypernix.tv.cli_main`.

📚 **Documentation updates.** Wiki expanded with usage examples for all
new modules. README updated with v0.70.0 feature highlights.

---

## 0.61.4

🖥️ **`tvtop` btop-style multi-panel rewrite.**  Reported on a
mid-screen rendering: the 0.61.1 dashboard "still sucks and only
shows CPU usage" — the single ``hardware`` panel was visually
sparse compared to btop++'s rich CPU / memory / GPU breakdown.

The 0.61.2 dashboard splits the old single ``hardware`` panel
into **four** richer panels in a 2×2 grid above the loss curve +
log:

* **`cpu` panel** — TOTAL utilisation bar at the top, then a
  **per-core grid** in two columns (each cell ``cN <bar>
  NN.N%``), then a 3-row history graph rendered through the
  same multi-row block-bar helper used for the loss curve.
  Per-core sampling: ``psutil.cpu_percent(interval=None,
  percpu=True)`` first, then a Linux-only ``/proc/stat`` per-CPU
  fallback that reads each ``cpuN`` line and computes the
  delta-against-prev sample.
* **`memory` panel** — separate bars for ``USED`` /  ``CACHE``
  / ``FREE`` / ``SWAP`` (each with absolute MiB), plus a 2-row
  history graph.  Sourced from
  ``psutil.virtual_memory()`` + ``psutil.swap_memory()`` first,
  then ``/proc/meminfo`` (``MemTotal`` / ``MemAvailable`` /
  ``Cached`` / ``SwapTotal`` / ``SwapFree``) on Linux.
* **`gpu` panel** — GPU name on top, then ``UTIL`` / ``VRAM``
  (with ``used/total MiB``) / ``TEMP`` (mapped 30-100°C across
  the bar so a hot GPU is visible) / ``PWR`` (against
  ``power.limit`` so 100% bar = at TDP) gauges + 2-row util
  history.  Falls back to a clean ``(no GPU detected)``
  placeholder when ``nvidia-smi`` isn't on PATH.
* **`training` panel** — unchanged from 0.61.1.

The footer now shows ``cores=N · gpu=<name>`` so users can see
at a glance whether the new probes resolved.

🔧 **New probes in `hypernix.tv`**:
* ``_safe_psutil_per_core()`` — per-core list of CPU
  percentages, ``None`` if psutil isn't installed.
* ``_read_proc_stat_per_core()`` — Linux fallback that needs
  two consecutive samples to compute deltas (returns ``None``
  on the first call).
* ``_read_memory_breakdown()`` — dict of
  ``total_mib`` / ``used_mib`` / ``free_mib`` / ``cached_mib``
  / ``swap_used_mib`` / ``swap_total_mib`` / ``percent``.
* ``_query_nvidia_smi_full()`` — extended ``nvidia-smi`` query
  that returns name + temperature + power.draw + power.limit
  alongside the original mem/util tuple.  Cached for 3 s
  alongside the legacy 3-tuple.
* Rolling history deques (``_cpu_history``, ``_ram_history``,
  ``_gpu_util_history``) capped at 120 entries, populated each
  ``latest_frame()``.

🪪 **No btop code was copied.**  The dashboard is original
Python that mimics the same UX patterns (per-core grid, time-
series block graphs, coloured threshold bars).  btop++ is
GPL-3.0 C++ source and reproducing it into hypernix would be a
license/copyright problem — so this is a clean-room
implementation inspired by the same look-and-feel.

🛡️ **9 new regression tests** in ``tests/test_v061_2.py``
covering: ``_read_memory_breakdown`` shape, ``_safe_psutil_per_core``
return type, ``/proc/stat`` per-core delta semantics, per-core
grid label appears in render, memory panel renders breakdown or
fallback, GPU panel renders gauges or no-GPU placeholder, footer
shows core count + GPU label, CPU/RAM/GPU history deques grow
per frame and are capped at 120.

The existing ``test_render_uses_panel_frames`` was updated to
check for the new ``cpu`` / ``memory`` / ``gpu`` panel titles
instead of the old single ``hardware`` title.

---

## 0.61.1

✨ **`hyped` chat CLI.**  New high-quality TUI chat CLI registered
as the ``hyped`` console script.  Two-screen flow:

1. **Configurator** — pick a model from the curated short-list
   organised by family (HyperNix / Nix / Qwen 3.5 / Nano), or
   ``0`` to browse every entry in :data:`KNOWN_MODELS`.  Pick a
   persona from :data:`hypernix.menu.MENU` (or ``0`` for none).
   Tweak sampling defaults (temperature / top_p / top_k /
   max_new_tokens) — press Enter on each to accept.
2. **Chat** — full-screen panel layout: status bar (model /
   persona / sampling), conversation panel with the last 12
   turns wrapped to terminal width, then a typing prompt.
   Streams tokens through :class:`hypernix.bell.Bell` and applies
   :class:`hypernix.flour.Flour` (smart by default; switch via
   ``--flour aggressive|off``).  Slash commands inside the chat:
   ``/quit``, ``/reset``, ``/persona <name>``, ``/save <path>``,
   ``/help``.

Skip the picker with ``hyped --model <short>``; pre-pick a
persona with ``hyped --persona <name>``.  ASCII fallback via
``hyped --ascii`` for non-UTF terminals; ``readline`` is loaded
when available so up-arrow recall + inline editing Just Work.

🚨 **MAJOR ``hyper-Nix.2`` undertrained warning.**  The chat-tuned
``ray0rf1re/hyper-Nix.2`` checkpoint shipped publicly but its
training run was cut short — outputs are often nonsensical,
repetitive, or incoherent.  ``hypernix.utils.warn_hyper_nix_2``
fires a red-bordered ANSI box on stderr the first time any
hyper-Nix.2 alias is touched (``download_model``, ``preheat``,
``hyped --model hyper-nix.2``).  Idempotent per process; suppress
with ``HYPERNIX_SUPPRESS_HYPERNIX2_WARNING=1``.  Also demotes the
hyped configurator badge from ``★`` to ``⚠`` and points users at
``Nix-ai/Nix-2.7a`` / ``Qwen/Qwen2.5-7B-Instruct`` /
``ray0rf1re/hyper-nix.1`` as solid alternatives.

🐛 **Five bug-fix passes** while building hyped:

* **hyped chat loop** now routes through ``Countertop.say()`` with
  a streaming token callback registered on the bell, instead of
  bypassing the countertop's history / trim / clean logic.
* **hyped ASCII picker** uses ``*`` instead of ``★`` for the
  default-model badge so non-UTF terminals don't render ``?``.
* **`ups.UPS` instantiation** is now lazy — IP-geolocation deferred
  to the first ``check()`` call, so ``UPS()`` no-args returns
  instantly instead of blocking on a 5-second HTTPS round-trip.
* **`plasma.calibrate_alarm`** stashes the pristine bound method
  on ``alarm._plasma_original`` and resets to it before
  re-wrapping, so calling ``calibrate_alarm`` twice no longer
  compounds factors.  New ``reset_calibration(alarm)`` undoes
  the wrapper entirely.
* **`tv._sanitise`** now exempts ``\r`` (0x0D) from the
  non-printable strip so Windows CRLF logs don't lose every line
  ending to ``?``.

🛠️ **Utility helpers** added:

* **`hypernix.utils`** (new module): ``healthcheck()`` /
  ``diagnostic_info()`` / ``list_models()`` / ``print_models()`` /
  ``session_dir()`` / ``is_module_available()`` /
  ``has_binary()``.  Diagnostic snapshot includes torch +
  CUDA + every common optional dep + relevant binaries on PATH +
  the ``KNOWN_MODELS`` count.
* **`Menu.find(query)`** — fuzzy persona lookup with exact /
  case-insensitive / substring / prefix matching.  Returns
  ``None`` on ambiguous matches so the caller can disambiguate.
* **`hypernix.injection.thinking()` / `testing()` /
  `system_override()`** — module-level shortcuts so
  ``injection.thinking("hi")`` works without instantiating an
  injector.

🔌 **New console script** in ``pyproject.toml``:
``hyped = "hypernix.hyped:cli_main"``.

🛡️ **37 new tests** in ``tests/test_v061_1.py`` covering every
bug-fix regression (ASCII picker / lazy UPS / plasma compounding /
CRLF / hyped curated short-list), every utility helper, every
fuzzy-find branch in ``Menu.find``, every injection shortcut, and
every code path of the hyper-Nix.2 warning (alias matching /
once-per-process / force re-emit / non-v2 skip / env-var
suppression).

---

## 0.61.0

🐍 **Python 3.14 support.**  ``requires-python`` bumped to
``>=3.10,<3.15``; classifiers gain
``Programming Language :: Python :: 3.14``.  No code changes
needed — every module imports clean on the 3.14 release
candidate.

✨ **Three new modules.**

* **`hypernix.ups`** — uninterruptible-power-supply mode.
  Checks two real-world signals every ``check_interval_seconds``
  (default 5 minutes):
    * **Weather** — open-meteo (free, no API key).  Forces a
      checkpoint when the WMO weather code is in
      :data:`SEVERE_WEATHER_CODES` (heavy rain 65/66/67, heavy
      snow 75, violent rain showers 82, thunderstorm 95/96/99).
    * **Scheduled outage** — pluggable
      ``outage_check_fn(address) -> bool`` callback so a user
      can wire in their utility's "scheduled maintenance" lookup.
  On a panic transition (was-clear → severe / outage), the UPS
  fires the user-supplied ``snapshot_fn`` exactly once, then
  shrinks ``save_every`` by ``cadence_multiplier`` (default 3 →
  "save 3× more often") for as long as the threat persists.
  Auto-locates via ipapi.co IP-geolocation when no
  latitude/longitude is supplied.  ``offline=True`` (or
  ``HYPERNIX_UPS_OFFLINE=1``) skips every HTTP call.

* **`hypernix.injection`** — token / phrase splicers for chat
  scaffolding tokens.  Four variants:
    * ``ThinkingInjector`` — wraps in ``<think>...</think>`` —
      the convention HyperNix-2 / Qwen-3 thinking mode /
      DeepSeek-R1 distilled checkpoints share.
    * ``TestingInjector`` — prepends ``<|test|>`` to short-
      circuit a chat oven into eval mode.
    * ``SystemOverrideInjector`` — appends a one-shot
      ``<|system_override|>...`` without disturbing the
      caller's persistent system prompt.
    * ``CustomInjector`` — generic open / close / mode triple.
  Two scopes: :meth:`inject_messages` for
  ``[{"role", "content"}, ...]`` lists, :meth:`inject_text`
  for already-rendered prompt strings.  Each injection is
  recorded in :attr:`history` for provenance.

* **`hypernix.plasma`** — quick GPU benchmark for sharper
  ETAs.  Runs a 6-step Llama-shape forward + loss + backward
  + AdamW.step loop sized to fit on a laptop GPU (and to
  finish in ~2 s on CPU), returning a :class:`PlasmaResult`
  with ``step_ms`` (median), ``tokens_per_sec``, and a
  ``calibration_factor``.  ``calibrate_alarm(alarm, result)``
  rebinds ``alarm.estimate_step_seconds`` so further calls
  scale by the measured factor — turns a generic
  ``GasAlarm(cpu_preset="i7-7700hq")`` ETA into one that
  reflects what the actual machine can do.  Autocast handled
  on CUDA so fp16 / bf16 configs don't explode on bf16-broken
  cross-entropy paths.

🖥️ **`tvtop` visual rewrite (the headline polish).**
The 0.60 dashboard worked but looked thin and got tripped by
non-training logs.  0.61.0b1 reworks the layout to btop++-style:

* **Multi-panel layout** — rounded-corner framed panels
  (``╭`` / ``╮`` / ``╰`` / ``╯``).  Side-by-side ``hardware``
  panel (CPU / RAM / GPU / VRAM bars + numbers) and
  ``training`` panel (step + progress bar, loss / lr / tput,
  elapsed / ETA).  Below: a full-width ``loss curve`` panel
  with a **5-row block-bar graph** (the new
  :func:`multi_row_graph` helper, quantised to ``height × 8``
  sub-pixels via the ``▁ ▂ ▃ ▄ ▅ ▆ ▇ █`` ladder), then a
  full-width ``recent log`` panel with the last 6 lines.
* **Auto-detect filter** — :func:`_looks_like_training_log`
  reads the first 16 KiB of each candidate log and keeps only
  the ones containing a ``step N/M loss=…`` match.  Ranks
  shaped logs above name-matched logs above arbitrary newest.
  Stops the dashboard from latching onto a Konsole / browser
  / system log.
* **Binary sanitisation** — ``_sanitise()`` replaces every
  byte in ``[0x00–0x08, 0x0B–0x1F, 0x7F–0x9F]`` with ``?``,
  so a binary-laced log can't render as ``�`` garbage.
* **Empty-state** — when no training data has been parsed
  yet, the training panel shows
  ``⏳ waiting for training data…`` instead of a fake
  ``step 0 / loss=—``.
* **Performance** — ``nvidia-smi`` cached for 3 seconds (was
  shelling out every 1-second refresh); cursor-home + per-line
  clear instead of full-screen erase per tick (less flicker);
  frame-diff suppression so the renderer skips writes when
  nothing visible changed.
* **ASCII fallback** — ``--ascii`` swaps every Unicode block
  char to ``# . : - = + *`` so non-UTF terminals stay readable.
* Rounded panel chars + colour gauges (green < 60% < yellow
  < 85% < red) make the panels actually pleasant to watch.

🛡️ **32 new tests** in ``tests/test_v061_b1.py`` covering
every UPS state transition (offline / panic-once-on-edge /
cadence triple / no-panic passthrough / history /
multiplier-floor), every Injection mode (text / messages /
prefix / suffix / wrap / factory / one-shot helper / history),
every Plasma path (returns shape / positive throughput /
summary string / alarm calibration / object-without-method
rejection / alias), and every tv polish bit
(``multi_row_graph`` shape / empty / constant / log
sanitisation / training-log autodetect filter / panel frames /
empty-state header).

Final: 800 tests pass, 1 skipped (matplotlib).

---

## 0.60.0

✨ **Eight new modules — four headline + four multi-tier.**

🖥️ **`hypernix.tv` + `tvtop` CLI** — btop++-style training
dashboard.  Tails any training log under cwd, parses
``step N/M loss=X lr=Y`` lines, and renders a live ANSI-colour
panel: progress bar with percent, loss sparkline (Unicode
block-bar by default; ``--ascii`` for non-UTF terminals),
throughput, elapsed wall time, ETA, CPU% / RAM% / GPU util%
/ VRAM (via ``nvidia-smi``), and the most recent log tail.
Zero hard dependencies — pure stdlib + ANSI.  Console script
``tvtop`` is registered in ``pyproject.toml``.

📦 **`hypernix.compactor`** — zip older checkpoints to save
disk.  ``Compactor(root, keep_recent=3, fmt="zip"|"tar"|"tar.gz")``
walks a snapshot directory, finds ``ckpt-NNNN`` /
``checkpoint-NNNN`` / ``step-NNNN`` directories (and matching
``.pt`` / ``.safetensors`` files), keeps the N most-recent
uncompressed, and rolls the rest into archives.  ``dry_run=True``
plans without touching the disk.

⚡ **`hypernix.ethanol` + `eth` CLI** — bounded GPU overclock.
``Ethanol(level=0..30)`` maps a single integer to bounded core /
memory / power-limit offsets (level 0 = full stock; level 30 =
``MAX_CORE_OFFSET_MHZ`` / ``MAX_MEM_OFFSET_MHZ`` /
``MAX_POWER_LIMIT_PCT``, all well below typical manual-OC
limits).  Refuses to apply without ``confirm=True`` or
``HYPERNIX_ETHANOL_CONFIRM=1``.  Vendor backends:
``nvidia-settings`` (full), ``nvidia-smi`` (power limit only),
``rocm-smi``, ``intel_gpu_frequency``.  Returned
``OverclockResult`` records what was attempted, what succeeded,
and any vendor-tool stderr.

🌑 **`hypernix.outage`** — turn the display off during training.
``with Outage(): train_for_six_hours()`` blanks the panel on
entry and **always** restores it on exit — clean finish,
KeyboardInterrupt, OOM, RuntimeError, doesn't matter.  Backends:
``xset dpms`` (X11), ``wlopm`` (Wayland), ``pmset`` (macOS),
``SendMessageW`` via ``ctypes`` (Windows).  Missing backends
log a note instead of raising.

🍳 **Four new 4-tier modules** (matching the established
multi-tier pattern of ``smoker`` / ``coffee_maker`` /
``espresso_maker`` / ``blender`` / ``toaster`` etc.):

* **`timer`** — countdown / interval / pomodoro helpers, all on
  a monotonic clock.
    * ``KitchenTimer``  — t1.  Plain countdown.
    * ``EggTimer``      — t2.  Countdown + ``on_ring`` callback
      fired exactly once when the timer crosses ``duration``.
    * ``IntervalTimer`` — t3.  Fires every ``interval_seconds``
      via ``should_fire()`` — ideal for throttling log emits /
      checkpoint saves / eval cadence inside a tight training
      loop.
    * ``PomodoroTimer`` — t4.  Alternates between
      ``work_seconds`` / ``rest_seconds`` blocks; ``state``
      returns ``"work" | "rest"``.

* **`thermometer`** — sample CPU / GPU temperatures.
    * ``InstantThermometer``  — t1.  One-shot read.
    * ``ProbeThermometer``    — t2.  Rolling window with
      ``recent_max / recent_mean / recent_min``.
    * ``InfraredThermometer`` — t3.  Per-source peak tracking +
      configurable warn / critical thresholds.
    * ``DigitalThermometer``  — t4.  Logs every reading to a
      JSONL file for post-mortem analysis.
  Sources: ``psutil.sensors_temperatures`` when installed,
  Linux ``/sys/class/thermal/thermal_zone*/temp`` fallback,
  ``nvidia-smi --query-gpu=temperature.gpu`` for the GPU.

* **`dishwasher`** — clean up training-run leftovers.
    * ``HandWash``   — t1.  Logs + ``__pycache__`` only.
    * ``QuickWash``  — t2.  HandWash + ``*.tmp`` / ``*.partial``
      / ``*.lock`` / ``.DS_Store``.
    * ``NormalWash`` — t3.  QuickWash + stale checkpoints
      (delegates discovery to :mod:`hypernix.compactor`).
    * ``HeavyDuty``  — t4.  NormalWash + intermediate fp16
      GGUFs + ``dist`` / ``build`` / ``.pytest_cache`` /
      ``.ruff_cache`` directories; opt-in
      ``purge_hf_cache=True`` also wipes
      ``~/.cache/huggingface``.
  Every tier supports ``dry_run=True`` and reports total bytes
  freed.

* **`strainer`** — drop low-quality dataset rows.
    * ``Colander``    — t1.  Empty / None / whitespace-only.
    * ``FineMesh``    — t2.  Colander + length floor / ceiling.
    * ``NutMilkBag``  — t3.  FineMesh + non-printable-character
      filter.
    * ``Cheesecloth`` — t4.  NutMilkBag + 8-gram Jaccard
      near-duplicate detection (``similarity_threshold=0.85``
      by default).
  Operates on dicts (``record["text"]``) or plain strings; the
  ``key`` arg points the strainer at a non-default field.

🛡️ **44 new tests** in ``tests/test_v060.py`` — checkpoint
discovery + zip / dry-run / unknown-fmt for ``compactor``,
level → offsets math + clamp + plan-without-confirm + CLI
help / invalid-level for ``ethanol``, backend detection +
context-manager round-trip + strict-mode for ``outage``,
sparkline / log-tail / step-loss-lr regex / progress clamp /
render / single-frame run for ``tv``, all four
timer / thermometer / dishwasher / strainer tiers + their
factories.

🔌 **Two new console scripts** registered in ``pyproject.toml``:
``tvtop`` → ``hypernix.tv:cli_main``, ``eth`` → 
``hypernix.ethanol:cli_main``.

---

## 0.52.6

🐛 **More forgiving `smoke_alarm` kwargs.**  Continuation of the
0.52.5 fix-up — same downstream ``chat_hypernix2.py`` script,
same Surface Pro, two more ``TypeError``s after the previous
patch landed::

    TypeError: GasAlarm.__init__() missing 1 required positional
    argument: 'time_budget_seconds'

    TypeError: Alarm.__init__() got an unexpected keyword argument
    'log_every'

The user's call shape is ``smoke_alarm.GasAlarm(cpu_preset="…",
log_every=10, save_every=100, ...)`` — an alarm being used as a
training-config holder.  Two further fixes:

* **`time_budget_seconds` now defaults to ``600.0``.** (Was a
  required positional arg.)  Picking a hardware preset is the
  more interesting signal; the time budget is a knob most
  callers default anyway.  ``RadsAlarm()`` / ``GasAlarm()`` /
  ``ModernAlarm()`` / ``AutoAlarm()`` all instantiate with no
  arguments now.
* **Base `Alarm` accepts `log_every` / `save_every` /
  `eval_every`.**  Training-loop cadence kwargs that real users
  type into config dicts.  RadsAlarm doesn't *use* them, but
  accepting them silently is friendlier than crashing.
  ``AutoAlarm`` also accepts and forwards them through
  ``_common_kwargs`` to the picked tier.

🛡️ **20 new regression tests** in ``tests/test_v052_6.py``:
both repro lines, default ``time_budget_seconds`` on every tier,
``log_every`` / ``save_every`` / ``eval_every`` accepted on every
tier, ``AutoAlarm`` forwarding the cadence knobs, and a realistic
``**cfg`` user-config-dict expansion test.

---

## 0.52.5

🐛 **`smoke_alarm` is forgiving about kwargs.**  Reported by a
downstream ``chat_hypernix2.py`` script running on an i7 7th-gen
Surface Pro:

    TypeError: GasAlarm.__init__() got an unexpected keyword
    argument 'cpu_preset'

…and after the script's own ``except`` fell through to
``RadsAlarm``:

    TypeError: Alarm.__init__() got an unexpected keyword
    argument 'max_steps'

Real users type the kwargs they intuitively expect.  ``cpu_preset``
is the *function name* for resolving CPU presets in
``hypernix.freezer``, so reaching for ``GasAlarm(cpu_preset=…)``
is the natural call.  Same for ``max_steps`` as a hard cap on
``recommended_steps()``.

Fix:

* **Base `Alarm` dataclass** gains three forgiving kwargs:
  ``max_steps: int | None``, ``cpu_preset: str | CPUPreset``,
  ``gpu_preset: str | GPUPreset``.  Every subclass
  (`RadsAlarm` / `GasAlarm` / `ModernAlarm`) inherits them, so
  none of them raise ``TypeError`` anymore on those kwargs.
* **`Alarm.recommended_steps()`** now caps the natural
  recommendation at ``self.max_steps`` when set (a CAP, not a
  target — recommendations below ``max_steps`` are unaffected).
* **`GasAlarm.__post_init__`** resolves a ``cpu_preset`` string
  into ``self.cpu`` via ``hypernix.freezer.cpu_preset``, and a
  ``gpu_preset`` string into ``self.gpu``.  An explicit
  ``cpu=`` / ``gpu=`` object takes precedence.  Pre-built
  ``CPUPreset`` / ``GPUPreset`` objects passed via the alias
  also work.
* **`AutoAlarm`** mirrors the same kwargs and forwards
  ``max_steps`` through ``_common_kwargs`` so the picked tier
  honours the cap.

🌶️ **Generational CPU aliases in `hypernix.freezer.cpu_preset`.**
``"i7_7th_gen"`` (the user's exact string) used to return
``None``.  Added a generation-family map so the natural-feeling
aliases resolve to a representative SKU:

* ``i7_7th_gen`` → ``i7-7700hq``
* ``i7-12th-gen`` → ``i7-12700h``
* ``i9-12th-gen`` → ``i9-12900k``
* ``i9-14th-gen`` → ``i9-14900k``
* ``ultra-7`` / ``core-ultra`` → ``core-ultra-7-155h``
* ``ultra-9`` → ``core-ultra-9-185h``
* …plus full coverage of i5 / i7 / i9 11th – 14th gen, Core
  Ultra Series 1 + 2.

Direct SKU lookups (``"i7-7700hq"``) still take the fast path —
the alias map is only consulted on a primary miss.

🛡️ **27 new regression tests** in ``tests/test_v052_5.py``
covering both lines from the user's repro, ``max_steps`` cap
semantics (no-op when natural rec is below the cap, ignores 0 /
None, hard-caps when smaller), explicit ``cpu_preset`` / 
``gpu_preset`` resolution, explicit-``cpu=`` precedence, every
generational alias, ``AutoAlarm`` forwarding, and kwarg
acceptance on every tier.

---

## 0.52.4

🐛 **`CodeOven.chat` no longer crashes with ``ValueError: too many
dimensions 'str'``.**  Reported on a downstream notebook running
the published wheel: a chat turn died deep inside
``torch.tensor([input_ids], dtype=torch.long, ...)`` because the
tokenizer's ``apply_chat_template`` returned a plain rendered
string instead of token IDs (some tokenizers ignore
``tokenize=True``).  ``list("hello world")`` produced
``['h', 'e', 'l', ...]``, and torch quite reasonably refused to
build a long tensor out of single-character strings.

The fix lives in two places:

* **New :meth:`CodeOven._coerce_token_ids` helper.**  Accepts
  every legal shape ``apply_chat_template`` is allowed to return
  and normalises into a flat ``list[int]``:

    * a plain ``str`` → re-encoded through ``self._encode``,
    * a 1-D / 2-D ``torch.Tensor`` → flattened then ``int(x)``-cast,
    * a ``BatchEncoding``-like object exposing ``.input_ids`` →
      recurses into the input-ids field,
    * ``list[int]`` / ``tuple[int, ...]`` → passthrough,
    * batched ``list[list[int]]`` → take the first batch,
    * ``list[str]`` (the buggy shape) → return ``None`` so the
      caller falls through to the cookbook / plain transcript
      path instead of crashing.

  The ``apply_chat_template`` call is also wrapped in a try /
  except so a tokenizer that simply raises is treated identically
  to a tokenizer that returns garbage — both fall through to the
  cookbook path.

* **Defensive guard in :meth:`CodeOven._run`.**  Coerces ``str``
  / ``torch.Tensor`` / generic-iterable inputs the same way as
  ``_coerce_token_ids`` and raises a clear ``TypeError("_run
  expected list[int] for input_ids; got …")`` if anything still
  slips through, instead of bubbling up the cryptic torch error.

🛡️ **19 new regression tests** in ``tests/test_v051_4.py``:

* The headline bug — chat does not raise ``too many dimensions
  'str'`` when the tokenizer's ``apply_chat_template`` returns a
  string.
* 1-D tensor return / 2-D batched tensor return /
  ``BatchEncoding``-like return / ``list[str]`` fallback.
* ``_coerce_token_ids`` unit coverage for str / list[int] /
  tuple[int] / 1-D Tensor / 2-D Tensor / empty Tensor / empty
  list / batched list / BatchEncoding-like / list[str] /
  unrecognised object.
* ``_run`` defensive guard accepts string and tensor inputs via
  coercion and raises ``TypeError`` with a useful message on a
  truly unrecoverable input.

---

## 0.52.3

🔧 Auto version bump from CI (no code changes vs 0.51.3).

---

## 0.51.3

✨ **`hypernix.quantize` rewrite — full llama.cpp catalog.**

The 6-type alias dict from 0.51.2 grew into a structured 30-entry
``QUANT_CATALOG`` of frozen ``QuantSpec`` dataclasses, one per
distinct llama-quantize target type, with bits-per-weight,
category, size factor (relative to fp16), human-readable notes,
and a ``recommended`` flag for the curated short-list.

* **Floats:** ``F32``, ``F16``, ``BF16``.
* **Legacy quants:** ``Q4_0``, ``Q4_1``, ``Q5_0``, ``Q5_1``,
  ``Q8_0``.
* **K-quants:** ``Q2_K``, ``Q2_K_S``, ``Q3_K_S``, ``Q3_K_M``,
  ``Q3_K_L``, ``Q4_K_S``, ``Q4_K_M``, ``Q5_K_S``, ``Q5_K_M``,
  ``Q6_K``.
* **IQ-quants (newer, importance-matrix friendly):** ``IQ1_S``,
  ``IQ1_M``, ``IQ2_XXS``, ``IQ2_XS``, ``IQ2_S``, ``IQ2_M``,
  ``IQ3_XXS``, ``IQ3_XS``, ``IQ3_S``, ``IQ3_M``, ``IQ4_NL``,
  ``IQ4_XS``.

49 aliases (incl. the original ``q4km`` / ``q5km`` shortcuts and
the dash-form ``q4-k-m``) all resolve through the catalog.  The
old ``QUANT_TYPES`` dict is preserved unchanged at the alias
layer — pre-0.51.3 callers keep working.

New helper API:

* ``quant_recommended()`` — curated short-list (F16, Q8_0,
  Q6_K, Q5_K_M, Q4_K_M).
* ``quant_by_category("float" | "legacy" | "k" | "iq")`` — every
  spec in a category, sorted ascending by bpw.
* ``quant_for_size(target_size_bytes, fp16_size_bytes)`` —
  picks the largest non-float spec that fits the byte budget;
  falls back to the smallest IQ tier if nothing fits.
* ``quant_estimate_size(quant_type, fp16_size_bytes)`` —
  pure-arithmetic size estimate (no llama-quantize required).
* ``quant_resolve_spec(alias)`` — alias → ``QuantSpec`` lookup
  with case-insensitive matching and dash/underscore normalisation.
* ``quant_list_types()`` — sorted list of every canonical name
  in the catalog.

``QuantSpec``, ``QUANT_CATALOG``, and all six helpers are
re-exported at the top level (``hypernix.QuantSpec``,
``hypernix.QUANT_CATALOG``, ``hypernix.quant_recommended``,
etc.).

🛡️ **37 new tests** in ``tests/test_v051_3.py`` covering:

* Catalog completeness (≥ 30 specs, every alias resolves, every
  spec has a positive bpw / known category / non-empty notes).
* ``QuantSpec`` is a frozen dataclass.
* ``recommended()`` short-list contents.
* ``by_category()`` sorted-by-bpw ordering and unknown-category
  empty return.
* ``for_size()`` happy path, tiny-target fallback, zero-fp16
  rejection.
* ``estimate_size()`` math against expected ranges.
* ``resolve_spec()`` canonical / short-alias / dash-alias /
  case-insensitive / unknown-raises paths.
* Backward-compat: every pre-0.51.3 alias still resolves,
  ``quantize_gguf`` still raises ``ValueError`` on unknown
  targets.
* Top-level re-exports present and identity-equal to the
  underlying objects.

📚 **README + wiki refreshed.**  README's quant-aliases table and
the ``hypernix.quantize`` row now describe the new catalog.
``wiki/Quantization.md`` opens with a v0.51.3 callout, the type
table covers every recommended bpw tier, and a new "Catalog
helpers" section shows ``quant_recommended`` /
``quant_by_category`` / ``quant_for_size`` /
``quant_estimate_size`` / ``quant_resolve_spec`` in action.
README also broadens the headline tagline to mention both the
chat-tuned ``ray0rf1re/hyper-Nix.2`` (current default) **and**
the original ``ray0rf1re/hyper-nix.1`` (still fully supported).

---

## 0.51.2.1

🐛 **PyPI logo broken-image fix (carried over from 0.51.1.2).**  The 0.51.1 / 0.51.1.1
README pointed at
``https://raw.githubusercontent.com/minerofthesoal/hypernix-pip/main/assets/logo.png``
but that path returns 404 — the logo file is on the
``claude/pytorch-quantization-package-cJMQp`` working branch
and hasn't been merged to ``main`` yet, so the PyPI project page
showed the alt text + a broken-image placeholder.  Fixed by
pinning the URL to commit ``2d5eb37`` (the upload commit), which
is permanent regardless of branch lifecycle.  PyPI renders the
logo from this release onward.  Once the branch lands on
``main`` we can switch back to the pretty
``main/assets/logo.png`` URL.

---

## 0.51.1.1

🎨 **Logo file landed.**  ``assets/logo.png`` (1408 × 768 RGBA,
670 KB) and the transparent-background variant
``assets/logo1.png`` are now in the repo, so the raw-GitHub
``<img>`` tag at the top of the README renders on the PyPI
project page from this release onward.  Originals also kept
under ``assets/logo/`` for archival.  No code changes vs
0.51.1.

---

## 0.51.1

🐛 **Five bug-fix patches across three review passes** — one
by-hand source-read pass and two hand-driven testing passes,
including a memory-leak / Pascal-GPU / CPU-leak audit.

* **`bell.Bell._iter_from_ids` — stop-marker leak.**  The
  stop-sequence check ran *after* yielding the offending token,
  so consumers wired up via ``iter_chat`` / ``iter_complete``
  saw ``"<|im_end|>"`` (or whatever the stop string was) appear
  in their stream before generation halted.  Fix: check the
  *candidate* decoded text BEFORE yielding the token.

* **`countertop.Countertop._trim` — wipes the just-added user
  turn.**  Aggressive trimming with a small ``max_history_tokens``
  could ``del self.history[:2]`` when ``len(history) == 2``,
  leaving an empty history right before the call to
  ``oven.chat(messages)``.  Fix: cap the drop count at
  ``len(self.history) - 1`` so the most-recent message always
  survives.

* **`cookbook._HYPER_NIX_2` — dict-aliasing footgun.**
  ``_HYPER_NIX_2`` was constructed with
  ``role_prefixes=_CHATML.role_prefixes`` (and same for
  ``role_suffixes``), so the two templates literally shared the
  same dict object.  Mutating ``COOKBOOK.get("chatml")``'s
  prefix table silently corrupted ``hyper-nix.2``.  Fix: copy
  the dicts at construction time.

* **`flour.Flour.process` — crashes on tensor input.**  The
  guard ``if produced_ids:`` raised
  ``RuntimeError: Boolean value of Tensor with more than one
  value is ambiguous`` when callers passed a ``torch.Tensor``.
  Fix: normalise ``produced_ids`` to a plain ``list[int]`` at
  the top of ``process`` and switch the gating to a length
  check; tensors, numpy arrays, and one-shot generators now all
  work.

* **`pressure_cooker.UniversalCooker.select` — breaks Pascal
  (sm_61) GPUs.**  The selector unconditionally returned
  ``ProCooker`` (which inherits ``InductionCooker`` with
  ``fused=True`` + CUDA graphs) on any CUDA device, but fused
  AdamW and ``torch.cuda.CUDAGraph`` both require compute
  capability ≥ 7.0.  A 1080 / 1080 Ti / Titan Xp user calling
  ``universal_cooker(model.parameters())`` would crash with
  ``RuntimeError: fused=True requires CUDA capability >= 7.0``.
  Fix: new ``_is_pre_volta(device)`` helper; the selector now
  detects Pascal and forces ``fused=False`` (with
  ``foreach=_HAS_FOREACH``) on a plain ``InductionCooker``.

🛡️ **14 new regression tests** in ``tests/test_v051_1.py`` —
one per behavioural requirement of the fixes (stop-marker
absence in stream / token-callback / done-callback; trim
preserves freshest user; cookbook dicts are independent and
non-aliasing; flour accepts torch tensors / generators / empty
inputs; ``_is_pre_volta`` returns False on CPU and the Pascal
selector path forces ``fused=False``).

🎨 **Project logo wired in.**  ``assets/logo.png`` is now
referenced from the top of the README (with a raw GitHub URL so
PyPI renders it on the project page) and is shipped in the sdist
via ``MANIFEST.in``.  ``DEFAULT_REPO_ID`` and the ``Homepage``
URL also updated to point at ``ray0rf1re/hyper-Nix.2``.

🔧 **Memory-leak audit (CPU + Pascal-GPU paths).**  Manually
exercised ``deep_fryer.LightFry`` (fry / un_fry over 50 iters,
``torch.Generator`` and ``torch.Tensor`` object counts both
delta-zero), ``Bell.iter_complete`` (20 streaming runs,
delta-zero), ``CodeOven.chat`` (10 turns, delta-zero).  No leaks
introduced by the v0.51.0 chat surface.

Final: 621 tests pass, 1 skipped (matplotlib).

---

## 0.51.0

✨ **Chat-first release.** Five new modules + first-class support
for the new ``ray0rf1re/hyper-Nix.2`` chat checkpoint.

* **`hypernix.cookbook` — chat-template registry.**
  Different model families use wildly different prompt formats
  (ChatML, Llama 3 turn tags, Alpaca, Vicuna, plain ``role:
  content``) and getting one wrong silently makes a chat model
  behave like a base model.  ``cookbook`` ships every common
  template as a dataclass and resolves the right one from a
  short name or HF repo id::

      from hypernix.cookbook import COOKBOOK, for_model

      tmpl = for_model("ray0rf1re/hyper-Nix.2")  # picks "hyper-nix.2"
      prompt = tmpl.apply(messages, add_generation_prompt=True)

  Built-in templates: ``chatml``, ``hyper-nix.2`` (ChatML +
  HyperNix-flavoured default system prompt), ``llama3``,
  ``llama2``, ``alpaca``, ``vicuna``, ``plain``.  Wired into
  ``CodeOven._format_chat`` as the layer-2 fallback (after
  ``tokenizer.apply_chat_template`` if present, before the plain
  ``role: content`` last-resort) so a freshly-downloaded
  hyper-Nix.2 snapshot Just Works for chat without any extra
  configuration.

* **`hypernix.countertop` — multi-turn chat session.**
  Persistent workspace bound to an oven::

      from hypernix.old_oven import preheat
      from hypernix.countertop import Countertop

      oven = preheat("hyper-nix.2")
      chat = Countertop(oven, system="You are a helpful chef.")
      print(chat.say("How do I dice an onion?"))
      print(chat.say("And a shallot?"))
      chat.save("session.json")

  Auto-resolves the chat template from ``oven.repo_id``,
  optionally streams through a :class:`Bell`, optionally cleans
  replies through a :class:`Flour`, trims oldest turns when the
  rendered transcript exceeds ``max_history_tokens``, and
  round-trips to JSON for resumable sessions.

* **`hypernix.menu` — system-prompt presets.**
  Named registry of personas: ``default`` / ``concise`` /
  ``code-helper`` / ``judge`` / ``creative`` / ``chef`` /
  ``hyper-nix``.  Pairs with the ``persona=`` kwarg on
  ``countertop()`` so you can say
  ``countertop(oven, persona="judge")`` instead of pasting the
  judge prompt by hand.  Persists with ``Menu.save / Menu.load``.

* **`hypernix.bell` — streaming-token callback.**
  Wraps any oven exposing ``model`` + ``_decode`` + ``_format_chat``
  so generation streams a token at a time::

      bell = Bell()
      bell.on_token(lambda tok, idx: print(tok, end="", flush=True))
      bell.on_done(lambda full: print(f"\\n[done, {len(full)} chars]"))
      bell.stream_chat(oven, messages, max_new_tokens=128)

  Or pull tokens out of the iterator yourself::

      for tok in bell.iter_chat(oven, messages):
          ...

  ``stdout_bell()`` and ``file_bell(path)`` are ready-made
  variants.  Bells accept a ``flour=`` so live logits processing
  applies during streaming, not just at the end.

* **`hypernix.flour` — chat-quality logits processor.**
  *The reason hypernix's chat surface is "better than raw
  transformers for chatting".*  Bundles every chat-quality
  heuristic you'd otherwise wire by hand on top of vanilla
  transformers:
    * **repetition penalty** (OpenAI-style multiplicative),
    * **frequency penalty** (linear in count),
    * **presence penalty** (linear, once per unique token),
    * **no-repeat n-gram** blocking,
    * **bad-word / phrase** suppression,
    * **role-leak suppression** — strips
      ``<|im_start|>user`` / ``[INST]`` / ``user:`` tokens the
      assistant would otherwise hallucinate, and cuts the reply
      at any half-emitted next-turn marker,
    * **stop-sequence detection** on **decoded text** rather than
      raw token ids — so ``"<|im_end|>"`` works even when the
      tokenizer splits it into 3 BPE pieces.
  ``Flour.smart_default(template="hyper-nix.2")`` applies all of
  the above with values tuned for chat.  ``Flour.aggressive()``
  cranks up the penalties for models that loop a lot.
  ``Flour.off()`` is a no-op.

🌶️ **First-class support for ``ray0rf1re/hyper-Nix.2``.**

* New ``KNOWN_MODELS`` entry plus the aliases ``hyper-nix.2`` /
  ``hyper-nix2`` / ``hypernix2`` / ``hyper-nix`` / ``hypernix``,
  all routing to ``ray0rf1re/hyper-Nix.2``.  The chat-aware
  ``hyper-nix`` / ``hypernix`` short names now resolve to v2
  (was v1 in 0.50).
* ``DEFAULT_REPO_ID`` updated to ``ray0rf1re/hyper-Nix.2`` so
  ``preheat()`` with no args downloads the chat-tuned model.
* New ``ARCH_PRESETS["hypernix2"]`` / ``["hyper-nix.2"]`` for
  fresh-init from-scratch chat models with the same Llama-shape
  config as v1.
* ``CodeOven.repo_id`` is now persisted on the oven so
  ``_format_chat`` can resolve the cookbook template
  automatically — no more ``role: content`` fallback for v2.

🛡️ **56 new tests** in ``tests/test_v051.py``: cookbook templates
(ChatML / Llama 2/3 / Alpaca / Vicuna / plain + ``for_model``
resolver), menu CRUD + persistence, bell streaming with a stub
oven (no real weights needed), countertop session lifecycle
(say / reset / trim / save / load / persona / flour-cleanup),
flour logits processor (repetition penalty math, no-repeat n-gram
ban, role-leak detection, decoded-text stop-match,
``clean_reply`` after generation), and hyper-Nix.2 wiring (alias
table, default repo id, oven ``repo_id`` plumbing).

Final: 607 tests pass, 1 skipped (matplotlib).

---

## 0.50.0

✨ **Four new kitchen modules.**

* **`hypernix.whisk` — checkpoint averaging.**
  Three modes for blending N saved snapshots into one set of
  weights, all working on plain ``dict[str, Tensor]``:
    * ``swa_average(items)`` — uniform Stochastic Weight Average
      (mean across all N).
    * ``ema(items, decay=0.99)`` — exponential moving average;
      later inputs weighted ``decay ** (N-1-i)``.
    * ``geometric_mean(items)`` — element-wise geometric mean
      (clamped at ``eps`` for non-positives).
  Inputs may be in-memory state dicts **or** paths to ``.pt`` /
  ``.safetensors``.  Mismatched keys are intersected with a
  warning unless ``strict=True``.  Integer tensors are taken from
  the first checkpoint (averaging them is meaningless).
  ``whisk(items, mode="swa"|"ema"|"geometric-mean")`` is the
  one-shot factory; ``whisk_to_snapshot(items, out_dir, ...)``
  whisks **and** writes a full HF-style snapshot directory in one
  call (best-effort config recovery from a sibling
  ``config.json``).

* **`hypernix.cutting_board` — train / val / test splitting.**
    * ``CuttingBoard(train_ratio, val_ratio, test_ratio,
      seed, shuffle)`` — deterministic random split.  Ratios are
      renormalised if they don't sum to 1.0; ``test_ratio=0`` is
      allowed (you'll get train + val and an empty test slice).
      ``.slice(source)`` returns ``{"train": [...], "val": [...],
      "test": [...]}`` from a corpus path or any iterable of
      strings; ``.slice_to_files(out_dir, suffix=".txt")`` writes
      each slice to its own file.
    * ``StratifiedBoard(label_key="label")`` — stratified split
      that preserves the class distribution from labelled records
      (each unique label is shuffled and split independently,
      then per-class slices are concatenated and shuffled once
      more so the output isn't grouped by class).
    * Convenience: ``cutting_board(source, train=…, val=…,
      test=…, seed=…)`` returns the slice dict directly when
      ``source`` is given, else returns a configured board.

* **`hypernix.apron` — RNG-state guard.**
  An apron protects what's underneath while you cook.  Captures
  every random-number source hypernix or your script might touch
  (Python ``random``, NumPy if installed, PyTorch CPU, every
  CUDA device's RNG) and restores it on exit.  Two ways to use
  it:

      with apron(seed=0):
          # everything inside is deterministic; nothing leaks out.
          random.shuffle(my_list)
          torch.randn(10)

      a = Apron.snapshot(seed=0)
      ...
      a.restore()

  Use it any time a step in your pipeline wants to perturb the
  global RNG (e.g. an evaluator that uses ``torch.randn`` for
  sampling) without leaking the perturbation back to the caller.

* **`hypernix.recipe_book` — named-config registry.**
  Save 12-key brew recipes once, refer to them by name forever.
  ``RecipeBook.add(name, recipe)`` / ``get(name)`` /
  ``remove(name)`` / ``save(path)`` / ``load(path)``.
  ``cook(name, **overrides)`` looks up, applies overrides on top,
  and dispatches by ``kind`` field:
    * ``"instant_pot"`` → ``hypernix.instant_pot.brew``
    * ``"cold_brew"`` → ``hypernix.coffee_maker.cold_brew(...).brew()``
    * ``"espresso"`` → ``hypernix.espresso_maker.espresso_maker(...).pull(prompts)``
  ``RecipeBook.from_builtins()`` ships a handful of ready-to-use
  recipes (``evaluator-quick``, ``ftune-pascal``,
  ``nightly-coldbrew``, ``espresso-eval``).

🐛 **Three bug-fix passes across the codebase.**

Pass 1 — runtime correctness:

* `pressure_cooker._adamw_multitensor`: the private
  ``torch.optim._functional.adamw`` API is **not** stable across
  torch 1.13 → 2.x.  Now wrapped in a try/except (both
  ``ImportError`` on the import and ``TypeError`` at call time),
  with a graceful fall-through to a hand-written
  ``_adamw_scalar_for(params, group)`` so the optimizer keeps
  working on torch versions where the private name was renamed
  or had its signature changed.
* `deep_fryer.LightFry` / `HeavyFry`: replaced the global
  ``torch.manual_seed`` mutation with a per-parameter
  ``torch.Generator(device=flat.device)`` keyed on
  ``self.seed + sum(map(ord, pname))``.  Two consecutive fries
  with the same seed now produce identical noise **without** also
  perturbing the user's training RNG state.
* `food_processor.SliceBlade`: previously accepted any
  ``overlap_chars`` and produced a zero-length step (infinite
  loop) when ``overlap_chars >= slice_chars``.  Now raises
  ``ValueError`` at chunk time with a clear message.
* `industrial_range._parse_pairwise`: the pairwise parser used
  to insist that "tie/tied/equal" be the first character of the
  judge response.  Real judges write things like "Tied — both
  responses are correct" or "Equal quality" — those now correctly
  return ``"T"``.

Pass 2 — UX / error-message clarity:

* `instant_pot.brew`: when ``recipe["dataset"]`` doesn't exist on
  disk, the old behaviour was a confusing ``KeyError`` deep inside
  ``train`` after a 30-second model download.  Now fast-fails with
  ``FileNotFoundError("instant_pot.brew: dataset … does not
  exist")`` before the download starts.
* `microwave._preheat`: a string repo id like ``"nix2.5"`` that
  happened to coincide with an existing local directory was being
  treated as a path even when the directory didn't contain a
  ``config.json``.  The path branch now also requires
  ``config.json`` before short-circuiting the Hub download.
* `cake_pan` `step_timeout` handler: the SIGALRM handler used to
  raise ``BakeOff`` directly without first restoring pristine
  state, leaving the model with a half-applied gradient step.
  Now calls ``self.roll_back()`` before raising.

Pass 3 — discovered during smoke-testing the new modules:

* `apron.Apron.snapshot`: the previous implementation seeded the
  RNGs **before** capturing state, so the ``with apron(seed=42):``
  context-manager exit restored to the seeded state instead of
  the caller's pre-call state.  Now snapshots first, then
  optionally seeds, so exit truly returns the caller to whatever
  they were doing before.

🛡️ **36 new tests** in ``tests/test_v050.py`` covering all four
new modules plus regressions for every bug fix above.

---

## 0.49.0

✨ **`hypernix.lunchbox` — consistent-schema dataset packager.**
Reported: the Hub dataset viewer on a hypernix-built
``ray0rf1re/eval`` dataset crashed with

  Error code: StreamingRowsError
  Exception:  CastError
  Message:    Couldn't cast … because column names don't match

The actual column layout (11 cols incl. ``latency_s``,
``keyword_score``, ``pipeline_meta``) didn't match the
``huggingface`` metadata blob embedded inside the Parquet shards
(only 4 cols).  That happens when shards written at different
schema versions get concatenated.  ``Lunchbox`` makes that
impossible by construction:

  * ``add(**fields)`` collects plain dicts.
  * ``normalize()`` fills every missing cell with ``None``.
  * ``validate()`` rejects mixed non-None types per column
    (str+float in the same column is a Parquet write error).
  * ``pack(path)`` routes through
    ``datasets.Dataset.from_list(...).to_parquet(...)`` so the
    embedded ``huggingface`` metadata is always in sync with the
    actual column set.
  * ``push_to_hub(repo_id)`` does the same for direct uploads.
  * ``Lunchbox.for_eval()`` pre-loads the recommended eval-dataset
    schema (``EVAL_SCHEMA``: id / category / difficulty / tier /
    prompt / reference / model_response / keyword_score /
    latency_s / variant / pipeline_meta).
  * ``pack_jsonl(path)`` writes the same normalised rows as JSON
    Lines — no pyarrow / datasets install required.

``datasets`` is a **lazy** dependency: the first pack / push call
routes through :func:`hypernix.deps.ensure`, respecting
``HYPERNIX_AUTO_INSTALL=0``.

🧪 **+31 new coverage tests** (`tests/test_coverage_beef.py`)
touching gaps in the existing per-module suites: lunchbox
edge cases (empty box, 10 000-row normalise, unicode,
duplicate rows, mixed-types rejection, push-URL shape),
pressure_cooker (amsgrad wiring, closure-form step, foreach
state persistence, repr text), deep_fryer (frozen-param
handling, multi-cycle save/restore, HeavyFry fries frozen
weights), cake_pan (CPU memory-guard no-op, oven-all-bad
zero count, step_count monotonicity), freezer presets (every
CPU has AVX, every GPU has positive bandwidth, lookup-key
normalisation), shakers (determinism, rate=0 identity, empty-
line passthrough), smoke_alarm (time_hours math, save_every=0
silence, unknown-preset error content), plus an end-to-end
evaluator→Lunchbox→JSONL→Table round trip.

Full suite 515 passed, 1 skipped (matplotlib).

---

## 0.48.0

✨ **`pressure_cooker` rewrite — 4 device-tuned tiers + universal
selector + 5 new knobs.**  The base :class:`PressureCooker` keeps
the v0.47 API exactly (warmup / plateau / cosine cooldown + optional
lookahead); on top of it ship four specialised classes and a
selector:

* **`StovetopCooker`** (CPU tier 1) — minimum-memory path:
  ``foreach=False``, ``fused=False``, no AMP.  Use on RAM-
  constrained boxes and old Intel Macs.
* **`ElectricCooker`** (CPU tier 2) — ``foreach=True`` multi-tensor
  path (torch ≥ 1.12) for fast CPU updates when you have the RAM.
* **`InductionCooker`** (GPU tier 1) — ``foreach=True`` +
  ``fused=True`` AdamW kernel on torch ≥ 2.0 + first-class
  ``torch.cuda.amp.GradScaler`` integration.  Pass
  ``grad_scaler=torch.cuda.amp.GradScaler()`` and the cooker
  unscales, inf-skips, and advances the scaler automatically.
* **`ProCooker`** (GPU tier 2) — InductionCooker plus optional
  CUDA-graph capture via ``warmup_graph(step_fn)`` /
  ``replay_graph()`` for a material speedup on fixed-shape steps.

✨ **`universal_cooker(params, prefer_speed=True)`** — probes the
first parameter's device and returns `ElectricCooker` on CPU (or
`StovetopCooker` with `prefer_speed=False`), `ProCooker` on CUDA
(or `InductionCooker`).

✨ **New base-class knobs (opt-in, all backward-compatible):**

* ``grad_scaler=`` — unscales, skips on inf, advances the scaler.
* ``grad_accum_steps=N`` — only the N-th ``step()`` runs the
  optimizer; earlier calls just bump the counter.
* ``foreach=True | False | None`` — selects the multi-tensor path.
* ``fused=True | False | None`` — selects the fused CUDA kernel
  when torch supports it (torch ≥ 2.0, all params on the same
  CUDA device).
* ``amsgrad=`` — forwarded to the inner AdamW.

✨ **Factory convenience:** ``pressure_cooker(params, tier="...")``
accepts any of ``"pressure-cooker"`` / ``"stovetop"`` / ``"electric"``
/ ``"induction"`` / ``"pro"``.  Unknown tiers raise
``ValueError`` with the full list.

🔧 `describe()` method on the base class returns a dict of the
active knobs for logging / provenance.

Tests (`tests/test_pressure_cooker_v048.py`, 19 new):

* v0.47 signature + LR schedule + phase labels unchanged (backward
  compat).
* Every tier's defaults (`foreach`, `fused`, `grad_scaler`) verified.
* Universal selector picks Electric on CPU (fast) or Stovetop
  (safe).
* Grad-accumulation: N-1 no-op steps then one real update.
* GradScaler: skip-on-inf path *and* update-on-finite path via a
  fake scaler so we don't need CUDA to test.
* Scalar vs. foreach inner path produce the same weight update to
  within fp rounding.
* Factory tier lookup + error paths.
* Lookahead slow-weight population survives the rewrite.

Full suite 469 passed, 1 skipped (matplotlib).

Docs: README subsystem table row rewritten to list all five tiers,
wiki/Home.md version history picks up 0.48.0 + backfills 0.47.1.

---

## 0.47.0

✨ **`deep_fryer`** — 2-tier model-weight perturbation.  `LightFry`
(t1): 2% of elements, 0.1× param-std Gaussian noise — use as a
regulariser between epochs.  `HeavyFry` (t2): 30% of elements,
0.5× noise, plus configurable zero-rate for sparse destruction —
use to generate deliberately-bad-model negatives for training a
judge, or for robustness testing.  Both are in-place and reversible
via `save_pristine()` / `un_fry()`.

✨ **`cake_pan`** — hybrid CPU + GPU training guard.  Wraps each
step in `bake(fn)` which catches NaN / Inf in the loss (and
optionally gradients), enforces a wall-time watchdog via SIGALRM,
monitors GPU memory and offloads matching modules when pressure
passes `free_gb_trip`, and rolls back to the last pristine state
on trouble — raising `BakeOff(reason, step)` for the caller.
`CakePan.oven(batches, step_fn)` is the fire-and-forget loop
wrapper with automatic retry + skip.

✨ **CPU preset expansion — now 48 total** (was 16, **×3**).
Adds 7th-gen i5 (7200U, 7300HQ, 7400, 7600K), i9 (7900X, 7980XE);
11th-gen i5 (11400, 11600K, 11320H), i9 (11900K); 12th-gen i5
(12400, 12500, 12600K), i9 (12900K, 12900HX); 13th-gen i5 (13400,
13500, 13600K), i9 (13900K, 13900HX); 14th-gen i5 (14400, 14500,
14600K), i9 (14900K, 14900KS, 14900HX); Core Ultra 5 Series 1
(125H, 135H, 228V), Series 2 (225K, 235K); Core Ultra 9 Series 1
(185H).

✨ **GPU preset expansion — now 71 total** (was 20, **×3.5**).
Adds the rest of GTX 10 (1050, 1050 Ti, 1060, 1070, 1070 Ti), GTX
16 (1650, 1650 Super, 1660, 1660 Super), RTX 20 (2060, 2060 Super,
2070, 2070 Super), full RTX 30 (3050, 3060, 3060 Ti, 3070, 3070
Ti, 3080, 3090, 3090 Ti), full RTX 40 (4060, 4060 Ti 8/16GB, 4070,
4070 Ti, 4080, 4090), full Blackwell consumer RTX 50 (5070, 5070
Ti, 5080, 5090).  **Apple Silicon** via MPS: M1 / M1 Pro / M1 Max
/ M1 Ultra, M2 / M2 Pro / M2 Max, M3 / M3 Pro / M3 Max, M4 / M4
Pro / M4 Max.  **AMD**: Radeon RX 6800 XT / 6900 XT / 7900 XT /
7900 XTX, Instinct MI250X / MI300X.  Non-CUDA devices (Apple,
AMD) use the `(0, 0)` sentinel for `compute_capability`.

Tests (`tests/test_v047_deep_fryer_cake_pan_presets.py`, 76 tests):
every fryer tier + pattern filter + unknown-tier error; cake_pan
loss/grad NaN detection, snapshot writes, oven retry counting,
pristine rollback; every new CPU preset spec + preset count bound;
every new GPU preset vram + count bound; compute-capability
sentinels for Apple + AMD.  **Full suite 447 passed**, 1 skipped
(matplotlib).

---

## 0.46.1

🛡️ **`nix` short-name fallback chain.**
`KNOWN_MODELS["nix"]` now points at `Nix-ai/Nix-2.7a` (was
`ray0rf1re/Nix2.5`).  `download_model("nix")` consults a new
`FALLBACK_CHAINS` registry and tries in order:
`Nix-ai/Nix-2.7a` → `Nix-ai/Nix2.6-mm` → `ray0rf1re/Nix2.5`,
falling through only when an earlier candidate 404s / is gated /
hits a network error.  Explicit `org/repo` ids bypass the chain.
Six regression tests in `tests/test_nix_fallback.py` cover the
happy path, fallthrough, exhaustion, and explicit-repo bypass.

---

## 0.46.0

✨ **`salt_shaker`** — 3-tier gentle data augmentation.

- `FromTheBag` (t1): per-character substitution at `rate`, preserves
  line length.
- `HandCrusher` (t2): adjacent-token swaps at `rate`.
- `PoshSaltDish` (t3): independent drop / duplicate / swap rates
  with word-level granularity.

All three share a `Shaker` base, a deterministic `seed`, and plug
into `sink.Sink.pour(...)` like the pans.

✨ **`pepper_shaker`** — 3-tier sharp perturbations.

- `SmallShaker` (t1): random token masking with configurable
  `mask_token` (default `[MASK]`).
- `Dish` (t2): typo injection (drop / duplicate an internal char);
  preserves first + last character so words stay recognisable.
- `TallHandmade` (t3): negation injection; prepends `negator`
  (default `"NOT"`) at `rate`.

✨ **`torch_compat`** — portability shim for **old Intel Macs with
torch 1.13**.  Provides version-gated fallbacks for
`torch.nn.RMSNorm` (needs ≥ 2.4) and
`torch.nn.functional.scaled_dot_product_attention` (needs ≥ 2.0).
`HyperNixModel` + `NanoNanoModel` now route through the shim, so
identical outputs on modern and legacy torch.

✨ **`[legacy-torch]` extra** — companion dep pins that co-install
with torch 1.13: `numpy<2`, `safetensors>=0.3.1`,
`huggingface-hub>=0.16`, `tqdm>=4.64`, `sentencepiece>=0.1.99`.
Does **not** relax the main torch pin; you must install torch 1.13
first yourself.  See `scripts/install_macos_legacy.sh`.

🔧 **`scripts/install_macos_legacy.sh`** — one-shot installer that
pins torch 1.13.1 CPU, installs hypernix with `--no-deps`, then
pulls the legacy-torch extras, and smoke-tests
`torch_compat.describe()`.

📚 New `wiki/macOS-legacy.md` documents what works, what doesn't,
and how to size training on old Intel Macs (`OldFreezer` + a
`GasAlarm(preset="i7-7660u")`-style budget).

---

## 0.45.3

🛡️ **`smoke_alarm.GasAlarm` accepts `preset=`.** One-string shortcut
that resolves against `GPU_PRESETS` first, then `CPU_PRESETS`. Works
on the class (`GasAlarm(..., preset="i7-7700hq")`), on the factory
(`gas_alarm(..., preset="h100")`), and on the selector
(`auto_alarm(..., preset="rtx-3080-ti")`). Unknown names raise
`ValueError` with the full list of valid presets.

🛡️ Explicit `cpu=` / `gpu=` instances still win over a conflicting
`preset=` hint — no silent overwrite.

🔧 Shared `_resolve_preset` helper in `smoke_alarm.py`.

## 0.45.2

🐛 **Every pan accepts `context_length=` and `max_chars=`.** Reported:
`FryingPan(context_length=CONTEXT_LEN)` raised a bare `TypeError`.
Both are now keyword-only fields on the `Pan` base class; when set,
lines are truncated to fit. `context_length` is treated as
`max_chars = context_length * 4` (English-BPE heuristic); the direct
`max_chars=` wins when both are set. For precise chunking by tokens
use `hypernix.food_processor` instead.

## 0.45.1

🐛 **Pan positional-argument fix.** `Pan` inherited `name: str` as a
dataclass field, so `Skillet(src, "instruct")` silently set
`name="instruct"` and left `mode="chat"`. Fix: `name` is now a
`typing.ClassVar` on every pan — still the pan's label, no longer
part of `__init__`. `GrillPan._seen` (internal dedupe state) marked
`init=False`.

🛡️ `pick_pan` error messages now list valid tiers / valid kwargs
instead of raising `KeyError` or cryptic `TypeError`.

## 0.45.0

✨ **Espresso, blender, toaster, food_processor, smoker** — five new
appliances, each 4 tiers. Shared interface per module.

✨ **+3 microwave tiers** — now `defrost` (preheat-only) / `low_zap`
(deterministic one-liner) / `zap` (existing) / `high_zap`
(long-temp draft) / `chat_zap` (existing). Plus `reheat(oven,
prior_output)` for continuation without rebuild.

✨ **+2 coffee_maker tiers and one new type.**
`FrenchPressMaker` (batch), `PercolatorMaker` (cyclic with optional
convergence), and a new `ColdBrewMaker` (long single brew with
mandatory JSON checkpoints, resumes cleanly after a crash).

✨ **CLI `hypernix brew recipe.json`** — runs `instant_pot.brew`
from a JSON recipe. Supports `--set KEY=VALUE` overrides with JSON
literals.

📚 `wiki/Kitchen.md` gets full sections for every new appliance.

## 0.44.0

✨ **Kitchen modules + pressure_cooker optimizer.** Seven new
top-level modules (pans, microwave, table, sink, instant_pot,
coffee_maker, pressure_cooker) covering preprocessing, throwaway
inference, log inspection, file output, end-to-end pipelines,
scheduled repetition, and a custom optimizer.

✨ `pressure_cooker` — `torch.optim.Optimizer` subclass: AdamW +
three-phase LR schedule (linear warmup → plateau → cosine cooldown)
+ Zhang-et-al-2019 Lookahead "pressure seal". No separate scheduler
object; the LR lives inside the optimizer.

📚 README gains a **"Who this is actually for"** section framing the
package around the solo-GPU / consumer-card / QLoRA-to-Hub workflow,
with an explicit disclaimer that `train()` is a smoke-tester, not a
production trainer. New `wiki/Kitchen.md`.

## 0.43.0

✨ **`smoke_alarm`** — four-tier training-step planner + mid-run
monitor. `RadsAlarm` (constants, lightest), `GasAlarm` (CPU/GPU
presets), `ModernAlarm` (warmup-measured), `AutoAlarm` (selector).

✨ **16 CPU presets** (`hypernix.freezer.CPU_PRESETS`): i7 7th gen
(7660U / 7700HQ / 7700K), 11th–14th gen K/H/HX, Core Ultra Series 1
(Meteor / Lunar Lake), Series 2 (Arrow Lake, AVX10).

✨ **20 GPU presets** (`hypernix.freezer.GPU_PRESETS`): Hopper
(H100/H200), Ampere workstation (A4500–A6000), RTX PRO Ada +
Blackwell, RTX 4070 Ti Super / 4080 Super, RTX 3080 Ti, Turing
consumer (1660 Ti, 2080, 2080 Super, 2080 Ti), Pascal (1080, 1080 Ti).

📚 New `wiki/Alarms.md` with both preset tables.

## 0.42.0

✨ **`new_range` / `old_range` / `industrial_range`** — three
sophistication tiers of labeling rubrics that drop into
`mediocre_fridge.collect_responses_from(label_rule=...)`.

- `new_range` — zero-dep first-fail rubric (is_empty, is_refusal,
  math_lacks_digit, is_repetition).
- `old_range` — weighted-mean scored rubric with `None` = "no
  opinion", any-rule-at-0 short-circuits to BAD, references / keywords
  / stopword-filtered overlap built in.
- `industrial_range` — LLM-as-judge wrapper around any CodeOven;
  pointwise + pairwise with caching.

📚 New `wiki/Ranges.md`.

## 0.41.0

✨ **CUDA 6.1 / Pascal support.** `compute_capability`, `is_pascal`,
`pascal_safe_dtype` (fp32 on CPU, fp16 on Pascal / Volta / Turing,
bf16 on Ampere+), `pascal_mode_hints` (one-stop dict of recommended
settings for sm_61).

✨ **`examples/train_hypernix_1_5_gtx1080.py`** — HyperNix 1.5,
verified 92,130,048 params, trains on an 8 GB Pascal card via
`auto_freezer` + `flash_freezer(slow=True)`.

📚 New `wiki/Pascal.md` with a full sm_61 playbook.

## 0.40.0

✨ **`freezer` module** — VRAM manager. `OldFreezer` (8 – 10 GB,
batch=1, fp16, empty_cache each step), `NewFreezer` (11 GB+, batch=8,
fp32/bf16), `FlashFreezer` (OOM-safe retry wrapper with exponential
backoff, wait-for-free-GB, and optional slow-mode that halves
`current_batch_size` on each retry).

📚 New `wiki/Freezer.md`.

## 0.36.0

✨ **`old_fridge` / `mediocre_fridge` / `new_fridge`** — memory
housekeeping (freeze/unfreeze/parameter_stats), judge-training dataset
synthesis, and training-curve plotting.

✨ `examples/train_hypernix_0_1_5_evaluator.py` — end-to-end example
wiring ovens + all three fridges.

📚 New `wiki/Fridges.md`.

## 0.35.0

✨ **Gemma 4, Qwen 3.5 & 3.6, GLM 5.x, Nix collection presets.** New
entries in both `ARCH_PRESETS` (for `new_oven`) and `KNOWN_MODELS`
(for short-name resolution). Config knobs verified against the actual
HuggingFace repos.

## 0.34.0

✨ **AutoModel fallback.** `load_snapshot` routes any non-HyperNix
`model_type` (Gemma, Phi, DeepSeek, GLM, GPT-OSS, …) through a thin
`transformers.AutoModelForCausalLM` wrapper. New ARCH_PRESETS covering
those families.

## 0.33.0

✨ **Windows + macOS support.** Cross-platform `doctor`, path
handling, `llama-quantize` resolution.

✨ **Python 3.13** support (sentencepiece 0.2.1 floor).

✨ **Runtime auto-install.** `HYPERNIX_AUTO_INSTALL` env var (default
on) lets missing runtime deps be installed lazily; `hypernix doctor
--fix` makes it explicit.

## 0.32.1

🐛 Fall back to the slow tokenizer when the `tokenizers` crate is too
old to decode a newer tokenizer.json.

## 0.32.0

✨ **torch 2.7+** (incl. CUDA 11.8 builds).

✨ One-shot PyPI publish via GitHub Actions Trusted Publishing.

## 0.31.0

✨ **Chat REPL.** `hypernix chat --repo-id <short-name>` plus
`CodeOven.chat(turns, ...)`.

✨ **Nano-nano / Nano-mini / nano-nano-927** family — new entries in
`KNOWN_MODELS`.

## 0.30.0

✨ **`old_oven` code-generation wrapper.** `preheat`, `CodeOven`,
`bake_code`, `fill_middle`, `save_pt` / `load_pt`. `--auto-oven`
top-level CLI shortcut.

## 0.21.0

✨ Download every file the model needs — not just weights — so the
output directory is a self-contained snapshot.

## 0.2.0

✨ First subcommand-based CLI. `train` module scaffold. Fixed
`tokenizer.ggml.merges` in GGUF output.

---

## Upgrading

`hypernix` follows no breaking-change policy yet. Patch releases
(`0.45.x`) are always safe to upgrade — they only fix bugs, UX
papercuts, or improve error messages.

Minor releases (`0.N.0`) add features. The usual gotcha is renamed
kwargs from the UX-polish patches above; when in doubt, check the
signature:

```python
import inspect
from hypernix import smoke_alarm, pans

print(inspect.signature(smoke_alarm.GasAlarm))
print(inspect.signature(pans.FryingPan))
```

## Contributing changelog entries

New features should land with a one-paragraph entry at the top of
this file, grouped by emoji legend. Patch releases get a couple of
bullet points; minor releases get a section per subsystem touched.
Keep the tone utilitarian — what changed, how the caller notices,
what to do instead if an old call stopped working.

---

## 0.61.4

🖥️ **Interactive TUI/CLI (`hypernix-cli`)** — Rich-based interactive menu system with fallback mode for all major operations: model management, training control, ASR/TTS pipelines, AI assistant, and Web UI launcher. Commands include `models`, `train`, `asr`, `tts`, `pipeline`, `assistant`, and `webui`.

🤖 **Linux Local AI Assistant** — Voice-controlled AI assistant with ASR input, natural language TTS responses, and system control capabilities. Built-in commands: `/help`, `/voice`, `/system`, `/quit`. Features persistent memory and conversation context.

🌐 **Web UI with Tailscale Integration** — Modern web dashboard at `http://localhost:8080` with secure Tailscale tunneling for remote access. Provides model management, training monitoring, ASR/TTS pipeline controls, and chat interface.

🔊 **Enhanced ASR/TTS Pipelines** — Improved `ASRToTTS` direct speech-to-speech conversion and enhanced `ASRToLLMToTTS` full conversational pipeline with better error handling, device management, and streaming support.

📦 **30+ New Model Architectures** — Added support for:
- LiquidAI LFM2.5-8B-A1B (GGUF quantized)
- OpenBMB MiniCPM5-1B
- Google Gemma 4 family (all variants including 31B-it, 12B, 4B, 1B)
- Qwen3.5 series, Phi-4, DeepSeek-V2.5, GLM-Edge/MoE
- GPT-OSS, Nemotron, Llama-3.2, Mistral-Nemo, Mixtral-8x22B
- Full Nano-Nano collection (ray0rf1re/nano-nano)
- And 15+ additional architectures for vision, audio, and language tasks

🛡️ **Pressure Cooker V2 Improvements** — Fixed lookahead slow buffer initialization bug that silently disabled lookahead optimization. Added comprehensive test coverage for both scalar and multitensor paths with Q8/Q6/Q5.5/Q4M quantization-aware training.

📚 **Documentation Updates** — Complete changelog preserved, README updated with new features, wiki expanded with usage examples for all new modules.

🔧 **Dependency Updates** — Updated requirements for latest transformers, accelerate, bitsandbytes, and TTS/ASR libraries. Added tailscale-python for secure tunneling.

---

## Contributing changelog entries
