# Convert — `hypernix.convert`

Converts a HyperNix (or HF-shaped) PyTorch checkpoint directory to an
uncompressed GGUF file at fp32 or fp16 precision. Architecture-agnostic:
discovers block count, hidden size, and FFN width from tensor shapes, so
it works for any checkpoint regardless of depth/width. For k-quants
(Q4_K_M etc.), run [`hypernix quantize`](Quantization.md) on the fp32/fp16
output afterward.

## `convert_to_gguf()`

```python
from hypernix.convert import convert_to_gguf

gguf_path = convert_to_gguf(
    model_dir="~/.cache/hypernix/models/hyper-Nix.2",
    output="hyper-nix-2.f16.gguf",
    dtype="fp16",
    arch_name="hypernix",
    name="HyperNix",
)
```

| Arg | Type | Default | Notes |
|---|---|---|---|
| `model_dir` | `Path \| str` | required | Local HF-style snapshot directory. |
| `output` | `Path \| str` | required | Destination GGUF path; parent dirs created automatically. |
| `dtype` | `str` | `"fp16"` | Only `"fp32"`/`"f32"`/`"fp16"`/`"f16"` accepted — `ValueError` otherwise (with a pointer to `quantize_gguf` for k-quants). |
| `arch_name` | `str` | `"hypernix"` | GGUF architecture id written into metadata. |
| `name` | `str` | `"HyperNix"` | Model display name. |
| `n_head_hint` | `int \| None` | `None` | Overrides the attention-head-count heuristic. |
| `context_length` | `int \| None` | `None` | Overrides the sequence-length metadata. |

### Weight loading (`_collect_state_dict`)

Tries, in order: sharded safetensors (`model.safetensors.index.json` +
shards), single `model.safetensors`, any other `*.safetensors` glob,
sharded `pytorch_model.bin.index.json` + shards, single
`pytorch_model.bin`, then loose `*.pt`/`*.pth`/`*.bin` files (unwrapping
a `{"state_dict": ...}` or `{"model": ...}` wrapper if present). Raises
`FileNotFoundError` if none of these patterns match anything.

### Config / hyperparameter resolution

Reads `config.json` (best-effort — returns `{}` on parse failure rather
than raising) and fills in gaps from `infer_arch()` (from
`hypernix.arch`) applied to the actual tensor shapes:

| GGUF field | Sourced from (in priority order) |
|---|---|
| `n_layers` | `config.num_hidden_layers` → inferred |
| `n_embd` | `config.hidden_size` → inferred |
| `n_head` | `config.num_attention_heads` → inferred → `1` |
| `n_head_kv` | `config.num_key_value_heads` → `n_head` (no GQA config = assume MHA) |
| `n_ff` | `config.intermediate_size` → inferred → `4 * n_embd` |
| `vocab_size` | `config.vocab_size` → inferred → `0` |
| `ctx_len` | `context_length` arg → `config.max_position_embeddings` → `config.n_positions` → `2048` |
| `rms_eps` | `config.rms_norm_eps` → `config.layer_norm_epsilon` → `1e-5` |
| `rope_theta` | `config.rope_theta` → `10000.0` |

### Tokenizer embedding (`_load_tokenizer_tokens`)

Best-effort, so the GGUF is self-contained (no separate tokenizer file
needed at inference time). Tries, in order:
1. `tokenizer.json` (BPE) — extracts vocab + merges. HF `tokenizer.json`
   v2+ stores merges as `[["a","b"], ...]`; converted to llama.cpp's
   flat `"a b"` string format.
2. `tokenizer.model` (SentencePiece, via the `sentencepiece` package) —
   extracts pieces, scores, and types. Returns `None` on any exception
   (missing package, corrupt file, etc.).
3. `vocab.txt` (WordPiece) — one token per line.

For BPE tokenizers, also sets `tokenizer.ggml.pre = "default"` —
required by llama.cpp 2024+ loaders, otherwise they fail with `invalid
GGUF type 9` on the merges field. Uses `writer.add_tokenizer_pre()` if
available, falling back to a raw `writer.add_string()` call for older
`gguf` package versions without that method.

### Tensor writing

Iterates tensors via `hypernix.arch.iter_state_dict_names` +
`map_tensor_name` (renaming HF-style keys to GGUF's naming convention).
**Token/output embeddings and all `*_norm` tensors are always kept in
F32**, even when `dtype="fp16"` — preserves accuracy on the
rarely-referenced tables while still shrinking the bulk of the weights.
Progress shown via `tqdm`.

### Required modules

- `numpy`, `torch`, `gguf` (`GGUFWriter`, `GGMLQuantizationType`), `tqdm` — hard dependencies
- `safetensors.torch` — lazy, only if safetensors weights are present
- `sentencepiece` — lazy, only for SentencePiece tokenizers
- `hypernix.arch` (`ArchInfo`, `infer_arch`, `iter_state_dict_names`, `map_tensor_name`) — internal
- Standard library: `json`, `collections.abc`, `pathlib`, `typing`

---

## See also

- [Download](Download.md) — produces the snapshot directory this module consumes
- [Quantization](Quantization.md) — the k-quant step that typically follows `convert_to_gguf`
- [Architectures](Architectures.md) — `infer_arch` / tensor-name mapping internals
