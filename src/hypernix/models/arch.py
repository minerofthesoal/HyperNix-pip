"""Architecture-agnostic tensor name mapping for custom HyperNix-style models.

The HyperNix family is described upstream as a "custom architecture" causal LM
without a fixed ``transformers`` class. We therefore avoid hard-coding layer
counts, hidden sizes, or attention-head counts: every parameter is introspected
from the state dict and remapped onto llama.cpp's canonical GGUF tensor names
when a recognizable pattern is found.

Tensors that do not match a known pattern are still emitted under their
original name so downstream tooling can round-trip arbitrarily shaped models.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

# Canonical GGUF tensor names (see gguf.constants.MODEL_TENSOR).
TOK_EMBD = "token_embd.weight"
OUTPUT_NORM = "output_norm.weight"
OUTPUT = "output.weight"

# Per-block templates.
BLK = "blk.{i}."
ATTN_NORM = BLK + "attn_norm.weight"
ATTN_Q = BLK + "attn_q.weight"
ATTN_K = BLK + "attn_k.weight"
ATTN_V = BLK + "attn_v.weight"
ATTN_QKV = BLK + "attn_qkv.weight"
ATTN_OUT = BLK + "attn_output.weight"
FFN_NORM = BLK + "ffn_norm.weight"
FFN_GATE = BLK + "ffn_gate.weight"
FFN_UP = BLK + "ffn_up.weight"
FFN_DOWN = BLK + "ffn_down.weight"


# Regex patterns for common naming conventions we've encountered across PyTorch
# reference implementations (HF style, nanoGPT style, llama-style, gpt-neox).
_LAYER_PREFIXES = [
    r"model\.layers\.(?P<i>\d+)\.",
    r"transformer\.h\.(?P<i>\d+)\.",
    r"layers\.(?P<i>\d+)\.",
    r"blocks\.(?P<i>\d+)\.",
    r"block\.(?P<i>\d+)\.",
    r"h\.(?P<i>\d+)\.",
]

# Tail regex (without layer prefix) -> canonical template.
_PER_BLOCK_RULES: list[tuple[str, str]] = [
    # norms
    (r"input_layernorm\.weight$", ATTN_NORM),
    (r"attention_norm\.weight$", ATTN_NORM),
    (r"ln_1\.weight$", ATTN_NORM),
    (r"norm1\.weight$", ATTN_NORM),
    (r"attn_norm\.weight$", ATTN_NORM),
    (r"post_attention_layernorm\.weight$", FFN_NORM),
    (r"ffn_norm\.weight$", FFN_NORM),
    (r"ln_2\.weight$", FFN_NORM),
    (r"norm2\.weight$", FFN_NORM),
    # attention projections (separate q/k/v)
    (r"(?:self_attn|attention|attn)\.q_proj\.weight$", ATTN_Q),
    (r"(?:self_attn|attention|attn)\.k_proj\.weight$", ATTN_K),
    (r"(?:self_attn|attention|attn)\.v_proj\.weight$", ATTN_V),
    (r"(?:self_attn|attention|attn)\.wq\.weight$", ATTN_Q),
    (r"(?:self_attn|attention|attn)\.wk\.weight$", ATTN_K),
    (r"(?:self_attn|attention|attn)\.wv\.weight$", ATTN_V),
    # fused qkv
    (r"(?:self_attn|attention|attn)\.(?:qkv_proj|Wqkv|qkv|c_attn)\.weight$", ATTN_QKV),
    # attention output
    (r"(?:self_attn|attention|attn)\.(?:o_proj|out_proj|wo|c_proj|dense)\.weight$", ATTN_OUT),
    # MLP
    (r"(?:mlp|feed_forward|ffn)\.(?:gate_proj|w1)\.weight$", FFN_GATE),
    (r"(?:mlp|feed_forward|ffn)\.(?:up_proj|w3|c_fc|fc_in|fc1)\.weight$", FFN_UP),
    (r"(?:mlp|feed_forward|ffn)\.(?:down_proj|w2|c_proj|fc_out|fc2)\.weight$", FFN_DOWN),
]

# Top-level (non-per-block) rules.
_TOP_LEVEL_RULES: list[tuple[str, str]] = [
    (r"^(?:model\.)?(?:tok_embeddings|embed_tokens|wte|embeddings?\.word_embeddings)\.weight$", TOK_EMBD),
    (r"^(?:model\.)?(?:norm|ln_f|final_layernorm|output_norm)\.weight$", OUTPUT_NORM),
    (r"^(?:lm_head|output|embed_out)\.weight$", OUTPUT),
]


@dataclass
class ArchInfo:
    """Dimensions inferred from the state dict."""

    n_layers: int = 0
    n_embd: int = 0
    n_head: int = 0
    n_head_kv: int = 0
    n_ff: int = 0
    vocab_size: int = 0
    layer_indices: list[int] = field(default_factory=list)
    tied_embeddings: bool = False


def _match_layer_index(name: str) -> tuple[int, str] | None:
    for pat in _LAYER_PREFIXES:
        m = re.match(pat, name)
        if m:
            return int(m.group("i")), name[m.end() :]
    return None


def map_tensor_name(name: str) -> str | None:
    """Map a PyTorch parameter name to a GGUF tensor name.

    Returns ``None`` if no canonical mapping applies — the caller may still
    emit the tensor under its original name.
    """
    for pat, canonical in _TOP_LEVEL_RULES:
        if re.match(pat, name):
            return canonical
    hit = _match_layer_index(name)
    if hit is None:
        return None
    idx, tail = hit
    for pat, template in _PER_BLOCK_RULES:
        if re.fullmatch(pat, tail):
            return template.format(i=idx)
    return None


def infer_arch(
    state_dict: dict[str, object],
    hint_n_head: int | None = None,
) -> ArchInfo:
    """Inspect tensor shapes to infer basic architectural dimensions.

    Works for any layer count / hidden size. Heads default to a sensible guess
    if not discoverable (hidden_size // 64, clamped to >= 1).
    """

    info = ArchInfo()
    layer_ids: set[int] = set()
    ffn_dim: int | None = None
    hidden: int | None = None
    vocab: int | None = None

    for name, tensor in state_dict.items():
        if not hasattr(tensor, "shape"):
            continue
        shape = tuple(tensor.shape)
        hit = _match_layer_index(name)
        if hit is not None:
            layer_ids.add(hit[0])
        lower = name.lower()
        if "embed" in lower and "weight" in lower and len(shape) == 2:
            vocab, hidden = shape[0], shape[1]
        elif lower.endswith("lm_head.weight") and len(shape) == 2:
            vocab = vocab or shape[0]
            hidden = hidden or shape[1]
        if len(shape) == 2 and ("gate_proj" in lower or "up_proj" in lower or ".w1." in lower or ".w3." in lower or "fc1" in lower or "fc_in" in lower):
            ffn_dim = max(ffn_dim or 0, shape[0])

    info.layer_indices = sorted(layer_ids)
    info.n_layers = (max(layer_ids) + 1) if layer_ids else 0
    info.n_embd = int(hidden or 0)
    info.vocab_size = int(vocab or 0)
    info.n_ff = int(ffn_dim or (4 * info.n_embd if info.n_embd else 0))
    if hint_n_head is not None and hint_n_head > 0:
        info.n_head = hint_n_head
    elif info.n_embd:
        guess = info.n_embd // 64
        info.n_head = max(1, guess)
    info.n_head_kv = info.n_head
    return info


def iter_state_dict_names(state_dict_keys: Iterable[str]) -> list[str]:
    """Return the list of keys in stable sorted order for deterministic output."""
    return sorted(state_dict_keys)
