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
    "materialize_draft",
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

    from ..quant.dflash2 import Dflash2Error, _info_from

    try:
        draft = _info_from(model)
    except Dflash2Error as exc:
        # A file whose metadata claims a draft it does not carry. Say so
        # here rather than letting a runtime fail on a missing tensor.
        draft = {"present": False, "error": str(exc)}

    return {
        "path": str(path),
        "architecture": model.metadata.get("general.architecture", ""),
        "name": model.metadata.get("general.name", ""),
        "sub_bit": bool(model.metadata.get("hypernix.sub_bit")),
        "tier": model.metadata.get("hypernix.tier", ""),
        "quantiser": model.metadata.get("hypernix.quantiser", ""),
        "tensors": len(model.tensors),
        "dflash2": draft,
    }


def materialize_draft(path: str | Path, cache_dir: str | Path | None = None) -> Path | None:
    """Write this model's embedded Dflash2 draft out, for a runtime that
    wants it as a separate file, and return where it went.

    ``None`` when there is no draft. Every llama.cpp that supports
    speculative decoding takes the draft as a second *path*
    (``--model-draft``), so a draft carried inside the model has to be
    handed over as a file at some point; doing it here means the person
    still only ever downloads and passes around one.

    Idempotent: a draft already sitting beside the model is reused rather
    than rewritten, since it cannot have changed without the model
    changing too.
    """
    from ..quant.dflash2 import Dflash2Error, extract, has_draft

    model_path = Path(path)
    if not has_draft(model_path):
        return None
    directory = Path(cache_dir) if cache_dir else model_path.parent
    target = directory / f"{model_path.stem}.dflash2-draft.gguf"
    if target.exists() and target.stat().st_mtime >= model_path.stat().st_mtime:
        return target
    try:
        directory.mkdir(parents=True, exist_ok=True)
        extract(model_path, target)
    except (Dflash2Error, OSError) as exc:
        raise GGUFRunError(f"Could not write the draft to {target}: {exc}") from exc
    return target


def _uses_hnx_runtime(info: dict[str, Any]) -> bool:
    """True when this file needs HyperNix's own runtime rather than llama.cpp.

    The sub-bit tiers carry GGML type ids at 200 and above. No llama.cpp
    build knows them -- the ids are deliberately out of upstream's range
    so a stock loader refuses the file by name instead of reading a
    0.5-bit tensor as Q4_K -- and even the reference ``gguf`` Python
    reader rejects them. Which used to mean the file had nowhere to run.
    It has somewhere now: :mod:`hypernix.models.hnxrun`.
    """
    return bool(info.get("sub_bit"))


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

    info = describe_gguf(model_path)
    if _uses_hnx_runtime(info):
        # llama.cpp cannot read these; HyperNix's own runtime can.
        from . import hnxrun

        try:
            return hnxrun.load_model(model_path)
        except hnxrun.HnxRunError as exc:
            raise GGUFRunError(str(exc)) from exc

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
    if _uses_hnx_runtime(describe_gguf(path)):
        return _chat_with_hnx_runtime(
            path, messages, system=system, max_tokens=max_tokens,
            temperature=temperature,
        )
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


def _chat_with_hnx_runtime(
    path: str | Path,
    messages: list[dict[str, str]],
    *,
    system: str | None = None,
    max_tokens: int = 512,
    temperature: float = 0.7,
) -> str:
    """A chat turn through HyperNix's own runtime, for the sub-bit tiers.

    Flattened to a plain prompt rather than run through a chat template:
    a model quantised to half a bit is not going to be following a
    template faithfully, and pretending otherwise would dress up its
    output as more structured than it is.
    """
    from . import hnxrun

    parts = []
    if system:
        parts.append(system)
    for message in messages:
        content = str(message.get("content", "")).strip()
        if content:
            parts.append(content)
    prompt = "\n".join(parts)

    try:
        return hnxrun.generate_text(
            path, prompt, max_new_tokens=max_tokens, temperature=temperature
        )
    except hnxrun.HnxRunError as exc:
        raise GGUFRunError(str(exc)) from exc


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
