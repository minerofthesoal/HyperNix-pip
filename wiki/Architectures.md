# Architectures — `ARCH_PRESETS` & `KNOWN_MODELS`

`hypernix` ships two registries. They solve different problems:

| Registry | Keys are | Values hold | Used by |
|---|---|---|---|
| `KNOWN_MODELS` | short names (`"nix2.5"`, `"gemma-4-e4b"`) | `ModelInfo(repo_id, arch, notes)` | `download_model`, `old_oven.preheat`, `hypernix chat` |
| `ARCH_PRESETS` | arch names (`"qwen2.5"`, `"gemma4"`, `"nix"`) | dict of config knobs | `new_oven(arch=...)` |

**`KNOWN_MODELS` resolves short names for *loading* pretrained
checkpoints.** You never need an ARCH_PRESET to load a pretrained
model — non-HyperNix `model_type` values route through
`transformers.AutoModelForCausalLM`.

**`ARCH_PRESETS` is for *building* a fresh parametric model** in the
shape of a known family. `new_oven(arch="qwen3.5", hidden_size=..., ...)`
stamps out an untrained model with the Qwen 3.5 config knobs set
correctly (rope_theta=1e7, tied embeddings, no qkv bias).

## `ARCH_PRESETS`

```python
from hypernix import ARCH_PRESETS

ARCH_PRESETS["gemma4"]
# {"attention_bias": False,
#  "model_type": "llama",       # runtime class we use for this shape
#  "rope_theta": 1_000_000.0,
#  "rms_norm_eps": 1e-6,
#  "tie_word_embeddings": True}
```

Full list at v0.41:

**HyperNix**
- `hypernix`

**Llama**
- `llama` — Llama 2 defaults (rope_theta=10k, untied)
- `llama3` / `llama3.1` / `llama3.3` / `llama4` — rope_theta=500k, untied
- `llama3.2` — rope_theta=500k, **tied** (small 1B/3B variants)

**Qwen**
- `qwen2` / `qwen2.5` — Qwen2 shape, attention_bias=True, rope_theta=1M, tied
- `qwen3` — Qwen3 shape, attention_bias=False, rope_theta=1M, tied
- `qwen3.5` — rope_theta=**10M**, tied
- `qwen3.6` — rope_theta=10M, **untied** (MoE)

**Mistral / Nemotron**
- `mistral` — attention_bias=False, rope_theta=1M
- `nemotron` — Llama-shape, rope_theta=500k

**Gemma**
- `gemma` / `gemma2` — Llama-backed, rope_theta=10k, tied
- `gemma3` — rope_theta=1M, tied
- `gemma4` — rope_theta=1M, tied (matches Gemma4ForConditionalGeneration)

**Phi**
- `phi3` — rope_theta=10k, untied
- `phi4` — rope_theta=**250k**, untied

**GLM**
- `glm4` — Qwen2-backed (has qkv bias), untied
- `glm5` / `glm5.1` — Llama-backed, rope_theta=1M, untied

**DeepSeek**
- `deepseek` / `deepseek-r1` — Llama-backed R1-distill shape

**OpenAI / Nix**
- `gpt-oss` / `gptoss` — Llama-backed, rope_theta=500k
- `nix` / `nix2` — Qwen2-backed, **no qkv bias** (unlike stock Qwen2), tied

### `model_type` inside presets

Because HyperNix implements Llama and Qwen2 natively, every preset
`model_type` is one of `"hypernix"`, `"llama"`, `"qwen2"`, or
`"mistral"` — the four arches the `HyperNixModel` class can realize
directly. Presets for other families (Gemma, Phi, GLM, Nemotron, etc.)
pick whichever of those four backs their shape most closely:

- bf16-friendly, no qkv bias → `"llama"`
- needs qkv bias (like GLM4) → `"qwen2"`
- exactly Mistral's conventions → `"mistral"`

This is why, for example, `ARCH_PRESETS["gemma4"]["model_type"]` is
`"llama"`. It's the runtime-class proxy, not the HF-side `model_type`.

## `KNOWN_MODELS`

```python
from hypernix import KNOWN_MODELS, resolve_repo_id, resolve_model_info

resolve_repo_id("nix2.5")          # -> "ray0rf1re/Nix2.5"
resolve_model_info("gemma-4-e4b")  # -> ModelInfo(repo_id="google/gemma-4-E4B-it",
                                   #             arch="auto",
                                   #             notes="Gemma 4 E4B it …")
```

Key sections (see the source for the full list — 60+ entries at v0.41):

### HyperNix native
`hyper-nix.1`, `hyper-nix`, `hypernix`, `nano-nano-v4`, `nano-nano`,
`nano-mini-6.99-v2`, `nano-mini`, `nano-nano-927-v3`, `nano-nano-927`

### Nix (ray0rf1re/nix collection, Qwen2-shape)
`nix`, `nix2.5`, `nix2.6`, `nix2.6-m`, `nix2.6-mm`, `nix-2.7a`, `nix2.7`

### Llama 3.x (gated)
`llama-3.1-8b`, `llama-3.1-8b-instruct`, `llama-3.2-1b`, `llama-3.2-3b`,
`llama-3.3-70b-instruct`

### Qwen 2.5 / 3 / 3.5 / 3.6
`qwen2.5-0.5b`, `qwen2.5-7b`, `qwen2.5-7b-instruct`, `qwen2.5-coder-7b`,
`qwen3-0.6b`, `qwen3-8b`,
`qwen3.5-0.8b`, `qwen3.5-2b`, `qwen3.5-4b`, `qwen3.5-9b`,
`qwen3.5-27b`, `qwen3.5-35b-a3b`, `qwen3.5-122b-a10b`, `qwen3.5-397b-a17b`,
`qwen3.6-35b-a3b`

### Gemma 2 / 3 / 4
`gemma-2-2b`, `gemma-2-9b`, `gemma-2-27b`,
`gemma-3-1b`, `gemma-3-4b`,
`gemma-4-e2b`, `gemma-4-e4b`, `gemma-4-26b-a4b`, `gemma-4-31b`

### Phi
`phi-3-mini`, `phi-3.5-mini`, `phi-4`

### DeepSeek
`deepseek-r1-distill-llama-8b`, `deepseek-r1-distill-qwen-7b`,
`deepseek-v2-lite`, `deepseek-v3`

### GLM
`glm-4-9b-chat`, `glm-4.1v`, `glm-5`, `glm-5.1`, `glm-5.1-fp8`

### Mistral / NVIDIA / gpt-oss
`mistral-7b-instruct`, `mixtral-8x7b-instruct`,
`nemotron-4-15b`, `llama-3.1-nemotron-70b-instruct`, `mistral-nemo-12b`,
`gpt-oss-20b`, `gpt-oss-120b`

### `arch="auto"` vs native

`ModelInfo.arch == "auto"` means the loader will use
`transformers.AutoModelForCausalLM`. This is correct for model types
without a native HyperNixModel implementation (`gemma4`, `qwen3_5`,
`qwen3_5_moe`, `glm_moe_dsa`, `phi3`, …). The other values
(`"hypernix"`, `"llama"`, `"qwen2"`, `"mistral"`) pick the matching
native path.

## Adding new entries

`KNOWN_MODELS` lives in
[`src/hypernix/download.py`](../src/hypernix/download.py).
`ARCH_PRESETS` lives in
[`src/hypernix/old_oven.py`](../src/hypernix/old_oven.py). Both are plain
Python dicts — add an entry, run the tests, open a PR.

For a KNOWN_MODELS entry, confirm the HF repo with a quick
`huggingface_hub.snapshot_download(..., allow_patterns=["config.json"])`
and make sure the `arch` string matches what `load_snapshot` will do
with it (`"auto"` for unfamiliar model_types).

For an ARCH_PRESET, verify against the official config.json on the
Hub: `rope_theta`, `rms_norm_eps`, `tie_word_embeddings`,
`attention_bias` are the four knobs that matter.
