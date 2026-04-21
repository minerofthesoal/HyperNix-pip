"""HyperNix: convert ray0rf1re/hyper-nix.1 PyTorch weights to GGUF."""
from __future__ import annotations

from . import old_oven
from .convert import convert_to_gguf
from .download import (
    KNOWN_MODELS,
    ModelInfo,
    download_model,
    resolve_model_info,
    resolve_repo_id,
    verify_snapshot,
)
from .fetcher import fetch_llama_quantize
from .generate import generate_text
from .old_oven import (
    ARCH_PRESETS,
    CodeOven,
    bake_code,
    fill_middle,
    load_pt,
    new_oven,
    preheat,
)
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
    "ARCH_PRESETS",
    "CodeOven",
    "HyperNixConfig",
    "HyperNixModel",
    "KNOWN_MODELS",
    "ModelInfo",
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
    "new_oven",
    "old_oven",
    "preheat",
    "quantize_gguf",
    "resolve_model_info",
    "resolve_repo_id",
    "save_snapshot",
    "train",
    "upload_gguf",
    "verify_snapshot",
]

__version__ = "0.31.1"
DEFAULT_REPO_ID = "ray0rf1re/hyper-nix.1"
