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

import sys
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
    """Return (tokenizer, kind). kind is 'hf' or 'byte'.

    Tries fast tokenizer first. If the local `tokenizers` crate is too old
    to parse the repo's ``tokenizer.json`` (a common failure mode looks like
    ``data did not match any variant of untagged enum ModelWrapper``),
    retries with ``use_fast=False``. Falls back to the byte tokenizer and
    prints an upgrade hint only if both HF paths fail.
    """
    has_fast = (model_dir / "tokenizer.json").exists()
    has_slow = (model_dir / "tokenizer.model").exists() or (
        (model_dir / "vocab.json").exists() and (model_dir / "merges.txt").exists()
    )
    if not (has_fast or has_slow):
        return _ByteTokenizer(), "byte"

    try:
        from transformers import AutoTokenizer
    except ModuleNotFoundError:
        return _ByteTokenizer(), "byte"

    fast_err: Exception | None = None
    if has_fast:
        try:
            return AutoTokenizer.from_pretrained(str(model_dir), use_fast=True), "hf"
        except Exception as exc:  # tokenizers crate schema mismatch, etc.
            fast_err = exc

    try:
        return AutoTokenizer.from_pretrained(str(model_dir), use_fast=False), "hf"
    except Exception as slow_err:
        msg = (
            f"[hypernix] could not load HF tokenizer from {model_dir}: {slow_err}\n"
            f"          falling back to UTF-8 byte tokenizer (output quality will suffer).\n"
            f"          try: pip install --upgrade 'tokenizers>=0.20' 'transformers>=4.44'"
        )
        if fast_err is not None:
            msg += f"\n          (fast-tokenizer error was: {fast_err})"
        print(msg, file=sys.stderr)
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
