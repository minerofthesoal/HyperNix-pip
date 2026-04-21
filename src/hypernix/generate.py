"""Sample text from a local HyperNix snapshot.

This is the tiny companion to :func:`hypernix.train.train`: once you've
run ``hypernix train init`` / ``expand`` / ``run``, use
``hypernix generate --model-dir ...`` to confirm the snapshot actually
produces something. It is deliberately minimal (no caching, no beam
search, no streaming) so it runs anywhere torch runs.

If the snapshot has a tokenizer (``tokenizer.json`` or ``tokenizer.model``)
and the optional ``transformers`` dep is installed, we use it. Otherwise
we fall back to a UTF-8 byte-level tokenizer so the code path always
stays exercisable on freshly-initialized models.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F

from .train import load_snapshot


class _ByteTokenizer:
    """Trivial UTF-8 byte-level tokenizer used when no real tokenizer is present."""

    def encode(self, text: str) -> list[int]:
        return list(text.encode("utf-8"))

    def decode(self, ids: list[int]) -> str:
        return bytes(b & 0xFF for b in ids).decode("utf-8", errors="replace")


def _load_tokenizer(model_dir: Path) -> tuple[Any, str]:
    """Return (tokenizer, kind). kind is 'hf' or 'byte'."""
    if (model_dir / "tokenizer.json").exists() or (model_dir / "tokenizer.model").exists():
        try:
            from transformers import AutoTokenizer

            return AutoTokenizer.from_pretrained(str(model_dir), use_fast=True), "hf"
        except ModuleNotFoundError:
            pass
    return _ByteTokenizer(), "byte"


def _sample_next(
    logits: torch.Tensor,
    *,
    temperature: float,
    top_k: int,
    top_p: float,
) -> torch.Tensor:
    """Sample one token id from the final-position logits (shape [vocab])."""
    if temperature <= 0:
        return logits.argmax(dim=-1, keepdim=True)
    logits = logits / temperature
    if top_k and top_k > 0:
        v, _ = torch.topk(logits, min(top_k, logits.size(-1)))
        logits = logits.masked_fill(logits < v[..., [-1]], float("-inf"))
    if top_p and 0 < top_p < 1.0:
        sorted_logits, sorted_idx = torch.sort(logits, descending=True)
        cumprobs = F.softmax(sorted_logits, dim=-1).cumsum(dim=-1)
        mask = cumprobs > top_p
        mask[..., 0] = False
        sorted_logits = sorted_logits.masked_fill(mask, float("-inf"))
        logits = torch.full_like(logits, float("-inf")).scatter(-1, sorted_idx, sorted_logits)
    probs = F.softmax(logits, dim=-1)
    return torch.multinomial(probs, num_samples=1)


@torch.no_grad()
def generate_text(
    model_dir: Path | str,
    prompt: str = "",
    *,
    max_new_tokens: int = 64,
    temperature: float = 1.0,
    top_k: int = 50,
    top_p: float = 0.95,
    seed: int | None = None,
    device: str | None = None,
    dtype: str = "float32",
) -> str:
    """Sample text from a HyperNix snapshot.

    Args:
        model_dir: Path to a HuggingFace-style snapshot dir.
        prompt: Text to condition on. Empty -> start from BOS if the
            tokenizer has one, otherwise the empty sequence.
        max_new_tokens: How many tokens to generate after the prompt.
        temperature / top_k / top_p: Standard sampling knobs. Set
            ``temperature=0`` for greedy decoding.
        seed: If given, seeds the torch RNG before sampling.
        device / dtype: Override the auto-detected device / compute dtype.
    """
    model_dir = Path(model_dir)
    if seed is not None:
        torch.manual_seed(seed)

    tok, kind = _load_tokenizer(model_dir)
    model, cfg = load_snapshot(model_dir)
    dev = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    tdtype = {"float32": torch.float32, "float16": torch.float16, "bfloat16": torch.bfloat16}[dtype]
    model.to(dev, dtype=tdtype)
    model.eval()

    # Encode the prompt.
    if kind == "hf":
        ids = tok.encode(prompt) if prompt else []
        bos = getattr(tok, "bos_token_id", None)
        if bos is not None and (not ids or ids[0] != bos):
            ids = [bos, *ids]
    else:
        ids = tok.encode(prompt)

    if not ids:
        # No prompt + no BOS: start from a single zero-id token so the model
        # has something to condition on.
        ids = [0]

    ctx = torch.tensor([ids], dtype=torch.long, device=dev)
    max_ctx = cfg.max_position_embeddings

    for _ in range(max_new_tokens):
        # Crop to max context length (the model has no KV cache here).
        if ctx.size(1) > max_ctx:
            ctx = ctx[:, -max_ctx:]
        logits = model(ctx)["logits"][:, -1, :].float()
        nxt = _sample_next(logits[0], temperature=temperature, top_k=top_k, top_p=top_p)
        ctx = torch.cat([ctx, nxt.view(1, 1)], dim=1)

    out_ids = ctx[0].tolist()
    if kind == "hf":
        return tok.decode(out_ids, skip_special_tokens=True)
    return tok.decode(out_ids)
