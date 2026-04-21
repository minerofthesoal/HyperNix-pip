"""HyperNix: convert ray0rf1re/hyper-nix.1 PyTorch weights to GGUF."""
from __future__ import annotations

from .convert import convert_to_gguf
from .download import download_model
from .fetcher import fetch_llama_quantize
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
    "HyperNixConfig",
    "HyperNixModel",
    "QUANT_TYPES",
    "convert_to_gguf",
    "download_model",
    "expand_checkpoint",
    "fetch_llama_quantize",
    "init_from_scratch",
    "load_snapshot",
    "quantize_gguf",
    "save_snapshot",
    "train",
    "upload_gguf",
]

__version__ = "0.2.0"
DEFAULT_REPO_ID = "ray0rf1re/hyper-nix.1"
