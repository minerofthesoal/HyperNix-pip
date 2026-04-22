# Quantization — the GGUF pipeline

The original reason `hypernix` exists: take a PyTorch snapshot of the
`ray0rf1re/hyper-nix.1` family and emit GGUF files that `llama.cpp`,
`ollama`, LM Studio, and friends can load directly.

## The pipeline, in three stages

```
    HF snapshot           fp16 GGUF             q-quant GGUFs
  (config.json +       (llama.cpp native)      (Q8_0 / Q6_K /
   model.safetensors)                           Q4_K_M / Q5_K_M)
         │                      │                     │
         │  convert_to_gguf     │  quantize_gguf     │
         └──────────────────────┴─────────────────────┘
```

Each stage is one library call and one CLI flag:

```bash
# all stages in one go (default: just fp32 + fp16)
hypernix --repo-id ray0rf1re/hyper-nix.1 --output-dir ./out \
    --quants fp32 fp16 q8_0 q6_k q4_k_m
```

```python
from hypernix import download_model, convert_to_gguf, quantize_gguf

snap = download_model("ray0rf1re/hyper-nix.1")
fp16 = convert_to_gguf(snap, "hn-fp16.gguf", dtype="fp16")
q4   = quantize_gguf(fp16, "hn-q4_k_m.gguf", "q4_k_m")
q6   = quantize_gguf(fp16, "hn-q6_k.gguf",   "q6_k")
q8   = quantize_gguf(fp16, "hn-q8_0.gguf",   "q8_0")
```

## `convert_to_gguf`

Architecture-agnostic. It reads the state dict directly, infers all
dimensions from tensor shapes, and maps HF tensor names onto
llama.cpp's canonical GGUF layout when a recognizable pattern
matches (Llama, GPT-NeoX, GPT-2, nanoGPT). Unknown names round-trip
verbatim so the output is always loadable somewhere downstream.

```python
convert_to_gguf(
    model_dir="./snapshot",
    output="./out-fp16.gguf",
    dtype="fp16",                 # or "fp32"
    arch_name="hypernix",         # sets "general.architecture"
    name="HyperNix",              # display name in the header
    n_head_hint=None,             # override head count if config is wrong
    context_length=None,          # override context length
)
```

No llama.cpp installation needed for this stage — it uses the
pure-Python `gguf` library. Produces fp32 or fp16 tensors.

## `quantize_gguf`

Drives the `llama-quantize` binary. Accepts any k-quant supported by
the upstream:

| Alias | llama.cpp enum | Typical use |
|---|---|---|
| `fp32` / `f32` | F32 | Reference / debugging |
| `fp16` / `f16` | F16 | Default intermediate |
| `q8` / `q8_0` | Q8_0 | Small model, near-lossless |
| `q6` / `q6_k` | Q6_K | Balanced accuracy/size |
| `q4km` / `q4_k_m` | Q4_K_M | Most common small-GPU choice |
| `q5km` / `q5_k_m` | Q5_K_M | A notch above Q4_K_M |

### `llama-quantize` binary resolution

In priority order:

1. Explicit `--llama-quantize /path/to/bin`
2. `llama-quantize` on `PATH`
3. `llama.cpp` bundled with `pip install "hypernix[llama-cpp]"`
4. System package manager locations:
   - Arch: `/usr/bin/llama-quantize`
   - Fedora: `/usr/bin/llama-quantize`
   - openSUSE: `/usr/bin/llama-quantize`
   - Homebrew (macOS): `/opt/homebrew/bin/llama-quantize`
   - Windows: `scoop install llama.cpp` → `~/scoop/apps/llama.cpp/current/bin/`
5. Auto-download from the upstream
   [`ggml-org/llama.cpp`](https://github.com/ggml-org/llama.cpp/releases)
   release to `~/.cache/hypernix/bin/` (CPU-only binary, CUDA variants
   available under other asset names).

Disable auto-download with `--no-auto-fetch`, pre-seed the cache with
`hypernix fetch-llama-quantize`, or provide `--llama-quantize` explicitly.

### The `--auto` flag

```bash
hypernix quantize --source hn-fp16.gguf --output hn-q4.gguf \
                  --type q4_k_m --auto
```

Adds two fallbacks on top of the normal resolution:

- Walks back through the latest N `llama.cpp` releases if the newest
  release has no asset for your OS / CPU variant.
- Falls back to `pip install llama-cpp-python` (which ships a bundled
  `llama-quantize`) if every GitHub fetch fails.

## `verify` and `info`

```bash
hypernix verify hn-q4_k_m.gguf
hypernix verify hn-q4_k_m.gguf --tensors     # also list tensors

hypernix info --gguf hn-q4_k_m.gguf          # package + GGUF headers
```

`verify` parses the GGUF header with the `gguf` library and prints
fields + tensor metadata. Use it as a CI guard to catch corrupted
downloads; the exit code is non-zero if parsing fails.

## `upload`

```bash
HF_TOKEN=hf_xxx hypernix upload \
    --repo-id ray0rf1re/HyperNix.1-gguf \
    ./hn-q4_k_m.gguf ./hn-q6_k.gguf ./hn-q8_0.gguf
```

Or as part of `hypernix all`:

```bash
hypernix --repo-id ray0rf1re/hyper-nix.1 --output-dir ./out \
    --quants fp32 fp16 q8_0 q6_k q4_k_m \
    --upload-to ray0rf1re/HyperNix.1-gguf
```

Uses `huggingface_hub.HfApi.upload_folder` under the hood.

## Common gotchas

**"huggingface-hub not found"** — the lazy import failed. `pip install
huggingface-hub>=0.24`; it's a core dep of hypernix so this shouldn't
happen on a clean install.

**GGUF won't load in llama.cpp** — check the
`general.architecture` string with `hypernix verify`. llama.cpp only
knows certain architecture strings; if you built a custom shape with
`new_oven` and called it `"my-arch"`, the GGUF will still write but
llama.cpp will reject it. Use `--arch llama` or `--arch hypernix` when
converting.

**Out-of-memory during quantization** — `llama-quantize` loads the
whole fp16 tensor into RAM for each quantization pass. On a 32 GB
box the largest model you can quantize in one shot is roughly 13 B
params (the tensor in fp16 alone is 26 GB). Use a box with more RAM
or a split-file GGUF.

**Laptop-grade quantization** — `scripts/quantize_i7_7660u.sh` caps
BLAS/OpenMP to 4 threads, runs at reduced CPU + I/O priority when
`nice` / `ionice` are available, and only keeps one fp16 intermediate
on disk. Good reference for tuning your own small-box pipeline.
