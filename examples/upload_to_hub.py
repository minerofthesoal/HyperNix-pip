"""Push the generated GGUFs to ray0rf1re/HyperNix.1-gguf.

Log in first:
    huggingface-cli login
or set ``HF_TOKEN`` in the environment.
"""
from pathlib import Path

from hypernix.upload import upload_gguf


def main() -> None:
    files = sorted(Path("hypernix-gguf").glob("*.gguf"))
    if not files:
        raise SystemExit("No GGUF files found in ./hypernix-gguf — run the converter first.")

    url = upload_gguf(
        files=files,
        repo_id="ray0rf1re/HyperNix.1-gguf",
        commit_message="Add fp32/fp16/Q8_0/Q6_K/Q4_K_M HyperNix quantizations",
    )
    print("uploaded ->", url)


if __name__ == "__main__":
    main()
