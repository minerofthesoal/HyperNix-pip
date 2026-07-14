<p align="center">
  <img src="https://raw.githubusercontent.com/minerofthesoal/hypernix-pip/2d5eb37/assets/logo.png" alt="hypernix logo" width="240" />
</p>

# hypernix

[![PyPI](https://img.shields.io/pypi/v/hypernix.svg)](https://pypi.org/project/hypernix/)
[![Python](https://img.shields.io/pypi/pyversions/hypernix.svg)](https://pypi.org/project/hypernix/)
[![License](https://img.shields.io/pypi/l/hypernix.svg)](https://github.com/minerofthesoal/hypernix-pip/blob/main/LICENSE)

**End-to-end toolkit for the HyperNix family of PyTorch language models** —
the chat-tuned `ray0rf1re/hyper-Nix.2` (current default) and the original
`ray0rf1re/hyper-nix.1` (still fully supported via the same `preheat()` /
`download_model()` paths) — covering download, chat, fine-tune, evaluate,
quantize, and ship.


| Subsystem | What it does |
|---|---|
| `hypernix.download` | Pull snapshots from the Hub (short-name resolution, gated repos, offline cache). |
| `hypernix.train` | `HyperNixConfig`, `HyperNixModel`, `init_from_scratch`, `expand_checkpoint`, `train`. Non-HyperNix archs route through `AutoModelForCausalLM`. |
| `hypernix.old_oven` | `CodeOven` — ready-to-use wrapper around a snapshot: `.complete()`, `.chat()`, `.fill()`, `.save_pt()`. `new_oven()` spins a fresh one from the [ARCH_PRESETS](#supported-model-families) registry. |
| `hypernix.old_fridge` | Memory housekeeping: `freeze`, `unfreeze`, `parameter_stats`, `offload_to_cpu`, `chill_cache`. |
| `hypernix.mediocre_fridge` | Judge-training dataset generation — `synthesize_judge_corpus`, `collect_responses_from`. |
| `hypernix.new_fridge` | Training-curve graphing — `parse_training_log`, `plot_loss_curve`, `plot_score_distribution`. Matplotlib installed lazily. |
| `hypernix.new_range` / `old_range` / `industrial_range` | Labeling rubrics for `mediocre_fridge.collect_responses_from`: `new_range` is a zero-dep first-fail rubric, `old_range` is a scored rubric with explainability, `industrial_range` is the LLM-as-judge wrapper. |
| `hypernix.freezer` | VRAM manager: `OldFreezer` (8-10 GB), `NewFreezer` (11 GB+), `FlashFreezer` (OOM-safe retry wrapper). Pascal (sm_61 / CUDA 6.1) helpers + 16 CPU presets (i7 7th-14th gen, Core Ultra Series 1 & 2) + 20 GPU presets (H100/H200, RTX A4500-A6000, RTX PRO Ada/Blackwell, 4070 Ti Super, 4080 Super, 1660 Ti, 2080/2080 Super/2080 Ti, 3080 Ti, 1080/1080 Ti). |
| `hypernix.smoke_alarm` | Training-step planner & monitor. `RadsAlarm` (constants, lightest), `GasAlarm` (CPU/GPU presets), `ModernAlarm` (warmup-measured), `AutoAlarm` (selector). Plus `storage_warning`, mid-run `check`. |
| `hypernix.pans` | 5-tier data preprocessing: `FryingPan` → `SaucePan` → `Skillet` → `GrillPan` → `Wok`. Pair with `sink.Sink.pour` to write the output to disk. |
| `hypernix.microwave` | 5-tier throwaway inference: `defrost` → `low_zap` → `zap` → `high_zap` → `chat_zap`, plus `reheat` for continuing a prior output. |
| `hypernix.table` | Dead-simple tabular viewer: `from_training_log`, `from_judge_corpus`, `filter`, `select`, `show`. |
| `hypernix.sink` | Append-only file sink with optional rotation + dedupe. |
| `hypernix.instant_pot` | `brew(recipe)` — one-shot end-to-end pipeline. Also available as `hypernix brew recipe.json`. |
| `hypernix.coffee_maker` | 3 tiers (drip / french-press / percolator) + `cold_brew` type for long checkpointed runs. |
| `hypernix.espresso_maker` | 4-tier evaluation: `Ristretto` / `SingleShot` / `DoubleShot` / `Lungo` — run a prompt battery, score, return shots. |
| `hypernix.blender` | 4-tier multi-source mixing: `HandBlender` / `PersonalBlender` / `CountertopBlender` / `HighPowerBlender`. |
| `hypernix.toaster` | 4-tier per-line formatting: `TwoSliceToaster` / `FourSliceToaster` / `ConveyorToaster` / `ToasterOven`. |
| `hypernix.food_processor` | 4-tier bulk chunking: `ChopBlade` / `SliceBlade` / `ShredBlade` / `PureeBlade`. |
| `hypernix.smoker` | 4-tier training quality: `UseableSmoker` / `GoodSmoker` / `CommercialSmoker` / `HighQualitySmoker`. |
| `hypernix.deep_fryer` | 2-tier model-weight perturbation: `LightFry` (regulariser) / `HeavyFry` (severe, for bad-model negatives). In-place, reversible via snapshot. |
| `hypernix.cake_pan` | Hybrid CPU + GPU training guard with NaN/Inf detection, wall-time watchdog, memory-pressure offload, and pristine-state rollback via `BakeOff`. |
| `hypernix.salt_shaker` | 3-tier gentle data augmentation: `FromTheBag` / `HandCrusher` / `PoshSaltDish`. |
| `hypernix.pepper_shaker` | 3-tier sharp perturbations: `SmallShaker` (MLM-style mask) / `Dish` (typos) / `TallHandmade` (negation). |
| `hypernix.pressure_cooker` | Custom AdamW optimizer in 5 tiers: base `PressureCooker` + CPU (`StovetopCooker`, `ElectricCooker`) + GPU (`InductionCooker`, `ProCooker`) + `universal_cooker` selector. Grad accumulation, GradScaler integration, fused/foreach AdamW, optional CUDA-graph capture on Pro. v0.70.0 V2 rewrite adds quantization-aware training (fp16/bf16/fp64 mixed-precision, QAT hooks for Q8/Q6/Q5.5/Q4M), gradient checkpointing, adaptive clipping, EMA shadowing, distributed awareness, dynamic loss scaling, parameter freezing callbacks, LR finder, and tvtop metrics streaming. |
| `hypernix.pressure_cooker_v3` | ZeRO-optimized V3 optimizer with FP8 support. New `QuantDtype` enum (FP8/FP16/FP32/FP64/Q8/Q6/Q5_5/Q4M) and `QuantConfig` dataclass. `PressureCookerV3` class with ZeRO-1/2 support, improved memory efficiency, and heavily tested quantization paths. `PressureCookerV3Plus` adds full QAT with calibration. |
| `hypernix.abbicus` | Automatic token regulation and curriculum tuning. **`Abbicus`** (linear) dynamically modifies max sequence length based on model size (0.5B–72B), global step, and dataset type. **`TurboAbbicus`** (v0.70.4) grows context exponentially to a configurable `hard_cap`, then oscillates using a sine wave adjusted by CPU load (never GPU). Includes VRAM safeguard that scales back context when memory is tight. |
| `hypernix.qa` | *(v0.70.4)* **`QAProcessor`** — turns structured datasets (JSONL, `list[dict]`, plain text) into causal LM training strings. Two modes: `question_answer` (`Question: {q}\nAnswer: {a}`) and `predict_next` (concatenation). Optional `salt_shaker` / `pepper_shaker` seasoning applied *before* templating so template keywords are never corrupted. |
| `hypernix.stml` | *(v0.70.4)* **Short Term Memory Loss** — two tools. `calculate_vram_context(vram_gb, params, batch_size, precision)` estimates the max safe trained context given your hardware. `STML` context manager enforces an `untrained_max_context` hard cap and folds long sequences into `(batch × segments, segment_length)` chunks so the model trains on all the data. Integrates with Abbicus / TurboAbbicus. CLI: `hypernix stml --vram 24 --params 7`. |
| `hypernix.compute_framework` | Hardware-agnostic multi-device training. Abstracts CUDA, MPS, CPU, TPU backends with automatic DDP/ZeRO wrapping. `ComputeFramework` handles PyTorch DDP initialization, device placement, fallback logic. Supports `local_rank`, `world_size`, `use_ddp`, `use_fsdp`, `zero_stage`. Auto-detects backend and sets up device. |
| `hypernix.workshop` | Model frameworks and TTS/ASR pipelines. `WorkshopFramework` base class with `FrameworkConfig` for TTS, ASR, LLM, Vision models. Pre-built templates for ray0rf1re/nano-nano collection and 30+ architectures (LiquidAI LFM2.5, MiniCPM5, Gemma 4, Qwen3.5, Phi-4, DeepSeek-V2.5, GLM-Edge/MoE, GPT-OSS, Nemotron, Llama-3.2, Mistral-Nemo, Mixtral-8x22B). Includes `TTSEngine`, `ASREngine`, `ASRToTTS` (speech-to-speech), `ASRToLLMToTTS` (conversational pipeline). |
| `hypernix.tvtop` | Backwards-compatibility shim — all functionality moved to `hypernix.tv`. Re-exports everything so `import hypernix.tvtop` continues to work. Console script `tvtop` now launches the premium `tvtop_plus_plus` dashboard; use `tvtop-old` for the classic view. |
| `hypernix.lunchbox` | Consistent-schema dataset packager. `Lunchbox.for_eval()` pre-loads the recommended eval-results columns; `pack(path)` / `push_to_hub(repo_id)` routes through `datasets.Dataset.from_list` so the Parquet `huggingface` metadata stays coherent with the column set (fixes the `CastError: column names don't match` path in the Hub viewer). |
| `hypernix.whisk` | Checkpoint averaging — `swa_average` (uniform mean), `ema` (exponential), `geometric_mean`. Accepts state dicts or paths to `.pt` / `.safetensors`. `whisk_to_snapshot` writes a full HF-style snapshot in one call. |
| `hypernix.cutting_board` | Train / val / test splitting. `CuttingBoard` (deterministic random) + `StratifiedBoard` (preserves class distribution on labelled records). Renormalises ratios; writes per-split files with `.slice_to_files()`. |
| `hypernix.apron` | RNG-state guard. `apron(seed=…)` context manager snapshots Python `random`, NumPy (if installed), torch CPU and every CUDA device's RNG, optionally seeds, and restores the originals on exit. |
| `hypernix.recipe_book` | Named-config registry. `RecipeBook` with `add` / `get` / `save` / `load` / `cook(name, **overrides)`. `cook` dispatches by `kind` (`instant_pot` / `cold_brew` / `espresso`). Built-in recipes via `RecipeBook.from_builtins()`. |
| `hypernix.cookbook` | Chat-template registry. Built-in templates for `chatml` / `hyper-nix.2` / `llama3` / `llama2` / `alpaca` / `vicuna` / `plain`. `for_model(repo_id)` picks the right one. Wired into `CodeOven._format_chat` so a `hyper-Nix.2` snapshot Just Works. |
| `hypernix.countertop` | Multi-turn chat session. `Countertop(oven, system=…)` with `say(user)` / `reset()` / `save(path)` / `load(path)`. Auto-trims long histories, optional `bell=` for streaming, optional `flour=` for chat-quality cleanup. |
| `hypernix.menu` | Named system-prompt registry: `default` / `concise` / `code-helper` / `judge` / `creative` / `chef` / `hyper-nix`. Pair with `countertop(oven, persona=