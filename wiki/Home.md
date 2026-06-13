# hypernix wiki

Deep-dive reference for the `hypernix` package. For the headline tour
see the [top-level README](../README.md).

## Topic guides

| Guide | Covers |
|---|---|
| [Ovens](Ovens.md) | `CodeOven`, `old_oven.preheat`, `new_oven`, `bake_code`, `fill_middle`, `save_pt` / `load_pt`. |
| [Fridges](Fridges.md) | `old_fridge` (memory housekeeping), `mediocre_fridge` (judge-data synthesis), `new_fridge` (graphing). |
| [Ranges](Ranges.md) | `new_range` / `old_range` / `industrial_range` — labeling rubrics from cheap heuristics up to LLM-as-judge. |
| [Freezer](Freezer.md) | VRAM manager — `OldFreezer`, `NewFreezer`, `FlashFreezer`, `auto_freezer`, `probe_vram`, plus CPU / GPU preset registries. |
| [Alarms](Alarms.md) | Smoke alarms — `RadsAlarm` (lightest), `GasAlarm` (mid), `ModernAlarm` (warmup-measured), `AutoAlarm`. CPU + GPU preset tables. |
| [Kitchen](Kitchen.md) | pans / microwave / table / sink / instant_pot / coffee_maker / pressure_cooker / pressure_cooker_v3. |
| [Pascal](Pascal.md) | GTX 1080 / CUDA 6.1 / sm_61 training playbook. |
| [Architectures](Architectures.md) | `ARCH_PRESETS` seed registry and `KNOWN_MODELS` short-name registry. |
| [Training](Training.md) | `init_from_scratch`, `expand_checkpoint`, `train`, AutoModel fallback, `compute_framework` for multi-device, `abbicus` for curriculum tuning. |
| [Pressure Cooker v3](Pressure-Cooker-V3.md) | `PressureCookerV3`, V3Plus QAT, `StovetopV3CookerPlus`, `CookerLite`. |
| [Abbicus](Abbicus.md) | Automatic token regulation and curriculum tuning by model size / step. |
| [Frameworks](Frameworks.md) | `ComputeFramework` multi-device training and `workshop` TTS/ASR pipelines. |
| [Tupperware](Tupperware.md) | Automated dataset round splitting with optimal LR and optional eval. |
| [Quantization](Quantization.md) | GGUF pipeline, k-quants, `HyperNixQuantizer`, `pressure_cooker_v3` QAT. |
| [CLI](CLI.md) | Every subcommand, every flag, typical invocations. |
| [Roadmap](Roadmap.md) | Planned releases (0.70.4 → 0.70.6 → 0.71.2). |
| [macOS-legacy](macOS-legacy.md) | Running on old Intel Macs with torch 1.13 via `hypernix.torch_compat`. |
| [Changelog](Changelog.md) | Full per-release notes — features, fixes, UX papercuts. |
| [Workshop](Workshop.md) | Model frameworks for TTS/ASR/LLM/Vision, nano-nano collection, 30+ architectures, `TTSEngine`, `ASREngine`, speech-to-speech pipelines. |

## The subsystem map

```
                 ┌──────────────┐
                 │  download    │  huggingface-hub + KNOWN_MODELS
                 └──────┬───────┘
                        ▼
          ┌───────────────────────────┐
          │        train              │  HyperNixConfig / Model
          │  (init, expand, loop,     │  AutoModel fallback for
          │   load_snapshot)          │  Gemma 4 / Qwen 3.5+ / GLM 5 / …
          └──────┬────────────┬───────┘
                 │            │
                 ▼            ▼
          ┌───────────┐  ┌───────────┐
          │ old_oven  │  │  new_oven │  new_oven = fresh init in
          │ (preheat) │  │           │  one of 20+ ARCH_PRESETS
          └─────┬─────┘  └─────┬─────┘
                └──────┬──────┘
                       ▼
         ┌──────────────────────────────┐
         │        CodeOven              │  .complete, .chat, .fill,
         │                              │  .train, .save_pt
         └──────────────────────────────┘

                           Assist modules
                                │
            ┌──────────────┬────┴────┬──────────────┐
            ▼              ▼         ▼              ▼
       freezer         old_fridge  mediocre_   new_fridge
       (VRAM mgr)      (memory)    fridge       (graphing)
                                   (datasets)

       convert → quantize → upload     (GGUF pipeline)
```

## Design principles

- **Small, inspectable modules.** Every subsystem is <~300 LOC and
  usable in isolation.
- **No hard dependencies on the big stuff.** `transformers`, `matplotlib`,
  and `llama-cpp-python` are all loaded lazily when first needed.
  `HYPERNIX_AUTO_INSTALL=0` disables runtime pip calls.
- **Degrade on CPU / old hardware.** Every VRAM and dtype decision has a
  CPU-safe fallback; the test suite exercises CPU-only paths directly.
- **One name, one thing.** `preheat` loads, `bake_code` generates,
  `freeze` freezes, `chill_cache` frees cache, `suggest_batch_size`
  suggests. Names are verbs where it makes sense.

## Version history

Recent releases (see [Changelog](Changelog.md) for the full per-release
notes going all the way back to 0.2.0):

- **0.70.3b2** — Web UI rebuilt from static assets; Tailscale opt-in via `-T`. New `Tupperware` round splitter, `StovetopV3CookerPlus`, `HyperNixQuantizer` facade. Wiki pages for Pressure Cooker v3, Abbicus, Frameworks, Roadmap. `old_fridge.unwrap_model` for DDP/FSDP.
- **0.70.3** — `lazy_suzan` decentralized multi-GPU linking, `StovetopV3Cooker` / `CookerLite`, ComputeFramework crash fixes.
- **0.61.2** — `tvtop` btop-style multi-panel rewrite. Old single `hardware` panel replaced by **four** richer panels: `cpu` (TOTAL bar + per-core grid + 3-row history graph), `memory` (USED / CACHE / FREE / SWAP breakdown bars + 2-row history), `gpu` (UTIL / VRAM / TEMP / PWR gauges + 2-row history + name tag), `training` (unchanged). New probes: `_safe_psutil_per_core`, `_read_proc_stat_per_core` (Linux fallback), `_read_memory_breakdown` (used/free/cached/swap), `_query_nvidia_smi_full` (adds temperature + power.draw + power.limit + GPU name). Footer shows core count + GPU label. All original — no btop code copied. 9 new regression tests in `tests/test_v061_2.py`.
- **0.61.1** — chat CLI + 5 bug-fix / utility passes + **MAJOR `hyper-Nix.2` undertrained warning**. New `hyped` console script: high-quality TUI chat CLI with a configurator that lets you pick from a curated short-list (`hyper-Nix.2`, `hyper-nix.1`, `nix2.7a`, `nix2.6-mm`, `nix2.5`, `qwen3.5-{0.8b,2b,4b,9b}`, `nano-nano-v4`, `nano-mini-6.99-v2`, `nano-nano-927-v3`) or browse all `KNOWN_MODELS`, then pick a persona from `MENU` and tweak sampling. New `hypernix.utils` module — `healthcheck()` / `diagnostic_info()` / `list_models()` / `print_models()` / `session_dir()` / `is_module_available()` / `has_binary()`. New `hypernix.utils.warn_hyper_nix_2()` fires a MAJOR red-bordered warning whenever the under-trained `ray0rf1re/hyper-Nix.2` checkpoint is loaded (suppress with `HYPERNIX_SUPPRESS_HYPERNIX2_WARNING=1`). 5 bugs fixed: hyped chat-loop now routes through `Countertop.say` for proper history management; ASCII picker uses `*` not `★`; `UPS` instantiation no longer blocks on IP-geolocation; `plasma.calibrate_alarm` resets instead of compounding on re-call; `tv._sanitise` preserves `\r` so Windows CRLF logs render. Plus utilities: `Menu.find()` fuzzy persona lookup; `injection.thinking()` / `testing()` / `system_override()` shortcuts. 37 new tests in `tests/test_v061_1.py`.
- **0.61.0** — Python 3.14 support + 3 new modules + tvtop visual rewrite. New: `ups` (uninterruptible-power-supply mode — checks open-meteo for severe-weather codes + a pluggable scheduled-outage callback; on panic, fires `snapshot_fn` once and 3×'s the trainer's `save_every`), `injection` (token splicers — `ThinkingInjector` wraps in `<think>...</think>`, `TestingInjector`, `SystemOverrideInjector`, `CustomInjector`), `plasma` (quick GPU benchmark — runs a 6-step Llama-shape fwd/bwd/step loop and returns a `calibration_factor` you apply to a `smoke_alarm` to make ETAs reflect actual hardware). **`tvtop` rewrite**: btop++-style multi-panel layout with rounded panel frames + side-by-side hardware/training panels + a 5-row Unicode block-bar loss-curve graph + a full-width log panel. Auto-detect now skips logs that don't contain `step N/M loss=…` lines (no more accidentally tailing Konsole/browser logs); binary chars are sanitised before render; nvidia-smi cached for 3 s. 32 new tests in `tests/test_v061_b1.py` + 2 supplementary in `test_v060.py`.
- **0.60.0** — eight new modules. Headline four: `tv` (btop++-style training dashboard, run with the `tvtop` CLI; ANSI-colour, no hard deps; tails the latest log, shows step/ETA/throughput/loss-sparkline/CPU/RAM/GPU vitals/log tail), `compactor` (zip older checkpoints — `Compactor(root, keep_recent=3, fmt="zip")` or one-shot `compact()`), `ethanol` (bounded GPU overclock helper, run with `eth 0` to `eth 30`; refuses to apply without `--confirm` or `HYPERNIX_ETHANOL_CONFIRM=1`; nvidia-settings + nvidia-smi + rocm-smi + intel_gpu_frequency backends), `outage` (display blanker context manager — restores the screen when training finishes, errors, or you Ctrl-C; xset / wlopm / pmset / Windows backends). Plus four 4-tier modules: `timer` (KitchenTimer / EggTimer / IntervalTimer / PomodoroTimer), `thermometer` (InstantThermometer / ProbeThermometer / InfraredThermometer / DigitalThermometer for CPU+GPU temp sampling), `dishwasher` (HandWash / QuickWash / NormalWash / HeavyDuty cleanup of stale logs / checkpoints / build artefacts), `strainer` (Colander / FineMesh / NutMilkBag / Cheesecloth dataset filtering, including 8-gram Jaccard near-dup detection). 44 new tests in `tests/test_v060.py`.
- **0.52.6** — more forgiving `smoke_alarm` kwargs: `time_budget_seconds` now defaults to `600.0` (10 min) so `GasAlarm(cpu_preset="i7_7th_gen")` Just Works, and the base `Alarm` accepts `log_every` / `save_every` / `eval_every` so a downstream training-config dict can be `**`-spread into the constructor without `TypeError`. 20 regression tests in `tests/test_v052_6.py`.
- **0.52.5** — `smoke_alarm` is forgiving: every tier (`RadsAlarm` / `GasAlarm` / `ModernAlarm` / `AutoAlarm`) now accepts `cpu_preset=` / `gpu_preset=` / `max_steps=` directly. `cpu_preset=` accepts both a CPU SKU name (`"i7-7700hq"`) and a generation-family alias (`"i7_7th_gen"` → `i7-7700hq`, `"i9-12th-gen"` → `i9-12900k`, `"core-ultra"` → `core-ultra-7-155h`, etc.). `max_steps` caps `recommended_steps()` so a downstream training loop can hard-limit what the alarm hands back. 27 regression tests in `tests/test_v052_5.py`.
- **0.52.4** — bug fix: `CodeOven.chat` no longer crashes with `ValueError: too many dimensions 'str'` when the tokenizer's `apply_chat_template` returns an unexpected shape (a plain string, a 2-D batched tensor, a `BatchEncoding`, etc.). New `_coerce_token_ids` helper normalises every legal return shape into a flat `list[int]`; `_run` now also defensively coerces its argument and raises a clear `TypeError` if anything still slips through. 19 regression tests in `tests/test_v051_4.py`.
- **0.52.3** — auto version bump from CI (no code changes vs 0.51.3).
- **0.51.3** — `quantize` rewrite: the 6-type alias dict from 0.51.2 grew into a 30-entry `QUANT_CATALOG` of `QuantSpec` dataclasses (frozen: `name`, `bits_per_weight`, `category` ∈ `{float, legacy, k, iq}`, `size_factor`, `notes`, `recommended`). 49 aliases now map to the full llama.cpp ladder — floats (`F32` / `F16` / `BF16`), legacy quants (`Q4_0` / `Q4_1` / `Q5_0` / `Q5_1` / `Q8_0`), k-quants (`Q2_K` … `Q6_K`), and IQ-quants (`IQ1_S` … `IQ4_XS`). New helpers: `quant_recommended()`, `quant_by_category("k")`, `quant_for_size(target_bytes, fp16_bytes)`, `quant_estimate_size("q4km", fp16_bytes)`, `quant_resolve_spec("q4km")`. README + wiki refreshed; `hyper-nix.1` stays a fully-supported model alongside `hyper-Nix.2`. 37 new tests in `tests/test_v051_3.py` covering the catalog, helpers, alias resolution, and backward-compat paths.
- **0.51.2.1** — fix the PyPI logo broken-image that shipped in 0.51.2: README's `<img src=…/main/assets/logo.png>` returned 404 because `main` didn't have the file yet (it was on the working branch). Switched to a SHA-pinned `…/2d5eb37/assets/logo.png` URL that's guaranteed to resolve regardless of branch state, so PyPI renders the logo from this release onward.
- **0.51.2** — auto version bump from CI (no code changes vs 0.51.1.1).
- **0.51.1.1** — logo present and accounted for: `assets/logo.png` (1408×768 RGBA, 670 KB) + the smaller transparent variant `assets/logo1.png` are now in the repo. (PyPI render still broken in this release — see 0.51.1.2.)
- **0.51.1** — 5 bug-fix patches across 3 review passes (1 by-hand source-read + 2 hand-driven testing): `bell` no longer leaks the stop marker into the streamed output; `countertop._trim` always preserves the freshly-appended user turn; `cookbook` `_HYPER_NIX_2` no longer shares dict objects with `_CHATML` (mutation-aliasing fix); `flour.process` accepts torch tensors / generators as `produced_ids`; `pressure_cooker.UniversalCooker.select` now detects Pascal (sm_61, e.g. GTX 1080) and forces `fused=False` instead of silently picking a kernel that requires sm_70+. Project logo wired into README + `assets/logo.png` for the PyPI page.
- **0.51.0** — chat-first release: 5 new modules + first-class support for `ray0rf1re/hyper-Nix.2`. `cookbook` (chat-template registry: chatml / hyper-nix.2 / llama3 / llama2 / alpaca / vicuna / plain + `for_model(repo_id)` resolver), `countertop` (multi-turn session with persisted history, system prompt, auto-trim), `menu` (system-prompt presets: default / code-helper / judge / creative / chef / hyper-nix), `bell` (streaming-token callback + done notification), `flour` (chat-quality logits processor: repetition penalty + no-repeat n-gram + role-leak suppression + decoded-text stop-sequence detection — the bundle that makes hypernix's chat surface better than raw transformers for chatting). `DEFAULT_REPO_ID` now points at `ray0rf1re/hyper-Nix.2`; `CodeOven.repo_id` is plumbed through to `_format_chat` so the cookbook fallback fires automatically.
- **0.50.0** — 4 new modules + 3 bug-fix passes: `whisk` (SWA / EMA / geometric-mean checkpoint averaging) + `cutting_board` (train/val/test split, deterministic + stratified) + `apron` (RNG-state guard context manager) + `recipe_book` (named-config registry with `cook(name, **overrides)`). Bug fixes: `pressure_cooker` falls back to scalar AdamW when private `_functional` API is unavailable; `deep_fryer` uses per-parameter `torch.Generator` for reproducible noise; `food_processor.SliceBlade` validates `overlap_chars`; `industrial_range` pairwise parser detects "tie/tied/equal" anywhere in the head; `instant_pot.brew` fast-fails on missing dataset; `microwave._preheat` requires `config.json` before treating a string as a local snapshot path; `cake_pan` rolls back on `step_timeout` before raising; `apron` snapshots state **before** seeding so exit really restores the caller's pre-call RNG.
- **0.49.0** — `lunchbox` dataset packager (fixes HF-Hub `CastError: column names don't match`) + 31 new coverage tests across lunchbox / pressure_cooker / deep_fryer / cake_pan / freezer / shakers / smoke_alarm + end-to-end evaluator integration test
- **0.48.0** — `pressure_cooker` rewrite: 4 new tiers (`StovetopCooker`, `ElectricCooker`, `InductionCooker`, `ProCooker`) + `universal_cooker` selector + grad accumulation + `GradScaler` integration + fused/foreach AdamW kernels
- **0.47.1** — relaxed install pin to `torch>=1.13,<3` so `pip install hypernix` works on old Intel Macs
- **0.47.0** — `deep_fryer` (weight-noise) + `cake_pan` (CPU+GPU training guard) + 32 new CPU presets (i5, i9, Ultra 5/9) + 51 new GPU presets (full GTX 10 / RTX 20/30/40/50 lineups, Apple M-series, AMD Instinct + Radeon)
- **0.46.1** — `nix` short-name fallback chain: 2.7a → 2.6-mm → 2.5
- **0.46.0** — `salt_shaker` / `pepper_shaker` augmenters + `torch_compat` shim for old Intel Macs with torch 1.13
- **0.45.3** — `smoke_alarm` accepts `preset=` one-string kwarg
- **0.45.2** — pans accept `context_length` / `max_chars` (kw-only)
- **0.45.1** — pans init fix: positional args no longer bind to `name`
- **0.45.0** — espresso_maker, blender, toaster, food_processor, smoker; +3 microwave tiers; +2 coffee_maker tiers + cold_brew; CLI `brew`
- **0.44.0** — pans / microwave / table / sink / instant_pot / coffee_maker / pressure_cooker
- **0.43.0** — `smoke_alarm` (Rads / Gas / Modern / Auto) + 16 CPU + 20 GPU presets
- **0.42.0** — `new_range` / `old_range` / `industrial_range` labeling rubrics
- **0.41.0** — CUDA 6.1 / Pascal helpers, HyperNix 1.5 (92.1 M) training script
- **0.40.0** — `freezer` module (OldFreezer / NewFreezer / FlashFreezer)
- **0.36.0** — `old_fridge` / `mediocre_fridge` / `new_fridge` + evaluator example
- **0.35.0** — Gemma 4, Qwen 3.5 / 3.6, GLM 5.x, Nix family presets
- **0.34.0** — AutoModel fallback, Gemma/Phi/GLM/DeepSeek/GPT-OSS presets
- **0.33.0** — Windows + macOS support, Python 3.13, runtime auto-install
- **0.32.x** — CUDA 11.8 torch, slow-tokenizer fallback
- **0.31.x** — Chat REPL, Nano-nano / Nano-mini model family
- **0.30.x** — Code-generation oven (`old_oven.preheat`)

See [Changelog.md](Changelog.md) for per-release details including
patch versions, UX fixes, and bug reports.
