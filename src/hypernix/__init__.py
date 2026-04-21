"""HyperNix: convert ray0rf1re/hyper-nix.1 PyTorch weights to GGUF."""
from __future__ import annotations

from . import old_oven
from .convert import convert_to_gguf
from .download import download_model, verify_snapshot
from .fetcher import fetch_llama_quantize
from .generate import generate_text
from .old_oven import CodeOven, bake_code, fill_middle, load_pt, preheat
from .quantize import QUANT_TYPES, quantize_gguf
from .train import (
    HyperNixConfig,
    HyperNixModel,
    expand_checkpoint,
    init_from_scratch,
    load_snapshot,
    save_snapshot,
    train,
)
from .upload import upload_gguf

__all__ = [
    "CodeOven",
    "HyperNixConfig",
    "HyperNixModel",
    "QUANT_TYPES",
    "bake_code",
    "convert_to_gguf",
    "download_model",
    "expand_checkpoint",
    "fetch_llama_quantize",
    "fill_middle",
    "generate_text",
    "init_from_scratch",
    "load_pt",
    "load_snapshot",
    "old_oven",
    "preheat",
    "quantize_gguf",
    "save_snapshot",
    "train",
    "upload_gguf",
    "verify_snapshot",
]

__version__ = "0.30.0"
DEFAULT_REPO_ID = "ray0rf1re/hyper-nix.1"
