"""bell — streaming token callbacks and "food's ready" notifications.

A bell rings when an order's done.  Here it does two things:

1.  Wraps any ``CodeOven`` (or compatible) so generation streams
    one token at a time through user-supplied callbacks instead of
    blocking until the full reply is ready.
2.  Provides a tiny notification primitive so a long chat or batch
    job can ring you (stdout, file, callback) when it finishes.

Usage with a chat oven::

    from hypernix.bell import Bell
    from hypernix.old_oven import preheat

    oven = preheat("hyper-nix.2")

    bell = Bell()
    bell.on_token(lambda tok, idx: print(tok, end="", flush=True))
    bell.on_done(lambda full: print(f"\\n[done, {len(full)} chars]"))

    reply = bell.stream_chat(
        oven,
        [{"role": "user", "content": "hello"}],
        max_new_tokens=128,
    )

Manual / pull-based streaming::

    for tok in bell.iter_chat(oven, messages):
        print(tok, end="", flush=True)

Both forms also work for plain completion via ``stream_complete`` /
``iter_complete``.

The bell is **not** required for chatting — :class:`hypernix.countertop.Countertop`
uses it under the hood when you pass ``stream=True``, but you can
also use it standalone with ``CodeOven``.
"""
from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import torch

TokenCallback = Callable[[str, int], None]
DoneCallback = Callable[[str], None]


@dataclass
class Bell:
    """Streaming-token + done-notification primitive.

    Attributes:
        token_callbacks: Each ``(token_str, index)`` is forwarded to
            every registered callback as it's produced.
        done_callbacks: Fired once at the end with the full decoded
            reply.
        flour: Optional :class:`hypernix.flour.Flour` chat-quality
            processor.  When set, each step's logits go through
            ``flour.process(...)`` before sampling and the running
            decoded text is checked against ``flour.matched_stop()``
            for early termination.
    """

    token_callbacks: list[TokenCallback] = field(default_factory=list)
    done_callbacks: list[DoneCallback] = field(default_factory=list)
    flour: Any = None  # hypernix.flour.Flour (forward-ref to avoid cycle)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def on_token(self, fn: TokenCallback) -> Bell:
        self.token_callbacks.append(fn)
        return self

    def on_done(self, fn: DoneCallback) -> Bell:
        self.done_callbacks.append(fn)
        return self

    def ring(self, full_reply: str) -> None:
        """Manually fire the done-callbacks (useful after a non-streamed
        run, e.g. to integrate a one-shot ``oven.complete`` into a
        flow that already wires a bell for notifications)."""
        for fn in self.done_callbacks:
            fn(full_reply)

    # ------------------------------------------------------------------
    # Streaming generators
    # ------------------------------------------------------------------

    def iter_complete(
        self,
        oven: Any,
        prompt: str,
        *,
        max_new_tokens: int = 128,
        temperature: float = 0.7,
        top_k: int = 40,
        top_p: float = 0.95,
        seed: int | None = None,
    ) -> Iterator[str]:
        """Yield decoded tokens as they're sampled from a completion.

        Compatible with :class:`hypernix.old_oven.CodeOven` and any
        oven that exposes ``_encode``, ``_decode`` and an autoregressive
        forward via ``model(...).logits``.
        """
        yield from self._iter_from_ids(
            oven,
            ids=oven._encode(prompt) or [0],
            max_new_tokens=max_new_tokens,
            temperature=temperature, top_k=top_k, top_p=top_p,
            seed=seed,
            eos=_eos_ids(oven),
        )

    def iter_chat(
        self,
        oven: Any,
        messages: list[dict[str, str]],
        *,
        max_new_tokens: int = 256,
        temperature: float = 0.7,
        top_k: int = 40,
        top_p: float = 0.95,
        seed: int | None = None,
    ) -> Iterator[str]:
        """Yield decoded tokens for a chat turn.  Routes through
        ``oven._format_chat`` so any custom chat template the oven
        already speaks (HF ``apply_chat_template`` or a hypernix
        cookbook template) is preserved."""
        ids = oven._format_chat(messages) or [0]
        yield from self._iter_from_ids(
            oven,
            ids=ids,
            max_new_tokens=max_new_tokens,
            temperature=temperature, top_k=top_k, top_p=top_p,
            seed=seed,
            eos=_eos_ids(oven),
        )

    # ------------------------------------------------------------------
    # Push-based streaming with callbacks
    # ------------------------------------------------------------------

    def stream_complete(
        self,
        oven: Any,
        prompt: str,
        **gen_kwargs: Any,
    ) -> str:
        return self._collect(self.iter_complete(oven, prompt, **gen_kwargs))

    def stream_chat(
        self,
        oven: Any,
        messages: list[dict[str, str]],
        **gen_kwargs: Any,
    ) -> str:
        return self._collect(self.iter_chat(oven, messages, **gen_kwargs))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _collect(self, it: Iterator[str]) -> str:
        chunks: list[str] = []
        for tok in it:
            chunks.append(tok)
        full = "".join(chunks)
        for fn in self.done_callbacks:
            fn(full)
        return full

    def _iter_from_ids(
        self,
        oven: Any,
        *,
        ids: list[int],
        max_new_tokens: int,
        temperature: float,
        top_k: int,
        top_p: float,
        seed: int | None,
        eos: tuple[int, ...],
    ) -> Iterator[str]:
        if seed is not None:
            torch.manual_seed(seed)
        device = oven.device if hasattr(oven, "device") else "cpu"
        model = oven.model
        was_training = model.training
        model.eval()
        tokenizer = getattr(oven, "tokenizer", None)
        decoded_so_far = ""
        try:
            cur = torch.tensor(ids, dtype=torch.long, device=device).unsqueeze(0)
            produced: list[int] = []
            with torch.no_grad():
                for i in range(max_new_tokens):
                    out = model(cur)
                    logits = out.logits[:, -1, :] if hasattr(out, "logits") else out[:, -1, :]
                    if self.flour is not None:
                        logits = self.flour.process(
                            logits, produced, tokenizer=tokenizer,
                        )
                    next_id = _sample_one(
                        logits, temperature=temperature,
                        top_k=top_k, top_p=top_p,
                    )
                    nid = int(next_id.item())
                    if nid in eos:
                        break
                    produced.append(nid)
                    tok = oven._decode([nid])
                    decoded_so_far += tok
                    for fn in self.token_callbacks:
                        fn(tok, i)
                    yield tok
                    cur = torch.cat([cur, next_id.view(1, 1)], dim=1)
                    if self.flour is not None and self.flour.matched_stop(decoded_so_far):
                        break
        finally:
            if was_training:
                model.train()


# ---------------------------------------------------------------------------
# Sampling helpers (kept self-contained so bell doesn't depend on the
# CodeOven internals; the same logic lives in old_oven._run, but
# duplicating it here means bell stays usable with custom ovens that
# don't expose the same private helpers).
# ---------------------------------------------------------------------------

def _sample_one(
    logits: torch.Tensor,
    *,
    temperature: float,
    top_k: int,
    top_p: float,
) -> torch.Tensor:
    if temperature <= 0:
        return logits.argmax(dim=-1).view(1)
    scaled = logits / max(temperature, 1e-6)
    if top_k and top_k < scaled.size(-1):
        kth = torch.topk(scaled, top_k, dim=-1).values[..., -1, None]
        scaled = torch.where(scaled < kth, torch.full_like(scaled, float("-inf")), scaled)
    probs = torch.softmax(scaled, dim=-1)
    if 0.0 < top_p < 1.0:
        sorted_probs, sorted_idx = torch.sort(probs, descending=True, dim=-1)
        cumprobs = torch.cumsum(sorted_probs, dim=-1)
        mask = cumprobs > top_p
        # always keep at least the top-1
        mask[..., 0] = False
        sorted_probs = sorted_probs.masked_fill(mask, 0.0)
        sorted_probs = sorted_probs / sorted_probs.sum(dim=-1, keepdim=True).clamp_min(1e-12)
        choice = torch.multinomial(sorted_probs, 1)
        return torch.gather(sorted_idx, -1, choice).view(1)
    return torch.multinomial(probs, 1).view(1)


def _eos_ids(oven: Any) -> tuple[int, ...]:
    if getattr(oven, "tokenizer_kind", None) == "hf":
        eid = getattr(oven.tokenizer, "eos_token_id", None)
        if isinstance(eid, int):
            return (eid,)
    return ()


# ---------------------------------------------------------------------------
# Convenience: ready-made bell variants
# ---------------------------------------------------------------------------

def stdout_bell() -> Bell:
    """A bell that writes each token to ``sys.stdout`` and prints a
    final newline + char-count summary on done."""
    b = Bell()
    b.on_token(lambda tok, _i: (sys.stdout.write(tok), sys.stdout.flush()))
    b.on_done(lambda full: sys.stdout.write(f"\n[bell: {len(full)} chars]\n"))
    return b


def file_bell(path: Path | str) -> Bell:
    """A bell that appends each token to ``path`` and writes a
    ``--- end of reply ---`` marker on done."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Truncate at the start of the run.
    p.write_text("", encoding="utf-8")
    fh = p.open("a", encoding="utf-8")
    b = Bell()
    b.on_token(lambda tok, _i: (fh.write(tok), fh.flush()))
    b.on_done(lambda _full: (fh.write("\n--- end of reply ---\n"), fh.close()))
    return b


def silent_bell() -> Bell:
    """A bell with no callbacks — useful when you want the streaming
    iterator without any side effects."""
    return Bell()


def bell(*, stdout: bool = False) -> Bell:
    """Construct a bell.  ``stdout=True`` returns :func:`stdout_bell`."""
    return stdout_bell() if stdout else Bell()


__all__ = [
    "Bell",
    "DoneCallback",
    "TokenCallback",
    "bell",
    "file_bell",
    "silent_bell",
    "stdout_bell",
]
