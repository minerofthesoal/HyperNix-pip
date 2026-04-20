"""HyperNix: convert ray0rf1re/hyper-nix.1 PyTorch weights to GGUF."""
from __future__ import annotations

from .convert import convert_to_gguf
from .download import download_model
from .fetcher import fetch_llama_quantize
from .quantize import QUANT_TYPES, quantize_gguf
from .upload import upload_gguf

__all__ = [
    "QUANT_TYPES",
    "convert_to_gguf",
    "download_model",
    "fetch_llama_quantize",
    "quantize_gguf",
    "upload_gguf",
]

__version__ = "0.1.3"
DEFAULT_REPO_ID = "ray0rf1re/hyper-nix.1"
