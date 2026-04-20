"""Fetch the HyperNix model snapshot from the HuggingFace Hub."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from huggingface_hub import snapshot_download


def download_model(
    repo_id: str = "ray0rf1re/hyper-nix.1",
    revision: Optional[str] = None,
    cache_dir: Optional[str] = None,
    local_dir: Optional[str] = None,
    token: Optional[str] = None,
) -> Path:
    """Download the full model snapshot and return the local directory path.

    Args:
        repo_id: HuggingFace repo, defaults to ``ray0rf1re/hyper-nix.1``.
        revision: Optional git revision / branch / tag.
        cache_dir: Override HF cache directory.
        local_dir: If set, download directly to this directory.
        token: HF access token (or reads ``HF_TOKEN`` / ``HUGGING_FACE_HUB_TOKEN``).
    """
    patterns = [
        "*.json",
        "*.txt",
        "*.md",
        "*.model",
        "*.safetensors",
        "*.bin",
        "*.pt",
        "*.pth",
        "tokenizer*",
        "vocab*",
        "merges*",
        "special_tokens_map*",
    ]
    path = snapshot_download(
        repo_id=repo_id,
        revision=revision,
        cache_dir=cache_dir,
        local_dir=local_dir,
        token=token,
        allow_patterns=patterns,
    )
    return Path(path)
