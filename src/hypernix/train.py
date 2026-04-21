"""Train or scale up HyperNix models.

Two common flows are supported:

* **Scratch training** — build a new HyperNix-style causal LM at an
  arbitrary size (same as v1, wider, deeper, or a custom shape) and
  pretrain from a raw-text corpus.
* **Model expansion** — take an existing HyperNix checkpoint and grow it
  wider and/or deeper, warm-starting the new weights from the small-model
  weights so you keep the pretraining signal.

Both flows write a HuggingFace-style snapshot directory
(``config.json`` + ``model.safetensors`` + optional tokenizer files), so
the output feeds straight back into :func:`hypernix.convert_to_gguf` or
the ``hypernix convert`` CLI.

The goal is a small but runnable scaffold — not a replacement for a
full-featured trainer. DeepSpeed / FSDP / multi-node are out of scope.
"""
from __future__ import annotations

import json
import math
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F
from safetensors.torch import load_file, save_file

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class HyperNixConfig:
    """HyperNix model shape. Same layout as v1, parametric in every axis."""

    vocab_size: int = 32000
    hidden_size: int = 1024
    intermediate_size: int = 4096
    num_hidden_layers: int = 16
    num_attention_heads: int = 16
    num_key_value_heads: int | None = None
    max_position_embeddings: int = 2048
    rope_theta: float = 10000.0
    rms_norm_eps: float = 1e-5
    tie_word_embeddings: bool = False
    # Qwen2/Qwen2.5 put a bias on q_proj/k_proj/v_proj (but never o_proj);
    # HyperNix-native and Llama-style configs leave this False. The HF
    # Qwen2 model expects this to be True.
    attention_bias: bool = False
    model_type: str = "hypernix"
    # RoPE convention:
    #   "interleaved" - GPT-NeoX / HyperNix-native (cos/sin pairs over ::2/1::2).
    #   "half-rotate" - HuggingFace Llama / Qwen2 (first half vs second half).
    # Loading an HF Llama checkpoint (model_type="llama") uses "half-rotate";
    # loading a HyperNix snapshot uses "interleaved".
    rope_style: str = "interleaved"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if d["num_key_value_heads"] is None:
            d["num_key_value_heads"] = self.num_attention_heads
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HyperNixConfig:
        # Normalize HF Llama "rope_parameters": {"rope_theta": ..., ...} dict
        # to the flat rope_theta our dataclass expects.
        d = dict(d)
        if "rope_parameters" in d and isinstance(d["rope_parameters"], dict):
            rp = d["rope_parameters"]
            if "rope_theta" in rp and "rope_theta" not in d:
                d["rope_theta"] = rp["rope_theta"]
        # Infer rope_style from model_type when the caller didn't supply one.
        if "rope_style" not in d:
            d["rope_style"] = _default_rope_style(d.get("model_type", "hypernix"))
        fields = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**fields)

    @classmethod
    def from_json(cls, path: Path | str) -> HyperNixConfig:
        return cls.from_dict(json.loads(Path(path).read_text()))

    @property
    def head_dim(self) -> int:
        return self.hidden_size // self.num_attention_heads

    @property
    def n_kv_head(self) -> int:
        return self.num_key_value_heads or self.num_attention_heads


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class RMSNorm(nn.Module):
    def __init__(self, hidden_size: int, eps: float = 1e-5) -> None:
        super().__init__()
        self.weight = nn.Parameter(torch.ones(hidden_size))
        self.eps = eps

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        dtype = x.dtype
        x = x.float()
        norm = x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps)
        return (self.weight * norm).to(dtype)


def _rope_cache(seq_len: int, head_dim: int, theta: float, device, dtype) -> tuple[torch.Tensor, torch.Tensor]:
    inv_freq = 1.0 / (theta ** (torch.arange(0, head_dim, 2, device=device).float() / head_dim))
    t = torch.arange(seq_len, device=device).float()
    freqs = torch.outer(t, inv_freq)
    return freqs.cos().to(dtype), freqs.sin().to(dtype)


def _default_rope_style(model_type: str) -> str:
    """Pick the RoPE convention a given HF ``model_type`` trains with."""
    if model_type in {"llama", "qwen2", "mistral"}:
        return "half-rotate"
    return "interleaved"


def _apply_rope(
    x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor, *, style: str = "interleaved",
) -> torch.Tensor:
    # x: [B, H, T, D] ; cos/sin: [T, D/2]
    cos = cos[None, None, :, :]
    sin = sin[None, None, :, :]
    if style == "half-rotate":
        # HF Llama / Qwen2: rotate first half against second half.
        x1, x2 = x[..., : x.shape[-1] // 2], x[..., x.shape[-1] // 2 :]
        return torch.cat((x1 * cos - x2 * sin, x1 * sin + x2 * cos), dim=-1)
    # "interleaved" (default): GPT-NeoX style, pairs (0,1), (2,3), ...
    x1, x2 = x[..., ::2], x[..., 1::2]
    return torch.stack((x1 * cos - x2 * sin, x1 * sin + x2 * cos), dim=-1).flatten(-2)


class Attention(nn.Module):
    def __init__(self, cfg: HyperNixConfig) -> None:
        super().__init__()
        self.n_head = cfg.num_attention_heads
        self.n_kv = cfg.n_kv_head
        self.head_dim = cfg.head_dim
        self.rope_style = cfg.rope_style
        hidden = cfg.hidden_size
        qkv_bias = cfg.attention_bias
        self.q_proj = nn.Linear(hidden, self.n_head * self.head_dim, bias=qkv_bias)
        self.k_proj = nn.Linear(hidden, self.n_kv * self.head_dim, bias=qkv_bias)
        self.v_proj = nn.Linear(hidden, self.n_kv * self.head_dim, bias=qkv_bias)
        self.o_proj = nn.Linear(self.n_head * self.head_dim, hidden, bias=False)

    def forward(self, x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
        B, T, _ = x.shape
        q = self.q_proj(x).view(B, T, self.n_head, self.head_dim).transpose(1, 2)
        k = self.k_proj(x).view(B, T, self.n_kv, self.head_dim).transpose(1, 2)
        v = self.v_proj(x).view(B, T, self.n_kv, self.head_dim).transpose(1, 2)
        q = _apply_rope(q, cos, sin, style=self.rope_style)
        k = _apply_rope(k, cos, sin, style=self.rope_style)
        # Repeat KV heads for grouped-query attention.
        if self.n_kv != self.n_head:
            repeat = self.n_head // self.n_kv
            k = k.repeat_interleave(repeat, dim=1)
            v = v.repeat_interleave(repeat, dim=1)
        out = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        out = out.transpose(1, 2).contiguous().view(B, T, -1)
        return self.o_proj(out)


class MLP(nn.Module):
    def __init__(self, cfg: HyperNixConfig) -> None:
        super().__init__()
        self.gate_proj = nn.Linear(cfg.hidden_size, cfg.intermediate_size, bias=False)
        self.up_proj = nn.Linear(cfg.hidden_size, cfg.intermediate_size, bias=False)
        self.down_proj = nn.Linear(cfg.intermediate_size, cfg.hidden_size, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.down_proj(F.silu(self.gate_proj(x)) * self.up_proj(x))


class Block(nn.Module):
    def __init__(self, cfg: HyperNixConfig) -> None:
        super().__init__()
        self.input_layernorm = RMSNorm(cfg.hidden_size, cfg.rms_norm_eps)
        self.self_attn = Attention(cfg)
        self.post_attention_layernorm = RMSNorm(cfg.hidden_size, cfg.rms_norm_eps)
        self.mlp = MLP(cfg)

    def forward(self, x: torch.Tensor, cos: torch.Tensor, sin: torch.Tensor) -> torch.Tensor:
        x = x + self.self_attn(self.input_layernorm(x), cos, sin)
        x = x + self.mlp(self.post_attention_layernorm(x))
        return x


class HyperNixModel(nn.Module):
    """Llama-shaped HyperNix causal LM. The tensor names match HF conventions
    so the existing architecture-agnostic converter in
    :mod:`hypernix.arch` picks them up without any special casing."""

    def __init__(self, cfg: HyperNixConfig) -> None:
        super().__init__()
        self.config = cfg
        self.embed_tokens = nn.Embedding(cfg.vocab_size, cfg.hidden_size)
        self.layers = nn.ModuleList([Block(cfg) for _ in range(cfg.num_hidden_layers)])
        self.norm = RMSNorm(cfg.hidden_size, cfg.rms_norm_eps)
        self.lm_head = nn.Linear(cfg.hidden_size, cfg.vocab_size, bias=False)
        if cfg.tie_word_embeddings:
            self.lm_head.weight = self.embed_tokens.weight

    def forward(self, input_ids: torch.Tensor, labels: torch.Tensor | None = None) -> dict[str, torch.Tensor]:
        x = self.embed_tokens(input_ids)
        cos, sin = _rope_cache(input_ids.size(1), self.config.head_dim, self.config.rope_theta, x.device, x.dtype)
        for block in self.layers:
            x = block(x, cos, sin)
        x = self.norm(x)
        logits = self.lm_head(x)
        out = {"logits": logits}
        if labels is not None:
            shift_logits = logits[..., :-1, :].contiguous()
            shift_labels = labels[..., 1:].contiguous()
            loss = F.cross_entropy(
                shift_logits.view(-1, shift_logits.size(-1)),
                shift_labels.view(-1),
                ignore_index=-100,
            )
            out["loss"] = loss
        return out


# ---------------------------------------------------------------------------
# Checkpoint I/O (HuggingFace-compatible snapshot layout)
# ---------------------------------------------------------------------------

def save_snapshot(
    model: HyperNixModel,
    out_dir: Path | str,
    tokenizer_source: Path | str | None = None,
) -> Path:
    """Write ``out_dir`` in HuggingFace snapshot layout.

    Produces::

        <out_dir>/config.json
        <out_dir>/model.safetensors
        <out_dir>/tokenizer.json        (copied from tokenizer_source if given)
        <out_dir>/tokenizer.model       (ditto)
        <out_dir>/special_tokens_map.json
        <out_dir>/tokenizer_config.json
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.json").write_text(json.dumps(model.config.to_dict(), indent=2))
    state = {k: v.detach().contiguous().cpu() for k, v in model.state_dict().items()}
    # When weights are tied, `embed_tokens.weight` and `lm_head.weight` share
    # memory, which safetensors rejects. Drop the redundant lm_head tensor —
    # the model re-ties on load via HyperNixModel.__init__.
    if model.config.tie_word_embeddings and "lm_head.weight" in state:
        if "embed_tokens.weight" in state and state["lm_head.weight"].data_ptr() == state["embed_tokens.weight"].data_ptr():
            del state["lm_head.weight"]
    save_file(state, str(out / "model.safetensors"))
    if tokenizer_source is not None:
        src = Path(tokenizer_source)
        for name in (
            "tokenizer.json",
            "tokenizer.model",
            "tokenizer_config.json",
            "special_tokens_map.json",
            "vocab.txt",
            "merges.txt",
            "added_tokens.json",
        ):
            candidate = src / name
            if candidate.exists():
                shutil.copy2(candidate, out / name)
    return out


def _load_state_dict(model_dir: Path) -> dict[str, torch.Tensor]:
    """Load the full state dict from a snapshot (single file or sharded)."""
    weights = model_dir / "model.safetensors"
    if weights.exists():
        return load_file(str(weights))
    state: dict[str, torch.Tensor] = {}
    for shard in sorted(model_dir.glob("*.safetensors")):
        state.update(load_file(str(shard)))
    return state


def _strip_hf_prefix(state: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
    """Drop the ``model.`` prefix HF LlamaForCausalLM puts on its tensors so
    they line up with :class:`HyperNixModel`'s flat naming."""
    if not any(k.startswith("model.") for k in state):
        return state
    remapped: dict[str, torch.Tensor] = {}
    for k, v in state.items():
        if k.startswith("model."):
            remapped[k[len("model.") :]] = v
        else:
            remapped[k] = v
    return remapped


def load_snapshot(model_dir: Path | str):
    """Load any supported snapshot from ``model_dir``.

    Dispatches on the ``model_type`` declared in ``config.json``:

    * ``"hypernix"`` / ``"llama"`` / ``"qwen2"`` / ``"mistral"`` — returns a
      :class:`HyperNixModel` (our parametric Llama-shape); the loader
      automatically strips the HF ``model.`` prefix and picks the correct
      RoPE convention.
    * ``"nano-nano"`` — returns a :class:`hypernix.nano_nano.NanoNanoModel`
      (the custom tiny arch used by ``ray0rf1re/nano-nano-927-v3``).

    Returns ``(model, config)``.
    """
    model_dir = Path(model_dir)
    cfg_raw = json.loads((model_dir / "config.json").read_text())
    model_type = cfg_raw.get("model_type", "hypernix")

    if model_type == "nano-nano":
        # Custom arch — delegate to the dedicated module so we don't pollute
        # the HyperNix code path with nano-nano-specific tensor remapping.
        from .nano_nano import NanoNanoConfig, NanoNanoModel

        cfg = NanoNanoConfig.from_dict(cfg_raw)
        model = NanoNanoModel(cfg)
        state = _strip_hf_prefix(_load_state_dict(model_dir))
        model.load_state_dict(state, strict=False)
        return model, cfg

    cfg = HyperNixConfig.from_dict(cfg_raw)
    model = HyperNixModel(cfg)
    state = _strip_hf_prefix(_load_state_dict(model_dir))
    model.load_state_dict(state, strict=False)
    return model, cfg


# ---------------------------------------------------------------------------
# Model expansion (warm-start a bigger model from a smaller one)
# ---------------------------------------------------------------------------

def _pad_tensor(src: torch.Tensor, dst_shape: tuple[int, ...], init_std: float = 0.02) -> torch.Tensor:
    """Copy ``src`` into a new tensor of ``dst_shape``; newly added slots are
    initialized from ``N(0, init_std)``. Works for 1D and 2D tensors."""
    if tuple(src.shape) == tuple(dst_shape):
        return src.clone()
    dst = torch.randn(*dst_shape, dtype=src.dtype) * init_std
    slices = tuple(slice(0, min(s, d)) for s, d in zip(src.shape, dst_shape, strict=False))
    dst[slices] = src[slices]
    return dst


def expand_checkpoint(
    src_dir: Path | str,
    dst_dir: Path | str,
    *,
    hidden_size: int | None = None,
    intermediate_size: int | None = None,
    num_hidden_layers: int | None = None,
    num_attention_heads: int | None = None,
    vocab_size: int | None = None,
    init_std: float = 0.02,
    tokenizer_source: Path | str | None = None,
    seed: int | None = None,
) -> Path:
    """Warm-start a bigger HyperNix model from a smaller snapshot.

    Any dimension left ``None`` is inherited from the source. Widening
    copies existing rows/columns into the top-left of the new tensors and
    fills the rest with small random init. Depth expansion duplicates the
    final block weights into the newly-added blocks (a safe starting
    point — the residual path keeps the network functional from step 0).

    Returns the path of ``dst_dir`` (suitable for feeding back into
    :func:`hypernix.convert_to_gguf`).
    """
    src = Path(src_dir)
    dst = Path(dst_dir)
    if seed is not None:
        torch.manual_seed(seed)
    old_model, old_cfg = load_snapshot(src)

    new_cfg = HyperNixConfig(
        vocab_size=vocab_size or old_cfg.vocab_size,
        hidden_size=hidden_size or old_cfg.hidden_size,
        intermediate_size=intermediate_size or old_cfg.intermediate_size,
        num_hidden_layers=num_hidden_layers or old_cfg.num_hidden_layers,
        num_attention_heads=num_attention_heads or old_cfg.num_attention_heads,
        num_key_value_heads=old_cfg.num_key_value_heads,
        max_position_embeddings=old_cfg.max_position_embeddings,
        rope_theta=old_cfg.rope_theta,
        rms_norm_eps=old_cfg.rms_norm_eps,
        tie_word_embeddings=old_cfg.tie_word_embeddings,
    )
    if new_cfg.hidden_size % new_cfg.num_attention_heads != 0:
        raise ValueError(
            f"hidden_size={new_cfg.hidden_size} must be divisible by "
            f"num_attention_heads={new_cfg.num_attention_heads}"
        )

    new_model = HyperNixModel(new_cfg)
    old_state = old_model.state_dict()
    new_state = new_model.state_dict()

    # Copy overlapping portions of per-block weights for the first
    # min(old_n_layers, new_n_layers) blocks; duplicate the last old block
    # into any extra blocks.
    old_nl = old_cfg.num_hidden_layers
    for k, new_t in new_state.items():
        if k.startswith("layers."):
            _, idx, *rest = k.split(".")
            src_idx = min(int(idx), old_nl - 1)
            src_key = ".".join(["layers", str(src_idx), *rest])
            if src_key in old_state:
                new_state[k] = _pad_tensor(old_state[src_key], tuple(new_t.shape), init_std)
        elif k in old_state:
            new_state[k] = _pad_tensor(old_state[k], tuple(new_t.shape), init_std)

    new_model.load_state_dict(new_state, strict=True)
    save_snapshot(new_model, dst, tokenizer_source=tokenizer_source or src)
    return dst


# ---------------------------------------------------------------------------
# Minimal training loop
# ---------------------------------------------------------------------------

def _iter_chunks(path: Path, tokenizer, ctx_len: int, bos_id: int | None = None):
    """Stream-chunk a raw-text file into fixed-length token blocks."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    ids = tokenizer.encode(text)
    if bos_id is not None:
        ids = [bos_id, *ids]
    for i in range(0, len(ids) - ctx_len - 1, ctx_len):
        yield torch.tensor(ids[i : i + ctx_len + 1], dtype=torch.long)


def train(
    model_dir: Path | str,
    dataset_path: Path | str,
    out_dir: Path | str,
    *,
    steps: int = 1000,
    batch_size: int = 2,
    context_length: int = 512,
    lr: float = 3e-4,
    weight_decay: float = 0.1,
    grad_clip: float = 1.0,
    device: str | None = None,
    dtype: str = "float32",
    log_every: int = 10,
    save_every: int = 500,
    seed: int | None = None,
) -> Path:
    """Minimal causal-LM training loop.

    This is intentionally barebones (single-GPU/CPU, no sharding, no
    mixed-precision) so it runs anywhere `torch` runs. Use it to smoke-test
    a freshly-expanded model or to run short continue-pretraining jobs;
    anything serious should go through a real trainer.
    """
    model_dir = Path(model_dir)
    dataset_path = Path(dataset_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    if seed is not None:
        torch.manual_seed(seed)

    dev = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    tdtype = {"float32": torch.float32, "float16": torch.float16, "bfloat16": torch.bfloat16}[dtype]

    model, cfg = load_snapshot(model_dir)
    model.to(dev, dtype=tdtype)
    model.train()

    try:
        from transformers import AutoTokenizer  # lazy import - optional dep
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "hypernix.train needs the `transformers` tokenizer at runtime. "
            "Install it with:  pip install 'hypernix[train]'  "
            "(or `pip install transformers`)."
        ) from exc
    if not (model_dir / "tokenizer.json").exists() and not (model_dir / "tokenizer.model").exists():
        raise FileNotFoundError(
            f"No tokenizer files under {model_dir}. Re-init with "
            "`hypernix train init --tokenizer-source <snapshot_with_tokenizer>` "
            "or copy tokenizer.json/tokenizer.model into the model dir."
        )
    tok = AutoTokenizer.from_pretrained(str(model_dir), use_fast=True)

    chunks = list(_iter_chunks(dataset_path, tok, context_length))
    if not chunks:
        raise RuntimeError(f"dataset {dataset_path} produced no training chunks (too short?)")

    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay, betas=(0.9, 0.95))
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=steps)

    step = 0
    while step < steps:
        batch = torch.stack([chunks[(step * batch_size + i) % len(chunks)] for i in range(batch_size)])
        batch = batch.to(dev)
        inputs = batch[:, :-1]
        labels = batch[:, 1:]
        out_dict = model(inputs, labels=labels)
        loss = out_dict["loss"]

        opt.zero_grad(set_to_none=True)
        loss.backward()
        if grad_clip:
            torch.nn.utils.clip_grad_norm_(model.parameters(), grad_clip)
        opt.step()
        sched.step()
        step += 1

        if step % log_every == 0:
            print(f"[hypernix.train] step {step}/{steps}  loss={loss.item():.4f}  ppl={math.exp(min(loss.item(), 20)):.2f}")
        if save_every and step % save_every == 0:
            save_snapshot(model, out, tokenizer_source=model_dir)

    save_snapshot(model, out, tokenizer_source=model_dir)
    return out


# ---------------------------------------------------------------------------
# Fresh-init helper
# ---------------------------------------------------------------------------

def init_from_scratch(
    out_dir: Path | str,
    cfg: HyperNixConfig,
    tokenizer_source: Path | str | None = None,
    init_std: float = 0.02,
    seed: int | None = None,
) -> Path:
    """Create a new randomly-initialized HyperNix snapshot at ``out_dir``.

    Pass ``seed`` to make initialization deterministic (useful when a user
    wants to reproduce a bigger-sibling model later via ``expand_checkpoint``).
    """
    if seed is not None:
        torch.manual_seed(seed)
    model = HyperNixModel(cfg)
    with torch.no_grad():
        for p in model.parameters():
            if p.dim() >= 2:
                nn.init.normal_(p, std=init_std)
    return save_snapshot(model, out_dir, tokenizer_source=tokenizer_source)
