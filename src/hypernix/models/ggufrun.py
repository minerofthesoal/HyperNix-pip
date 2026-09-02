"""hypernix.models.ggufrun — run a GGUF from ``generate`` and ``chat``.

``hypernix generate`` and ``hypernix chat`` took a snapshot directory:
``config.json`` plus safetensors, loaded through torch. So the one format
this package spends most of its time *producing* was the one format its
own inference commands could not read.

This routes a ``.gguf`` path to a runtime that can. It does not implement
inference — :mod:`hypernix.models.multilama` already speaks to four
llama.cpp variants and the ``llama_cpp`` binding, and a fifth
implementation here would be a fifth thing to keep working.

The sub-bit refusal
-------------------
The tiers this package writes with :mod:`hypernix.quant.hyprslug` —
``IQ0.9_L``, ``IQ0.75_M``, ``IQ0.5_XXXL`` — use GGML type ids at 200 and
above, which no llama.cpp knows. Handing one to a runtime that does not
know them produces either a refusal in someone else's words or, worse,
tensors read as the wrong type. So they are detected here, by reading
the file's own metadata, and refused with the reason and the remedy.

That check is the reason this module reads the GGUF header itself before
handing the path on: the answer to "why will this model not load" should
come from the thing that made it.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "GGUFRunError",
    "is_gguf",
    "describe_gguf",
    "load_gguf",
    "generate_with_gguf",
    "chat_with_gguf",
]


class GGUFRunError(RuntimeError):
    """The GGUF cannot be run, with a reason worth reading."""


def is_gguf(path: str | Path) -> bool:
    """True when *path* names a GGUF file.

    By magic bytes, not by extension: a file named ``.gguf`` that is not
    one should fail as "not a GGUF" rather than somewhere deep in a
    loader, and a GGUF with an unusual name should still work.
    """
    candidate = Path(path)
    if not candidate.is_file():
        return False
    try:
        with candidate.open("rb") as stream:
            return stream.read(4) == b"GGUF"
    except OSError:
        return False


def describe_gguf(path: str | Path) -> dict[str, Any]:
    """Architecture, tier and sub-bit status, read from the file."""
    from ..quant.gguf import GGUFError, GGUFFile

    try:
        model = GGUFFile.read(path)
    except GGUFError as exc:
        raise GGUFRunError(str(exc)) from exc

    return {
        "path": str(path),
        "architecture": model.metadata.get("general.architecture", ""),
        "name": model.metadata.get("general.name", ""),
        "sub_bit": bool(model.metadata.get("hypernix.sub_bit")),
        "tier": model.metadata.get("hypernix.tier", ""),
        "quantiser": model.metadata.get("hypernix.quantiser", ""),
        "tensors": len(model.tensors),
    }


def _refuse_sub_bit(info: dict[str, Any]) -> None:
    if not info["sub_bit"]:
        return
    tier = info.get("tier") or "a HyperNix sub-bit tier"
    raise GGUFRunError(
        f"{info['path']} is {tier}, a HyperNix extension type. No llama.cpp "
        "build can read it — the type ids are deliberately above anything "
        "upstream has allocated so a stock loader refuses the file instead of "
        "reading its tensors as the wrong type.\n"
        "  Run the model it was quantised from, or quantise to an upstream "
        "tier: hypernix quantize --type Q4_K_M"
    )


def load_gguf(
    path: str | Path,
    *,
    backend: str = "vanilla",
    n_ctx: int = 8192,
    n_gpu_layers: int = -1,
    quiet: bool = True,
) -> Any:
    """Load a local GGUF through :mod:`hypernix.models.multilama`."""
    model_path = Path(path)
    if not model_path.exists():
        raise GGUFRunError(f"No such model: {model_path}")
    if not is_gguf(model_path):
        raise GGUFRunError(f"{model_path} is not a GGUF file (bad magic).")

    _refuse_sub_bit(describe_gguf(model_path))

    from . import multilama

    try:
        # A local path, not a repo id. multilama.load resolves repo/file
        # pairs; passing the directory and the filename is how a path that
        # is already on disk goes through it without a download.
        return multilama.load(
            str(model_path.parent),
            model_path.name,
            backend=backend,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            quiet=quiet,
        )
    except multilama.MultiLlamaError as exc:
        raise GGUFRunError(str(exc)) from exc


def chat_with_gguf(
    path: str | Path,
    messages: list[dict[str, str]],
    *,
    system: str | None = None,
    max_tokens: int = 512,
    temperature: float = 0.7,
    backend: str = "vanilla",
    n_ctx: int = 8192,
) -> str:
    """One chat turn against a local GGUF."""
    model = load_gguf(path, backend=backend, n_ctx=n_ctx)
    try:
        return model.chat(
            messages, system=system, max_tokens=max_tokens, temperature=temperature
        )
    finally:
        close = getattr(model, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001 - a failed teardown is not a failed turn
                logger.debug("ggufrun: close() raised", exc_info=True)


def generate_with_gguf(
    path: str | Path,
    prompt: str,
    *,
    max_new_tokens: int = 64,
    temperature: float = 1.0,
    backend: str = "vanilla",
    n_ctx: int = 8192,
) -> str:
    """Continue *prompt* with a local GGUF.

    Carried over the chat shape: every backend here speaks chat, and
    several no longer speak the legacy completions endpoint at all.
    """
    return chat_with_gguf(
        path,
        [{"role": "user", "content": prompt}],
        max_tokens=max_new_tokens,
        temperature=temperature,
        backend=backend,
        n_ctx=n_ctx,
    )
