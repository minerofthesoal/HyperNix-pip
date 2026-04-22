"""microwave — one-shot quick inference at five power levels.

When you don't want to preheat an oven and keep it around, zap the
prompt through a microwave: one function call takes a repo id or
local path, produces a completion, and tears down.  Ideal for
scripting ("make a filename from this heading"), CI smoke tests, and
the kind of 5-line snippet you paste into a Jupyter cell.

Five power levels (tiers):

* :func:`defrost`  — just preheat and return the oven; no generation.
                     Handy when you want a warm oven for a burst of
                     follow-up calls without a full preheat cost.
* :func:`low_zap`  — short, cool output (16 tokens, temp 0.0).
                     Filename / keyword / single-line-answer mode.
* :func:`zap`      — standard (64 tokens, temp 0.2).
* :func:`high_zap` — long, hot output (512 tokens, temp 0.7).
                     Draft-a-paragraph mode.
* :func:`chat_zap` — single-turn chat using the tokenizer's chat
                     template (128 tokens, temp 0.7).

All five accept the same ``repo_id_or_dir`` and ``device`` / ``dtype``
arguments, so the only thing that changes between tiers is the
sampling profile.  Use :func:`reheat` to continue an earlier output
with the same oven (avoids rebuilding state).
"""
from __future__ import annotations

from pathlib import Path

from . import old_oven


def _preheat(
    repo_id_or_dir: str | Path,
    *,
    device: str | None,
    dtype: str,
    quiet: bool,
):
    local_dir: Path | None = None
    repo_id = str(repo_id_or_dir)
    if isinstance(repo_id_or_dir, Path) or (
        isinstance(repo_id_or_dir, str) and Path(repo_id_or_dir).exists()
    ):
        local_dir = Path(repo_id_or_dir)
        repo_id = "ray0rf1re/hyper-nix.1"
    return old_oven.preheat(
        repo_id=repo_id, local_dir=local_dir, device=device, dtype=dtype,
        quiet=quiet,
    )


def defrost(
    repo_id_or_dir: str | Path,
    *,
    device: str | None = None,
    dtype: str = "float32",
    quiet: bool = True,
):
    """Tier 1.  Preheat and return the oven — no generation.  Use this
    to warm up once and then issue many :meth:`CodeOven.complete` /
    ``.chat`` calls without rebuilding state each time."""
    return _preheat(repo_id_or_dir, device=device, dtype=dtype, quiet=quiet)


def low_zap(
    repo_id_or_dir: str | Path,
    prompt: str,
    *,
    max_new_tokens: int = 16,
    temperature: float = 0.0,
    top_k: int = 1,
    top_p: float = 1.0,
    stop: tuple[str, ...] = ("\n",),
    seed: int | None = 0,
    device: str | None = None,
    dtype: str = "float32",
    quiet: bool = True,
) -> str:
    """Tier 2.  Short, deterministic, single-line output.  Perfect for
    filename / slug / one-word-answer generation."""
    oven = _preheat(repo_id_or_dir, device=device, dtype=dtype, quiet=quiet)
    return oven.complete(
        prompt, max_new_tokens=max_new_tokens, temperature=temperature,
        top_k=top_k, top_p=top_p, stop=stop, seed=seed,
    )


def zap(
    repo_id_or_dir: str | Path,
    prompt: str,
    *,
    max_new_tokens: int = 64,
    temperature: float = 0.2,
    top_k: int = 40,
    top_p: float = 0.95,
    stop: tuple[str, ...] = (),
    seed: int | None = None,
    device: str | None = None,
    dtype: str = "float32",
    quiet: bool = True,
) -> str:
    """Tier 3.  Standard "zap" — 64 tokens, low-temp sampling.  The
    default if you don't know which tier you want."""
    oven = _preheat(repo_id_or_dir, device=device, dtype=dtype, quiet=quiet)
    return oven.complete(
        prompt, max_new_tokens=max_new_tokens, temperature=temperature,
        top_k=top_k, top_p=top_p, stop=stop, seed=seed,
    )


def high_zap(
    repo_id_or_dir: str | Path,
    prompt: str,
    *,
    max_new_tokens: int = 512,
    temperature: float = 0.7,
    top_k: int = 50,
    top_p: float = 0.95,
    stop: tuple[str, ...] = (),
    seed: int | None = None,
    device: str | None = None,
    dtype: str = "float32",
    quiet: bool = True,
) -> str:
    """Tier 4.  Long, hot output.  Draft-a-paragraph / synth-a-story
    mode."""
    oven = _preheat(repo_id_or_dir, device=device, dtype=dtype, quiet=quiet)
    return oven.complete(
        prompt, max_new_tokens=max_new_tokens, temperature=temperature,
        top_k=top_k, top_p=top_p, stop=stop, seed=seed,
    )


def chat_zap(
    repo_id_or_dir: str | Path,
    message: str,
    *,
    system: str | None = None,
    max_new_tokens: int = 128,
    temperature: float = 0.7,
    top_k: int = 40,
    top_p: float = 0.95,
    seed: int | None = None,
    device: str | None = None,
    dtype: str = "float32",
    quiet: bool = True,
) -> str:
    """Tier 5.  Single-turn chat.  Uses the tokenizer's chat template
    when present; falls back to raw completion otherwise."""
    oven = _preheat(repo_id_or_dir, device=device, dtype=dtype, quiet=quiet)
    turns = []
    if system is not None:
        turns.append({"role": "system", "content": system})
    turns.append({"role": "user", "content": message})
    return oven.chat(
        turns,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
        top_k=top_k, top_p=top_p, seed=seed,
    )


def reheat(
    oven,
    prior_output: str,
    continuation_prompt: str = "",
    *,
    max_new_tokens: int = 64,
    temperature: float = 0.2,
    stop: tuple[str, ...] = (),
    seed: int | None = None,
) -> str:
    """Continue a previous microwave output without reloading the model.

    ``oven`` is typically the return value of :func:`defrost`.  The
    ``prior_output`` is the text you want to extend; ``continuation_prompt``
    is an optional bridge string inserted between the prior output and
    the new generation window.
    """
    full = prior_output + continuation_prompt
    return oven.complete(
        full, max_new_tokens=max_new_tokens, temperature=temperature,
        stop=stop, seed=seed,
    )


TIERS: dict[str, callable] = {
    "defrost": defrost,
    "low": low_zap,
    "standard": zap,
    "high": high_zap,
    "chat": chat_zap,
}
