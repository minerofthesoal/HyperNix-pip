"""microwave — one-shot quick inference.

When you don't want to preheat an oven and keep it around, zap the
prompt through a microwave: one function call takes a repo id or
local path, produces a completion, and tears down.  Ideal for
scripting ("make a filename from this heading"), CI smoke tests, and
the kind of 5-line snippet you paste into a Jupyter cell.

This is deliberately *not* a class.  The oven is for interactive use;
the microwave is for transactional use.
"""
from __future__ import annotations

from pathlib import Path

from . import old_oven


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
    """Preheat, complete, discard.  Returns the generated string.

    ``repo_id_or_dir`` can be a KNOWN_MODELS short name (``"nix2.5"``,
    ``"nano-mini"``), a full HF repo id, or an on-disk snapshot
    directory.  For repeat calls on the same model, preheat a
    :class:`hypernix.old_oven.CodeOven` once instead — this function
    rebuilds the model on every call.
    """
    local_dir: Path | None = None
    repo_id = str(repo_id_or_dir)
    if isinstance(repo_id_or_dir, Path) or (
        isinstance(repo_id_or_dir, str) and Path(repo_id_or_dir).exists()
    ):
        local_dir = Path(repo_id_or_dir)
        repo_id = "ray0rf1re/hyper-nix.1"  # unused when local_dir is set

    oven = old_oven.preheat(
        repo_id=repo_id, local_dir=local_dir, device=device, dtype=dtype,
        quiet=quiet,
    )
    return oven.complete(
        prompt,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
        top_k=top_k, top_p=top_p,
        stop=stop, seed=seed,
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
    """Single-turn chat companion to :func:`zap`."""
    local_dir: Path | None = None
    repo_id = str(repo_id_or_dir)
    if isinstance(repo_id_or_dir, Path) or Path(str(repo_id_or_dir)).exists():
        local_dir = Path(repo_id_or_dir)
        repo_id = "ray0rf1re/hyper-nix.1"

    oven = old_oven.preheat(
        repo_id=repo_id, local_dir=local_dir, device=device, dtype=dtype,
        quiet=quiet,
    )
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
