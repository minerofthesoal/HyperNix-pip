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
| [Kitchen](Kitchen.md) | pans / microwave / table / sink / instant_pot / coffee_maker / pressure_cooker. |
| [Pascal](Pascal.md) | GTX 1080 / CUDA 6.1 / sm_61 training playbook. |
| [Architectures](Architectures.md) | `ARCH_PRESETS` seed registry and `KNOWN_MODELS` short-name registry. |
| [Training](Training.md) | `init_from_scratch`, `expand_checkpoint`, `train`, AutoModel fallback. |
| [Quantization](Quantization.md) | GGUF pipeline, k-quants, `llama-quantize` integration. |
| [CLI](CLI.md) | Every subcommand, every flag, typical invocations. |
| [macOS-legacy](macOS-legacy.md) | Running on old Intel Macs with torch 1.13 via `hypernix.torch_compat`. |
| [Changelog](Changelog.md) | Full per-release notes — features, fixes, UX papercuts. |

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
