# hypernix

[![PyPI](https://img.shields.io/pypi/v/hypernix.svg)](https://pypi.org/project/hypernix/)
[![Python](https://img.shields.io/pypi/pyversions/hypernix.svg)](https://pypi.org/project/hypernix/)
[![License](https://img.shields.io/pypi/l/hypernix.svg)](https://github.com/minerofthesoal/hypernix-pip/blob/main/LICENSE)

**End-to-end toolkit for the `ray0rf1re/hyper-nix.1` family of PyTorch
language models.**


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
| `hypernix.salt_shaker` | 3-tier gentle data augmentation: `FromTheBag` / `HandCrusher` / `PoshSaltDish`. |
| `hypernix.pepper_shaker` | 3-tier sharp perturbations: `SmallShaker` (MLM-style mask) / `Dish` (typos) / `TallHandmade` (negation). |
| `hypernix.pressure_cooker` | Custom optimizer: AdamW + warmup / plateau / cosine cooldown + lookahead. |
| `hypernix.torch_compat` | Portability shim (RMSNorm + SDPA) for running on old Intel Macs with torch 1.13. See [`wiki/macOS-legacy.md`](wiki/macOS-legacy.md). |
| `hypernix.convert` | Safetensors → GGUF at fp32/fp16. Architecture-agnostic tensor naming. |
| `hypernix.quantize` | `llama-quantize` driver for Q8_0, Q6_K, Q4_K_M, Q5_K_M. |
| `hypernix.upload` | Push the produced artifacts back to a HuggingFace repo. |

Cross-platform: Linux, macOS, Windows. Python 3.10 – 3.13.

## Who this is actually for

Put bluntly, `hypernix` is shaped around one use case: **a solo
practitioner fine-tuning or building causal LMs on a consumer GPU,
then publishing quantized GGUFs.** The `OldFreezer` defaults, the
Pascal helpers, the 8 – 10 GB tuning, the `FlashFreezer` OOM retry,
the in-process `llama-quantize` fetch, the runtime auto-pip for
fiddly deps — every design decision points at that workflow. If
you're on an H100 cluster with a real trainer, you'd pick DeepSpeed
or similar; if you're on a GTX 1080 / 2080 / 3060 trying to ship a
QLoRA fine-tune to the Hub, this is extremely on-target.

It's also worth flagging what it's *not*: the `train()` loop is a
smoke-tester, not a production trainer — it's explicitly
single-device, no sharding, no mixed precision. Anything serious
goes through a real framework. `hypernix`'s value is in everything
**around** that loop: the snapshot handling, the conversion pipeline,
the memory plumbing, the labeling rubrics, the time budgeting, and
the `pressure_cooker` optimizer for when you do want something with
more opinion than stock AdamW.

---

## Install

From PyPI:

```bash
pip install "hypernix[llama-cpp]"     # + bundled llama-cpp-python
pip install "hypernix[train]"         # + transformers, accelerate
pip install hypernix                  # core only
```

Need a specific torch build? Install torch **first**; pip will reuse
it rather than replace it:

```bash
# CUDA 11.8 — old drivers, Pascal GPUs (GTX 1080 et al.)
pip install --index-url https://download.pytorch.org/whl/cu118 torch
pip install hypernix

# CUDA 12.x — modern default
pip install --index-url https://download.pytorch.org/whl/cu124 torch
pip install hypernix

# CPU-only
pip install --index-url https://download.pytorch.org/whl/cpu torch
pip install hypernix
```

Sanity-check the environment:

```bash
hypernix doctor          # report
hypernix doctor --fix    # install missing runtime deps
```

Automatic dependency management can be disabled with
`HYPERNIX_AUTO_INSTALL=0`.

## Quickstart

### Chat with any supported model

```bash
hypernix chat --repo-id nix2.5 --message "hello"
hypernix chat --repo-id qwen3.5-4b --message "explain rotary embeddings"
hypernix chat --repo-id gemma-4-e4b --message "write a haiku"
```

Short names resolve via `KNOWN_MODELS`; see
[Supported model families](#supported-model-families).

### Convert a snapshot to GGUF

```bash
# Default: fp32 + fp16
hypernix --repo-id ray0rf1re/hyper-nix.1 --output-dir ./out

# Opt in to k-quants (needs llama-quantize)
hypernix --repo-id ray0rf1re/hyper-nix.1 --output-dir ./out \
    --quants fp32 fp16 q8_0 q6_k q4_k_m
```

### Train HyperNix 1.5 (~92.1 M params) on a GTX 1080

```bash
python examples/train_hypernix_1_5_gtx1080.py \
    --dataset corpus.txt \
    --tokenizer-source ./hyper-nix-v1 \
    --out-dir ./hypernix-1.5 \
    --steps 2000 --batch-size 1 --context-length 1024
```

Auto-detects compute capability 6.x, forces fp16 (Pascal has no native
bf16), disables TF32 / SDPA / `torch.compile`, and wraps the training
loop in a `FlashFreezer` so OOMs pause-and-halve rather than crash. See
[`wiki/Pascal.md`](wiki/Pascal.md) for the full Pascal playbook.

### Build a HyperNix 0.1.5 evaluator

```bash
python examples/train_hypernix_0_1_5_evaluator.py --out-dir ./eval
```

Synthesizes a judge-training corpus with `mediocre_fridge`, freezes
embeddings with `old_fridge`, trains via `oven.train`, reloads with the
other oven, plots the loss curve with `new_fridge`. Self-contained
smoke test for every subsystem.

## Python API tour

```python
import hypernix
from hypernix import freezer, old_oven, old_fridge, mediocre_fridge, new_fridge

# 1) Auto-pick a VRAM strategy.  On a GTX 1080 this returns OldFreezer(fp16);
#    on a 3090 it returns NewFreezer(fp32 / bf16 on Ampere).
fz = freezer.flash_freezer(base=freezer.auto_freezer(), slow=True)

# 2) Preheat an oven from a short name (downloads on first call).
oven = old_oven.preheat(repo_id="nix2.5", device="cuda", dtype="float16")

# 3) Memory hygiene.
old_fridge.freeze(oven.model, patterns=("embed_tokens",))
print(old_fridge.parameter_stats(oven.model))

# 4) Training data.
dataset = mediocre_fridge.synthesize_judge_corpus(n=1024, out_path="judge.txt")

# 5) Train inside a FlashFreezer so OOMs don't blow up the run.
fz.guard(lambda: oven.train(dataset, "./trained", steps=500, batch_size=1))

# 6) Graph.
import pathlib
log = pathlib.Path("./trained/train.log").read_text()
new_fridge.plot_loss_curve(new_fridge.parse_training_log(log), "loss.png")
```

## CLI reference

```
hypernix <subcommand> [options]

  all                   download -> convert -> [quantize]   (default)
  download              fetch a HuggingFace snapshot
  convert               produce fp32 / fp16 GGUF from a snapshot
  quantize              run llama-quantize on an fp16 / fp32 GGUF
  verify                read-validate a GGUF and print headers
  info                  package + optional GGUF header summary
  upload                push files to a HuggingFace repo
  doctor                environment diagnostic  (pass --fix to install deps)
  fetch-llama-quantize  pre-seed the llama-quantize cache
  train init            create a fresh HyperNix snapshot
  train expand          warm-start a bigger model from a smaller one
  train run             minimal causal-LM training loop
  generate              sample text from a local snapshot
  oven                  code-generation wrapper (preheat + complete / fill)
  chat                  interactive chat REPL against any supported model
```

Quant aliases accepted by `--quants` and `hypernix quantize`:

| Alias | llama.cpp enum |
|---|---|
| `fp32`, `f32` | F32 |
| `fp16`, `f16` | F16 |
| `q8`, `q8_0` | Q8_0 |
| `q6`, `q6_k` | Q6_K |
| `q4km`, `q4_k_m` | Q4_K_M |
| `q5km`, `q5_k_m` | Q5_K_M |

## Supported model families

### Short names (CLI & Python)

Pass any of these to `hypernix chat --repo-id`, `old_oven.preheat`,
`download_model`, etc.

| Family | Short names |
|---|---|
| **HyperNix** | `hyper-nix.1`, `hyper-nix`, `hypernix`, `nano-nano-v4`, `nano-mini-6.99-v2`, `nano-nano-927-v3` |
| **Nix** (ray0rf1re/nix collection) | `nix`, `nix2.5`, `nix2.6-m`, `nix2.6-mm`, `nix-2.7a`, `nix2.7`, `nix2.6` |
| **Llama 3.x** | `llama-3.1-8b`, `llama-3.1-8b-instruct`, `llama-3.2-1b`, `llama-3.2-3b`, `llama-3.3-70b-instruct` |
| **Qwen 2.5 / 3 / 3.5 / 3.6** | `qwen2.5-*`, `qwen3-0.6b`, `qwen3-8b`, `qwen3.5-{0.8b,2b,4b,9b,27b,35b-a3b,122b-a10b,397b-a17b}`, `qwen3.6-35b-a3b` |
| **Gemma 2 / 3 / 4** | `gemma-2-{2b,9b,27b}`, `gemma-3-{1b,4b}`, `gemma-4-{e2b,e4b,26b-a4b,31b}` |
| **Phi 3 / 3.5 / 4** | `phi-3-mini`, `phi-3.5-mini`, `phi-4` |
| **DeepSeek** | `deepseek-r1-distill-llama-8b`, `deepseek-r1-distill-qwen-7b`, `deepseek-v2-lite`, `deepseek-v3` |
| **GLM 4 / 5 / 5.1** | `glm-4-9b-chat`, `glm-4.1v`, `glm-5`, `glm-5.1`, `glm-5.1-fp8` |
| **Mistral / Mixtral** | `mistral-7b-instruct`, `mixtral-8x7b-instruct` |
| **NVIDIA** | `nemotron-4-15b`, `llama-3.1-nemotron-70b-instruct`, `mistral-nemo-12b` |
| **OpenAI gpt-oss** | `gpt-oss-20b`, `gpt-oss-120b` |

The full registry lives in `hypernix.KNOWN_MODELS`.

### ARCH_PRESETS (seeds for `new_oven`)

`new_oven(arch="...", ...)` spins a fresh, parametric model in the
shape of any of these families:

- `hypernix`, `llama`, `llama3`, `llama3.1`, `llama3.2`, `llama3.3`, `llama4`
- `qwen2`, `qwen2.5`, `qwen3`, `qwen3.5`, `qwen3.6`
- `gemma`, `gemma2`, `gemma3`, `gemma4`
- `mistral`, `phi3`, `phi4`
- `glm4`, `glm5`, `glm5.1`
- `deepseek`, `deepseek-r1`, `nemotron`, `gpt-oss` / `gptoss`
- `nix`, `nix2`

Presets are seeds for brand-new parametric models. **Loading** a
pretrained checkpoint for any of these families works without a matching
preset because non-HyperNix `model_type` values route through
`transformers.AutoModelForCausalLM`.

## Examples

- [`examples/quickstart.py`](examples/quickstart.py) — 5-line Python API demo.
- [`examples/custom_arch.py`](examples/custom_arch.py) — arbitrary-size HyperNix.
- [`examples/upload_to_hub.py`](examples/upload_to_hub.py) — publish to the Hub.
- [`examples/train_hypernix_0_1_5_evaluator.py`](examples/train_hypernix_0_1_5_evaluator.py) — tiny evaluator demo wiring ovens + all three fridges.
- [`examples/train_hypernix_1_5_gtx1080.py`](examples/train_hypernix_1_5_gtx1080.py) — production-shape 92.1 M model trained on an 8 GB Pascal card.

## Wiki / deep dives

Topic-focused reference guides live in the `wiki/` directory:

- [`wiki/Home.md`](wiki/Home.md) — index
- [`wiki/Ovens.md`](wiki/Ovens.md) — `old_oven` / `new_oven` reference
- [`wiki/Fridges.md`](wiki/Fridges.md) — `old_fridge` / `mediocre_fridge` / `new_fridge`
- [`wiki/Ranges.md`](wiki/Ranges.md) — `new_range` / `old_range` / `industrial_range` (labeling rubrics)
- [`wiki/Freezer.md`](wiki/Freezer.md) — VRAM manager (OldFreezer / NewFreezer / FlashFreezer)
- [`wiki/Alarms.md`](wiki/Alarms.md) — smoke alarms (Rads / Gas / Modern / Auto) + CPU / GPU preset tables
- [`wiki/Kitchen.md`](wiki/Kitchen.md) — pans / microwave / table / sink / instant pot / coffee maker / pressure cooker
- [`wiki/Pascal.md`](wiki/Pascal.md) — CUDA 6.1 / GTX 1080 playbook
- [`wiki/Architectures.md`](wiki/Architectures.md) — ARCH_PRESETS and KNOWN_MODELS
- [`wiki/Training.md`](wiki/Training.md) — scratch training, expansion, and fine-tuning flows
- [`wiki/CLI.md`](wiki/CLI.md) — full CLI cheat sheet
- [`wiki/Quantization.md`](wiki/Quantization.md) — GGUF conversion + k-quant pipeline
- [`wiki/Changelog.md`](wiki/Changelog.md) — full per-release version history

## How the GGUF pipeline works

1. `huggingface_hub.snapshot_download` pulls weights + tokenizer files.
2. The converter loads the state dict, infers dimensions from tensor
   shapes (so any HyperNix size works), and maps tensor names onto
   llama.cpp's canonical GGUF layout when a recognizable pattern matches
   (Llama, GPT-NeoX, GPT-2, nanoGPT). Unknown names round-trip verbatim.
3. `llama-quantize` consumes the fp16 GGUF to produce each k-quant.

The CLI emits exactly one fp16 intermediate and reuses it for every
k-quant in the plan.

## Platform notes

- **Linux**: full support, every distro tested on: (Ubuntu, Debian, Arch.)
- **macOS**: Metal for inference, Homebrew for `llama-quantize`. (untested)
- **Windows**: native support; doctor accepts Windows; `llama-quantize` auto-downloads Windows binaries; use scoop / chocolatey for system deps. (untested)
- **Pascal (GTX 1080 / 1080 Ti / Titan Xp)**: install torch from the CUDA 11.8 index first (see above). Use `OldFreezer` or `auto_freezer()`; `pascal_safe_dtype()` picks fp16. `hypernix.freezer.pascal_mode_hints()` returns the full Pascal cheat sheet.

## Build / release

```bash
pip install build twine
python -m build
twine check --strict dist/*
```

Release tags (`vX.Y.Z`) fire `.github/workflows/release.yml` which
publishes to PyPI via Trusted Publishing and attaches the wheel +
sdist + an `examples-scripts` tarball + `SHA256SUMS` to a GitHub
Release.

## License

Apache-2.0.
