"""Fetch the HyperNix model snapshot from the HuggingFace Hub.

The downloader pulls every file a HuggingFace-style checkpoint needs to
round-trip through :mod:`hypernix.convert`:

* model weights (safetensors / bin / loose .pt)
* config.json and generation_config.json
* tokenizer files (tokenizer.json, tokenizer.model, vocab*, merges*,
  special_tokens_map.json, tokenizer_config.json, added_tokens.json,
  chat_template.json / chat_template.jinja)
* any index.json sharded-weight manifests

After the download completes we run :func:`verify_snapshot` to make sure
the resulting directory can actually be consumed by ``hypernix convert``
— i.e. it contains at least one weight file *and* a ``config.json``.
"""
from __future__ import annotations

import sys
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download

# Files we always try to pull. The list is intentionally explicit so the
# reader can see exactly what's considered "needed", and the glob fallbacks
# (``*.json`` etc.) still cover anything unusual.
REQUIRED_PATTERNS: list[str] = [
    # Every JSON in the repo root (config.json, generation_config.json,
    # tokenizer.json, tokenizer_config.json, special_tokens_map.json,
    # added_tokens.json, preprocessor_config.json, *.index.json, ...).
    "*.json",
    # Tokenizer flavours.
    "tokenizer.*",                   # tokenizer.json / tokenizer.model
    "tokenizer_config.*",
    "special_tokens_map.*",
    "added_tokens.*",
    "vocab.*",                       # vocab.json / vocab.txt
    "merges.*",                      # merges.txt
    "spiece.model",                  # T5-style SentencePiece
    "sentencepiece.bpe.model",
    "chat_template.*",               # chat_template.json / .jinja
    "*.tiktoken",
    # Weights — safetensors (single + sharded) and pickled variants.
    "*.safetensors",
    "*.safetensors.index.json",
    "pytorch_model*.bin",
    "pytorch_model.bin.index.json",
    "*.pt",
    "*.pth",
    # Misc.
    "*.txt",
    "*.md",
    "*.model",
    "LICENSE*",
    "README*",
]

# Files that MUST exist after a successful download for `hypernix convert` to
# work. Weights are checked via a glob in :func:`verify_snapshot` — any of the
# accepted weight patterns satisfies the requirement.
_REQUIRED_FILES = ("config.json",)
_WEIGHT_GLOBS = ("*.safetensors", "pytorch_model*.bin", "*.pt", "*.pth", "*.bin")


def verify_snapshot(model_dir: Path | str) -> list[str]:
    """Verify a downloaded snapshot contains everything `convert` needs.

    Returns a sorted list of the actual filenames present. Raises
    ``FileNotFoundError`` with a specific message if ``config.json`` or any
    weight file is missing — that's almost always the reason downstream
    conversion fails.
    """
    model_dir = Path(model_dir)
    if not model_dir.exists():
        raise FileNotFoundError(f"snapshot directory does not exist: {model_dir}")
    present = sorted(p.name for p in model_dir.iterdir() if p.is_file())

    missing_required = [f for f in _REQUIRED_FILES if not (model_dir / f).exists()]
    has_weights = any(next(model_dir.glob(pat), None) for pat in _WEIGHT_GLOBS)

    problems: list[str] = []
    if missing_required:
        problems.append("missing required metadata: " + ", ".join(missing_required))
    if not has_weights:
        problems.append(
            "no weight files found (looked for: " + ", ".join(_WEIGHT_GLOBS) + ")"
        )
    if problems:
        raise FileNotFoundError(
            f"snapshot at {model_dir} is incomplete: "
            + "; ".join(problems)
            + f". Got {len(present)} file(s): {present[:20]}"
            + ("..." if len(present) > 20 else "")
        )
    return present


def download_model(
    repo_id: str = "ray0rf1re/hyper-nix.1",
    revision: str | None = None,
    cache_dir: str | None = None,
    local_dir: str | None = None,
    token: str | None = None,
    quiet: bool = False,
    verify: bool = True,
) -> Path:
    """Download a full HuggingFace model snapshot and return its directory.

    Args:
        repo_id: HuggingFace repo, defaults to ``ray0rf1re/hyper-nix.1``.
        revision: Git revision / branch / tag.
        cache_dir: Override the HF cache directory.
        local_dir: If set, download directly to this directory instead of
            the blob-store cache.
        token: HF access token (or reads ``HF_TOKEN`` /
            ``HUGGING_FACE_HUB_TOKEN``).
        quiet: Suppress the per-file listing.
        verify: After download, raise if ``config.json`` or any weight file
            is missing.
    """
    def log(msg: str) -> None:
        if not quiet:
            print(f"[hypernix] {msg}", file=sys.stderr)

    log(f"downloading {repo_id} ...")
    path = Path(
        snapshot_download(
            repo_id=repo_id,
            revision=revision,
            cache_dir=cache_dir,
            local_dir=local_dir,
            token=token,
            allow_patterns=REQUIRED_PATTERNS,
        )
    )

    # Safety net: some repos put ``config.json`` behind a non-default branch
    # or embed it only in a README; if it wasn't picked up by the glob,
    # try a single-file fetch as a last resort.
    if not (path / "config.json").exists():
        try:
            hf_hub_download(
                repo_id=repo_id,
                filename="config.json",
                revision=revision,
                cache_dir=cache_dir,
                local_dir=local_dir or str(path),
                token=token,
            )
        except Exception as exc:  # noqa: BLE001
            log(f"WARNING: config.json missing and single-file fetch failed: {exc}")

    if verify:
        present = verify_snapshot(path)
    else:
        present = sorted(p.name for p in path.iterdir() if p.is_file())

    log(f"snapshot at {path} ({len(present)} files)")
    for name in present:
        log(f"  - {name}")
    return path
