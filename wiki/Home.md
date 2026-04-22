# hypernix wiki

Deep-dive reference for the `hypernix` package. For the headline tour
see the [top-level README](../README.md).

## Topic guides

| Guide | Covers |
|---|---|
| [Ovens](Ovens.md) | `CodeOven`, `old_oven.preheat`, `new_oven`, `bake_code`, `fill_middle`, `save_pt` / `load_pt`. |
| [Fridges](Fridges.md) | `old_fridge` (memory housekeeping), `mediocre_fridge` (judge-data synthesis), `new_fridge` (graphing). |
| [Freezer](Freezer.md) | VRAM manager — `OldFreezer`, `NewFreezer`, `FlashFreezer`, `auto_freezer`, `probe_vram`. |
| [Pascal](Pascal.md) | GTX 1080 / CUDA 6.1 / sm_61 training playbook. |
| [Architectures](Architectures.md) | `ARCH_PRESETS` seed registry and `KNOWN_MODELS` short-name registry. |
| [Training](Training.md) | `init_from_scratch`, `expand_checkpoint`, `train`, AutoModel fallback. |
| [Quantization](Quantization.md) | GGUF pipeline, k-quants, `llama-quantize` integration. |
| [CLI](CLI.md) | Every subcommand, every flag, typical invocations. |

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

The project is semver-ish; minor bumps add features, patch bumps are
bug fixes. Recent notable releases:

- **0.41.0** — CUDA 6.1 / Pascal helpers, HyperNix 1.5 (92.1 M) training script
- **0.40.0** — `freezer` module (OldFreezer / NewFreezer / FlashFreezer)
- **0.36.0** — `old_fridge` / `mediocre_fridge` / `new_fridge` + evaluator example
- **0.35.0** — Gemma 4, Qwen 3.5 / 3.6, GLM 5.x, Nix family presets
- **0.34.0** — AutoModel fallback, Gemma/Phi/GLM/DeepSeek/GPT-OSS presets
- **0.33.0** — Windows + macOS support, Python 3.13, runtime auto-install
- **0.32.x** — CUDA 11.8 torch, slow-tokenizer fallback
- **0.31.x** — Chat REPL, Nano-nano / Nano-mini model family
- **0.30.x** — Code-generation oven (`old_oven.preheat`)
