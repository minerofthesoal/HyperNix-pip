"""hypernix.models.hnxrun — run a GGUF, including the sub-bit ones.

The IQ0.x tiers have been real quantisations since 0.72.3 pt 2: the
tensors genuinely carry 0.56 bits per weight and the file is a
well-formed GGUF. What they have never been is *runnable*. The type ids
are at 200 and above, which no llama.cpp knows and which even the
reference ``gguf`` Python reader rejects outright::

    ValueError: np.uint32(202) is not a valid GGMLQuantizationType

So :mod:`hypernix.models.ggufrun` refused them by name, and a person who
quantised a model to IQ0.5 got a file that was correct, small, and
useless. "It is a real quantisation" is not much comfort when nothing
will load it.

This is the loader and the forward pass that make it a model. It reads
any GGUF this package can write — F32/F16/BF16, the llama.cpp block
types via :mod:`hypernix.quant.llamaquants`, and the HyperNix sub-bit
types via :mod:`hypernix.quant.subbit` — dequantises every tensor to
torch, and runs the llama-family architecture over it.

What it is and is not
---------------------
It is a *reference* implementation: correctness first, in torch, with no
kernels and no fused anything. It will not beat llama.cpp and is not
trying to; the point is that a 0.5-bit model has somewhere to run at
all. For an upstream quant type, llama.cpp remains the right answer and
:mod:`hypernix.models.ggufrun` still sends it there.

The RoPE convention
-------------------
llama.cpp's converter permutes Q and K on the way into a GGUF so that
rotary embedding applies to *adjacent pairs* rather than to split
halves. That permutation is why reading these tensors back and applying
the half-split form — which is what every Hugging Face implementation
does — produces a model that loads, runs, and generates confident
nonsense. Adjacent pairs is the convention here, matching the file.

Attention is causal with a KV cache; grouped-query attention is handled
by repeating the KV heads. Both are checked against a full recompute in
the tests, because a cache that drifts from the uncached path is the
classic way this goes subtly wrong.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "HnxRunError",
    "ModelConfig",
    "LoadedModel",
    "load_model",
    "generate_tokens",
    "generate_text",
    "describe",
]


class HnxRunError(RuntimeError):
    """The model could not be loaded or run, with a reason worth reading."""


# ---------------------------------------------------------------------------
# Configuration, read from the file rather than guessed
# ---------------------------------------------------------------------------


@dataclass
class ModelConfig:
    """The architecture, as the GGUF describes itself."""

    architecture: str = "llama"
    block_count: int = 0
    embedding_length: int = 0
    head_count: int = 0
    head_count_kv: int = 0
    feed_forward_length: int = 0
    context_length: int = 2048
    rms_eps: float = 1e-5
    rope_theta: float = 10000.0
    rope_dimension_count: int = 0
    vocab_size: int = 0

    @property
    def head_dim(self) -> int:
        return self.embedding_length // self.head_count if self.head_count else 0

    @property
    def kv_groups(self) -> int:
        """How many query heads share each key/value head."""
        return self.head_count // self.head_count_kv if self.head_count_kv else 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "architecture": self.architecture,
            "block_count": self.block_count,
            "embedding_length": self.embedding_length,
            "head_count": self.head_count,
            "head_count_kv": self.head_count_kv,
            "head_dim": self.head_dim,
            "feed_forward_length": self.feed_forward_length,
            "context_length": self.context_length,
            "rope_theta": self.rope_theta,
            "vocab_size": self.vocab_size,
        }


#: Architectures whose tensor names and block shape this forward pass
#: matches. Refusing a name we do not know beats running the llama graph
#: over a model that is not one and reporting the result as generation.
SUPPORTED_ARCHITECTURES = ("llama", "mistral", "qwen2", "hypernix")


def _metadata_int(meta: dict, *keys: str, default: int = 0) -> int:
    for key in keys:
        if key in meta:
            try:
                return int(meta[key])
            except (TypeError, ValueError):
                continue
    return default


def _metadata_float(meta: dict, *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if key in meta:
            try:
                return float(meta[key])
            except (TypeError, ValueError):
                continue
    return default


def read_config(metadata: dict, tensors: dict) -> ModelConfig:
    """The architecture from the file's own metadata.

    Falls back to the tensor shapes for anything the metadata omits —
    a converter that dropped ``feed_forward_length`` still produced a
    model whose ``ffn_up`` says how wide the MLP is, and refusing to run
    it over a missing key nobody reads would be pedantry.
    """
    arch = str(metadata.get("general.architecture", "llama"))
    prefix = arch
    config = ModelConfig(
        architecture=arch,
        block_count=_metadata_int(metadata, f"{prefix}.block_count"),
        embedding_length=_metadata_int(metadata, f"{prefix}.embedding_length"),
        head_count=_metadata_int(metadata, f"{prefix}.attention.head_count"),
        head_count_kv=_metadata_int(metadata, f"{prefix}.attention.head_count_kv"),
        feed_forward_length=_metadata_int(metadata, f"{prefix}.feed_forward_length"),
        context_length=_metadata_int(metadata, f"{prefix}.context_length", default=2048),
        rms_eps=_metadata_float(
            metadata, f"{prefix}.attention.layer_norm_rms_epsilon", default=1e-5
        ),
        rope_theta=_metadata_float(metadata, f"{prefix}.rope.freq_base", default=10000.0),
        rope_dimension_count=_metadata_int(metadata, f"{prefix}.rope.dimension_count"),
    )

    embd = tensors.get("token_embd.weight")
    if embd is not None:
        config.vocab_size = int(embd.shape[0])
        if not config.embedding_length:
            config.embedding_length = int(embd.shape[1])
    if not config.block_count:
        config.block_count = 1 + max(
            (
                int(name.split(".")[1])
                for name in tensors
                if name.startswith("blk.") and name.split(".")[1].isdigit()
            ),
            default=-1,
        )
    if not config.head_count:
        config.head_count = 1
    if not config.head_count_kv:
        kv = tensors.get("blk.0.attn_k.weight")
        if kv is not None and config.head_dim:
            config.head_count_kv = max(1, int(kv.shape[0]) // config.head_dim)
        else:
            config.head_count_kv = config.head_count
    if not config.feed_forward_length:
        up = tensors.get("blk.0.ffn_up.weight")
        if up is not None:
            config.feed_forward_length = int(up.shape[0])
    if not config.rope_dimension_count:
        config.rope_dimension_count = config.head_dim
    return config


# ---------------------------------------------------------------------------
# Reading the weights, whatever they are packed as
# ---------------------------------------------------------------------------


def _dequantize(raw: bytes, ggml_type: int, elements: int):
    """Tensor bytes to a flat float32 numpy array, for every type we write."""
    import numpy as np

    from ..quant import llamaquants
    from ..quant.gguf import GGMLType
    from ..quant.subbit import dequantize_tensor as subbit_dequantize

    kind = int(ggml_type)
    if kind == int(GGMLType.F32):
        return np.frombuffer(raw, dtype="<f4", count=elements).astype(np.float32)
    if kind == int(GGMLType.F16):
        return np.frombuffer(raw, dtype="<f2", count=elements).astype(np.float32)
    if kind == int(GGMLType.BF16):
        # The top 16 bits of an F32, so widening is a shift.
        upper = np.frombuffer(raw, dtype="<u2", count=elements).astype(np.uint32)
        return (upper << 16).view(np.float32).astype(np.float32)
    if kind == int(GGMLType.F64):
        return np.frombuffer(raw, dtype="<f8", count=elements).astype(np.float32)
    if llamaquants.is_supported(kind):
        return np.asarray(llamaquants.dequantize_array(raw, kind), dtype=np.float32)[
            :elements
        ]
    if kind in (
        int(GGMLType.HNX_IQ0_9),
        int(GGMLType.HNX_IQ0_75),
        int(GGMLType.HNX_IQ0_5),
    ):
        packing = {
            int(GGMLType.HNX_IQ0_9): "sign_scale_l",
            int(GGMLType.HNX_IQ0_75): "pair_code_m",
            int(GGMLType.HNX_IQ0_5): "quad_code_xxxl",
        }[kind]
        return np.asarray(
            subbit_dequantize(raw, packing), dtype=np.float32
        )[:elements]
    raise HnxRunError(
        f"GGML type {kind} is one this runtime cannot decode. It reads F32, F16, "
        f"BF16, the llama.cpp block types, and the HyperNix sub-bit types."
    )


@dataclass
class LoadedModel:
    """A GGUF, dequantised and ready to run."""

    config: ModelConfig
    tensors: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    path: str = ""
    #: ``{ggml type name: tensor count}`` — what the file was packed as.
    packed_as: dict = field(default_factory=dict)
    tokenizer: Any = None

    @property
    def sub_bit(self) -> bool:
        return any(name.startswith("HNX_") for name in self.packed_as)

    def describe(self) -> str:
        mix = ", ".join(f"{k} x{v}" for k, v in sorted(self.packed_as.items()))
        return (
            f"{self.config.architecture}: {self.config.block_count} blocks, "
            f"{self.config.embedding_length} wide, "
            f"{self.config.head_count} heads "
            f"({self.config.head_count_kv} kv), vocab {self.config.vocab_size}\n"
            f"  packed as: {mix}"
        )


def load_model(path: str | Path, *, device: str = "cpu") -> LoadedModel:
    """Read a GGUF and dequantise every tensor into torch.

    Everything is materialised in float32. That is the honest cost of a
    reference runtime: a 0.5-bit model on disk is a float32 model in
    memory, so this loads models that *fit*, and says so rather than
    pretending the on-disk size is the resident size.
    """
    import numpy as np
    import torch

    from ..quant.gguf import GGMLType, GGUFError, GGUFFile

    model_path = Path(path)
    if not model_path.exists():
        raise HnxRunError(f"No such model: {model_path}")
    try:
        gguf_file = GGUFFile.read(model_path)
    except GGUFError as exc:
        raise HnxRunError(f"{model_path}: {exc}") from exc

    tensors: dict[str, Any] = {}
    packed: dict[str, int] = {}
    for tensor in gguf_file.tensors:
        raw = gguf_file.tensor_bytes(tensor)
        flat = _dequantize(raw, tensor.ggml_type, tensor.elements)
        # GGUF stores shape fastest-dimension-first: (n_input, n_output)
        # for a weight matrix. Reversing gives the (out, in) that a
        # linear layer wants, and getting it backwards produces a model
        # that loads cleanly and multiplies the wrong way round.
        shape = tuple(int(d) for d in reversed(tensor.shape))
        array = np.asarray(flat, dtype=np.float32).reshape(shape)
        tensors[tensor.name] = torch.from_numpy(array.copy()).to(device)
        try:
            name = GGMLType(int(tensor.ggml_type)).name
        except ValueError:  # pragma: no cover - guarded by _dequantize
            name = str(int(tensor.ggml_type))
        packed[name] = packed.get(name, 0) + 1

    config = read_config(gguf_file.metadata, tensors)
    if config.architecture not in SUPPORTED_ARCHITECTURES:
        raise HnxRunError(
            f"This runtime implements the llama-family graph; the file says its "
            f"architecture is {config.architecture!r}. Running the wrong graph over "
            f"a model produces confident nonsense rather than an error, so it is "
            f"refused here. Known: {', '.join(SUPPORTED_ARCHITECTURES)}."
        )
    missing = [
        name
        for name in ("token_embd.weight",)
        if name not in tensors
    ]
    if missing:
        raise HnxRunError(
            f"{model_path} is missing {', '.join(missing)}, so there is no model to "
            f"run. It has {len(tensors)} tensor(s); this looks like a fragment or a "
            f"file that is not a language model."
        )

    from .hnxtokenizer import tokenizer_from_metadata

    return LoadedModel(
        config=config,
        tensors=tensors,
        metadata=dict(gguf_file.metadata),
        path=str(model_path),
        packed_as=packed,
        tokenizer=tokenizer_from_metadata(gguf_file.metadata),
    )


def describe(path: str | Path) -> dict[str, Any]:
    """Architecture and packing, without running anything."""
    loaded = load_model(path)
    return {
        "path": str(path),
        **loaded.config.to_dict(),
        "packed_as": dict(sorted(loaded.packed_as.items())),
        "sub_bit": loaded.sub_bit,
        "has_tokenizer": loaded.tokenizer is not None,
    }


# ---------------------------------------------------------------------------
# The forward pass
# ---------------------------------------------------------------------------


def _rms_norm(x, weight, eps: float):
    import torch

    variance = x.to(torch.float32).pow(2).mean(-1, keepdim=True)
    return x * torch.rsqrt(variance + eps) * weight


def _rope(x, positions, theta: float, rope_dims: int):
    """Rotary embedding over *adjacent pairs*, as the GGUF expects.

    ``x`` is ``(heads, seq, head_dim)``. llama.cpp's converter permutes
    Q and K precisely so that this — not the half-split form every
    Hugging Face implementation uses — is the right rotation for the
    stored weights.
    """
    import torch

    head_dim = x.shape[-1]
    dims = min(rope_dims or head_dim, head_dim)
    dims -= dims % 2
    if dims <= 0:
        return x

    rotated = x[..., :dims]
    passthrough = x[..., dims:]

    inverse = 1.0 / (theta ** (torch.arange(0, dims, 2, dtype=torch.float32) / dims))
    angles = positions.to(torch.float32)[:, None] * inverse[None, :]
    cos = torch.cos(angles)[None, :, :]
    sin = torch.sin(angles)[None, :, :]

    even = rotated[..., 0::2]
    odd = rotated[..., 1::2]
    out = torch.empty_like(rotated)
    out[..., 0::2] = even * cos - odd * sin
    out[..., 1::2] = even * sin + odd * cos
    if passthrough.shape[-1]:
        return torch.cat([out, passthrough], dim=-1)
    return out


def _repeat_kv(x, groups: int):
    """Grouped-query attention: one KV head serves *groups* query heads."""
    if groups == 1:
        return x
    return x.repeat_interleave(groups, dim=0)


class _Cache:
    """Per-layer key/value history. Plain lists; correctness over speed."""

    def __init__(self, layers: int) -> None:
        self.keys: list[Any] = [None] * layers
        self.values: list[Any] = [None] * layers

    def __len__(self) -> int:
        first = self.keys[0] if self.keys else None
        return 0 if first is None else int(first.shape[1])


def forward(
    model: LoadedModel,
    token_ids,
    *,
    cache: _Cache | None = None,
    start_position: int = 0,
):
    """Logits for the last position of *token_ids*.

    Returns ``(logits, cache)``. Pass the returned cache back with the
    next token to continue without recomputing the prefix.
    """
    import torch

    config = model.config
    weights = model.tensors
    device = weights["token_embd.weight"].device

    ids = torch.as_tensor(token_ids, dtype=torch.long, device=device).reshape(-1)
    if ids.numel() == 0:
        raise HnxRunError("Nothing to run: the token sequence is empty.")
    if int(ids.max()) >= config.vocab_size or int(ids.min()) < 0:
        raise HnxRunError(
            f"Token id out of range: this model's vocabulary is 0..{config.vocab_size - 1}."
        )

    hidden = weights["token_embd.weight"][ids]
    seq = ids.shape[0]
    positions = torch.arange(start_position, start_position + seq, device=device)
    if cache is None:
        cache = _Cache(config.block_count)

    head_dim = config.head_dim
    scale = 1.0 / math.sqrt(head_dim) if head_dim else 1.0

    def need(name: str):
        tensor = weights.get(name)
        if tensor is None:
            raise HnxRunError(f"{model.path} has no {name}; the model is incomplete.")
        return tensor

    for layer in range(config.block_count):
        prefix = f"blk.{layer}."
        normed = _rms_norm(hidden, need(prefix + "attn_norm.weight"), config.rms_eps)

        q = normed @ need(prefix + "attn_q.weight").T
        k = normed @ need(prefix + "attn_k.weight").T
        v = normed @ need(prefix + "attn_v.weight").T

        q = q.view(seq, config.head_count, head_dim).transpose(0, 1)
        k = k.view(seq, config.head_count_kv, head_dim).transpose(0, 1)
        v = v.view(seq, config.head_count_kv, head_dim).transpose(0, 1)

        q = _rope(q, positions, config.rope_theta, config.rope_dimension_count)
        k = _rope(k, positions, config.rope_theta, config.rope_dimension_count)

        if cache.keys[layer] is not None:
            k = torch.cat([cache.keys[layer], k], dim=1)
            v = torch.cat([cache.values[layer], v], dim=1)
        cache.keys[layer] = k
        cache.values[layer] = v

        keys = _repeat_kv(k, config.kv_groups)
        values = _repeat_kv(v, config.kv_groups)

        scores = (q @ keys.transpose(1, 2)) * scale
        total = keys.shape[1]
        # Causal mask over absolute positions, so a cached prefix is
        # visible and the future never is -- including when this call
        # carries several new tokens at once.
        query_pos = positions[:, None]
        key_pos = torch.arange(total, device=device)[None, :]
        scores = scores.masked_fill((key_pos > query_pos)[None, :, :], float("-inf"))
        attention = torch.softmax(scores, dim=-1)
        context = (attention @ values).transpose(0, 1).reshape(seq, -1)

        hidden = hidden + context @ need(prefix + "attn_output.weight").T

        ffn_norm = weights.get(prefix + "ffn_norm.weight")
        normed = (
            _rms_norm(hidden, ffn_norm, config.rms_eps) if ffn_norm is not None else hidden
        )
        gate = normed @ need(prefix + "ffn_gate.weight").T
        up = normed @ need(prefix + "ffn_up.weight").T
        hidden = hidden + (
            torch.nn.functional.silu(gate) * up
        ) @ need(prefix + "ffn_down.weight").T

    output_norm = weights.get("output_norm.weight")
    if output_norm is not None:
        hidden = _rms_norm(hidden, output_norm, config.rms_eps)

    # A model with no output head ties it to the embedding, which is the
    # common arrangement for small models and not an error.
    head = weights.get("output.weight", weights["token_embd.weight"])
    return hidden @ head.T, cache


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def generate_tokens(
    model: LoadedModel,
    prompt_ids,
    *,
    max_new_tokens: int = 32,
    temperature: float = 0.0,
    top_k: int = 0,
    seed: int | None = None,
    stop_ids=(),
) -> list[int]:
    """Continue *prompt_ids*. ``temperature=0`` is greedy and deterministic."""
    import torch

    if max_new_tokens < 0:
        raise HnxRunError("max_new_tokens cannot be negative.")
    generator = None
    if seed is not None:
        generator = torch.Generator(device="cpu")
        generator.manual_seed(int(seed))

    ids = [int(t) for t in prompt_ids]
    if not ids:
        raise HnxRunError("Nothing to continue: the prompt has no tokens.")

    logits, cache = forward(model, ids)
    produced: list[int] = []
    stops = {int(t) for t in stop_ids}

    for _ in range(max_new_tokens):
        last = logits[-1]
        if temperature <= 0:
            token = int(torch.argmax(last))
        else:
            scaled = last / float(temperature)
            if top_k and top_k < scaled.numel():
                cut = torch.topk(scaled, int(top_k)).values[-1]
                scaled = scaled.masked_fill(scaled < cut, float("-inf"))
            probabilities = torch.softmax(scaled, dim=-1)
            token = int(torch.multinomial(probabilities, 1, generator=generator))
        produced.append(token)
        if token in stops:
            break
        logits, cache = forward(
            model, [token], cache=cache, start_position=len(ids) + len(produced) - 1
        )
    return produced


def generate_text(
    path: str | Path,
    prompt: str,
    *,
    max_new_tokens: int = 32,
    temperature: float = 0.0,
    top_k: int = 0,
    seed: int | None = None,
    device: str = "cpu",
) -> str:
    """Load *path* and continue *prompt*.

    Needs the GGUF to carry its tokenizer, which every real conversion
    does. Without one there is no way to turn text into the ids this
    model was trained on, and guessing an encoding would produce output
    that looks like a broken model rather than a missing tokenizer.
    """
    model = load_model(path, device=device)
    if model.tokenizer is None:
        raise HnxRunError(
            f"{path} carries no tokenizer metadata, so text cannot be turned into "
            f"tokens for it. Use generate_tokens() with ids you already have, or "
            f"convert the model with a tool that writes tokenizer.ggml.*."
        )
    prompt_ids = model.tokenizer.encode(prompt)
    if not prompt_ids:
        raise HnxRunError("The prompt tokenised to nothing.")
    produced = generate_tokens(
        model,
        prompt_ids,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
        top_k=top_k,
        seed=seed,
        stop_ids=model.tokenizer.stop_ids,
    )
    return model.tokenizer.decode(produced)
