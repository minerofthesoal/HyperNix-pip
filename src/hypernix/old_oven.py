"""old_oven: code-generation wrapper around HyperNix.

The oven metaphor: a raw HuggingFace snapshot is dough. :func:`preheat`
downloads / loads it into a fully-ready :class:`CodeOven` you can bake
code out of — low-temperature sampling defaults, stop-sequence awareness,
and an optional fill-in-the-middle API for code infilling tasks.

Typical use (Python)::

    from hypernix import old_oven

    oven = old_oven.preheat("ray0rf1re/hyper-nix.1")
    print(oven.complete("def fibonacci(n):"))
    print(oven.fill(prefix="def add(a, b):\\n    return ",
                    suffix="\\n\\nresult = add(1, 2)"))
    oven.save_pt("./hypernix.pt")   # self-contained torch.load()-able bundle

Typical use (CLI)::

    hypernix --auto-oven --prompt "def fib(n):"
    hypernix oven --model-dir ./snapshot --prompt "def fib(n):"
    hypernix oven --model-dir ./snapshot --fill-prefix "def add(a,b):\\n    return " \\
                                         --fill-suffix "\\n\\nprint(add(1,2))"
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch

from .download import download_model, verify_snapshot
from .generate import _load_tokenizer, _sample_next
from .train import HyperNixModel, load_snapshot

# Heuristic stop strings we trim off a code completion. Users can pass an
# explicit `stop=...` to override; set `stop=()` to disable trimming.
DEFAULT_STOPS: tuple[str, ...] = ("\nclass ", "\ndef ", "\n\n\n", "</s>")

# FIM tokens used by the common "starcoder-style" convention; generate.fill()
# falls back to plain prefix-only continuation if these aren't in the vocab.
_FIM_PREFIX = "<fim_prefix>"
_FIM_SUFFIX = "<fim_suffix>"
_FIM_MIDDLE = "<fim_middle>"


def _dtype_from_str(name: str) -> torch.dtype:
    return {"float32": torch.float32, "float16": torch.float16, "bfloat16": torch.bfloat16}[name]


def _trim_at_stop(text: str, stops: tuple[str, ...]) -> str:
    if not stops:
        return text
    earliest = len(text)
    for s in stops:
        idx = text.find(s)
        if idx >= 0:
            earliest = min(earliest, idx)
    return text[:earliest]


@dataclass
class CodeOven:
    """A loaded HyperNix model + tokenizer ready for code generation.

    Returned by :func:`preheat`. Safe to reuse across many generate calls —
    the model is loaded once and kept resident on ``device``.
    """

    model: HyperNixModel
    tokenizer: Any
    tokenizer_kind: str  # "hf" or "byte"
    device: torch.device
    dtype: torch.dtype
    model_dir: Path

    # ------------------------------------------------------------------
    # Tokenizer helpers
    # ------------------------------------------------------------------

    def _encode(self, text: str) -> list[int]:
        if self.tokenizer_kind == "hf":
            return list(self.tokenizer.encode(text, add_special_tokens=False))
        return self.tokenizer.encode(text)

    def _decode(self, ids: list[int]) -> str:
        if self.tokenizer_kind == "hf":
            return self.tokenizer.decode(ids, skip_special_tokens=True)
        return self.tokenizer.decode(ids)

    def _fim_token_id(self, marker: str) -> int | None:
        if self.tokenizer_kind != "hf":
            return None
        tid = self.tokenizer.convert_tokens_to_ids(marker)
        # HF returns `unk_token_id` (or a bare int like 0/None) on miss;
        # treat anything falling back to the unk token as "not present".
        unk = getattr(self.tokenizer, "unk_token_id", None)
        if tid is None or (unk is not None and tid == unk):
            return None
        return int(tid)

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------

    @torch.no_grad()
    def _run(
        self,
        input_ids: list[int],
        *,
        max_new_tokens: int,
        temperature: float,
        top_k: int,
        top_p: float,
        eos_ids: tuple[int, ...] = (),
    ) -> list[int]:
        ctx = torch.tensor([input_ids], dtype=torch.long, device=self.device)
        max_ctx = self.model.config.max_position_embeddings
        generated: list[int] = []
        for _ in range(max_new_tokens):
            if ctx.size(1) > max_ctx:
                ctx = ctx[:, -max_ctx:]
            logits = self.model(ctx)["logits"][:, -1, :].float()
            nxt = _sample_next(
                logits[0], temperature=temperature, top_k=top_k, top_p=top_p,
            )
            tok = int(nxt.item())
            generated.append(tok)
            if tok in eos_ids:
                break
            ctx = torch.cat([ctx, nxt.view(1, 1)], dim=1)
        return generated

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def complete(
        self,
        prompt: str,
        *,
        max_new_tokens: int = 256,
        temperature: float = 0.2,
        top_k: int = 40,
        top_p: float = 0.95,
        stop: tuple[str, ...] = DEFAULT_STOPS,
        seed: int | None = None,
    ) -> str:
        """Continue ``prompt`` as code.

        Defaults favour code generation: low temperature, moderate top-p,
        and a stop-sequence trimmer that cuts the output at the first
        ``\\nclass `` / ``\\ndef `` boundary so you usually get one
        function back rather than a whole file.
        """
        if seed is not None:
            torch.manual_seed(seed)

        ids = self._encode(prompt) if prompt else []
        bos = getattr(self.tokenizer, "bos_token_id", None) if self.tokenizer_kind == "hf" else None
        if bos is not None and (not ids or ids[0] != bos):
            ids = [bos, *ids]
        if not ids:
            ids = [0]

        eos: tuple[int, ...] = ()
        if self.tokenizer_kind == "hf":
            eid = getattr(self.tokenizer, "eos_token_id", None)
            if isinstance(eid, int):
                eos = (eid,)

        out_ids = self._run(
            ids,
            max_new_tokens=max_new_tokens,
            temperature=temperature, top_k=top_k, top_p=top_p,
            eos_ids=eos,
        )
        new_text = self._decode(out_ids)
        return _trim_at_stop(new_text, stop)

    def fill(
        self,
        prefix: str,
        suffix: str,
        *,
        max_new_tokens: int = 128,
        temperature: float = 0.2,
        top_k: int = 40,
        top_p: float = 0.95,
        seed: int | None = None,
    ) -> str:
        """Fill-in-the-middle: generate text that fits between ``prefix``
        and ``suffix``.

        Uses the starcoder-style ``<fim_prefix> ... <fim_suffix> ... <fim_middle>``
        convention when the tokenizer has those special tokens; otherwise
        falls back to prefix-only completion (ignoring ``suffix``). Useful
        for editor-style code infilling.
        """
        if seed is not None:
            torch.manual_seed(seed)

        pre_id = self._fim_token_id(_FIM_PREFIX)
        suf_id = self._fim_token_id(_FIM_SUFFIX)
        mid_id = self._fim_token_id(_FIM_MIDDLE)

        if pre_id is not None and suf_id is not None and mid_id is not None:
            ids = [pre_id, *self._encode(prefix), suf_id, *self._encode(suffix), mid_id]
        else:
            # Graceful fallback: ignore the suffix and continue the prefix.
            # Users can detect this by comparing the tokenizer vocabulary.
            ids = self._encode(prefix) or [0]

        out_ids = self._run(
            ids,
            max_new_tokens=max_new_tokens,
            temperature=temperature, top_k=top_k, top_p=top_p,
        )
        return self._decode(out_ids)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_pt(self, out_path: Path | str) -> Path:
        """Save a self-contained ``torch.load``-able bundle to ``out_path``.

        The resulting ``.pt`` contains ``config`` (dict), ``state_dict``,
        and the source ``model_dir`` for later tokenizer recovery — so
        callers can ship a single file around and reconstruct the model
        with :func:`load_pt`.
        """
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        bundle = {
            "hypernix_format_version": 1,
            "config": self.model.config.to_dict(),
            "state_dict": {k: v.detach().cpu() for k, v in self.model.state_dict().items()},
            "source_model_dir": str(self.model_dir),
        }
        torch.save(bundle, out_path)
        return out_path


# ---------------------------------------------------------------------------
# Top-level functional API
# ---------------------------------------------------------------------------

def preheat(
    repo_id: str = "ray0rf1re/hyper-nix.1",
    *,
    local_dir: Path | str | None = None,
    revision: str | None = None,
    token: str | None = None,
    device: str | None = None,
    dtype: str = "float32",
    quiet: bool = False,
) -> CodeOven:
    """Download (if necessary) + load a HyperNix snapshot into a ``CodeOven``.

    If ``local_dir`` already contains a valid snapshot (``config.json`` +
    weights), no network call is made; otherwise the snapshot is fetched
    from the HF Hub. This is the one-call "get me a working PyTorch model
    right now" entry point; pairs with ``hypernix --auto-oven`` on the CLI.
    """
    path: Path
    if local_dir is not None:
        ld = Path(local_dir)
        try:
            if ld.exists():
                verify_snapshot(ld)
                path = ld
            else:
                raise FileNotFoundError(ld)
        except FileNotFoundError:
            path = download_model(
                repo_id=repo_id, revision=revision,
                local_dir=str(ld), token=token, quiet=quiet,
            )
    else:
        path = download_model(
            repo_id=repo_id, revision=revision, token=token, quiet=quiet,
        )

    model, _cfg = load_snapshot(path)
    dev = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    tdtype = _dtype_from_str(dtype)
    model.to(dev, dtype=tdtype)
    model.eval()

    tok, kind = _load_tokenizer(path)
    return CodeOven(
        model=model, tokenizer=tok, tokenizer_kind=kind,
        device=dev, dtype=tdtype, model_dir=path,
    )


def bake_code(source: CodeOven | Path | str, prompt: str, **kwargs: Any) -> str:
    """Convenience: accepts a preheated oven or a snapshot path/URL."""
    oven = source if isinstance(source, CodeOven) else preheat(local_dir=str(source))
    return oven.complete(prompt, **kwargs)


def fill_middle(
    source: CodeOven | Path | str, prefix: str, suffix: str, **kwargs: Any,
) -> str:
    """Convenience FIM API — accepts a preheated oven or a snapshot path."""
    oven = source if isinstance(source, CodeOven) else preheat(local_dir=str(source))
    return oven.fill(prefix, suffix, **kwargs)


def load_pt(pt_path: Path | str, *, device: str | None = None) -> CodeOven:
    """Rehydrate a CodeOven from a ``save_pt`` bundle.

    Tokenizer files are pulled from the original ``source_model_dir`` when
    still available; otherwise falls back to the byte-level tokenizer.
    """
    pt_path = Path(pt_path)
    bundle = torch.load(pt_path, map_location="cpu", weights_only=False)
    from .train import HyperNixConfig, HyperNixModel

    cfg = HyperNixConfig.from_dict(bundle["config"])
    model = HyperNixModel(cfg)
    model.load_state_dict(bundle["state_dict"], strict=False)
    dev = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
    model.to(dev)
    model.eval()

    src_dir = Path(bundle.get("source_model_dir") or "")
    tok, kind = _load_tokenizer(src_dir) if src_dir.exists() else _load_tokenizer(Path("."))
    return CodeOven(
        model=model, tokenizer=tok, tokenizer_kind=kind,
        device=dev, dtype=next(model.parameters()).dtype,
        model_dir=src_dir if src_dir.exists() else pt_path.parent,
    )
