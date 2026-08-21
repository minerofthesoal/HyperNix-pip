"""Push generated GGUF files to a HuggingFace repo."""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from huggingface_hub import HfApi, create_repo


def upload_gguf(
    files: Iterable[Path | str],
    repo_id: str = "ray0rf1re/HyperNix.1-gguf",
    token: str | None = None,
    commit_message: str = "Add HyperNix GGUF quantizations",
    private: bool = False,
    create_if_missing: bool = True,
) -> str:
    """Upload one or more GGUF files to a HuggingFace model repo.

    Returns the repo URL.
    """
    api = HfApi(token=token)
    if create_if_missing:
        create_repo(repo_id=repo_id, token=token, repo_type="model", private=private, exist_ok=True)

    paths = [Path(p) for p in files]
    for p in paths:
        if not p.exists():
            raise FileNotFoundError(p)

    if len(paths) == 1:
        p = paths[0]
        api.upload_file(
            path_or_fileobj=str(p),
            path_in_repo=p.name,
            repo_id=repo_id,
            repo_type="model",
            commit_message=commit_message,
        )
    else:
        # upload_folder is faster for multiple files; stage them via a common parent
        parents = {p.parent for p in paths}
        if len(parents) == 1:
            parent = next(iter(parents))
            api.upload_folder(
                folder_path=str(parent),
                repo_id=repo_id,
                repo_type="model",
                commit_message=commit_message,
                allow_patterns=[p.name for p in paths],
            )
        else:
            for p in paths:
                api.upload_file(
                    path_or_fileobj=str(p),
                    path_in_repo=p.name,
                    repo_id=repo_id,
                    repo_type="model",
                    commit_message=commit_message,
                )
    return f"https://huggingface.co/{repo_id}"
