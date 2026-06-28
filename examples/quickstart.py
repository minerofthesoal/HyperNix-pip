"""Minimal end-to-end example.

Downloads a HyperNix snapshot (default: chat-tuned ``hyper-Nix.2``;
pass ``REPO_ID=ray0rf1re/hyper-nix.1`` in the env to use the original
v1 instead — both are still fully supported), writes an fp16 GGUF,
then produces a sweep of quantizations using llama-quantize.

The quant list comes from :func:`hypernix.quant_recommended` so this
script automatically tracks the curated short-list (currently F16,
Q8_0, Q6_K, Q5_K_M, Q4_K_M).

Run:
    python examples/quickstart.py
    REPO_ID=ray0rf1re/hyper-nix.1 python examples/quickstart.py
"""
import os
from pathlib import Path

from hypernix import (
    convert_to_gguf,
    download_model,
    quant_recommended,
    quantize_gguf,
)

REPO_ID = os.environ.get("REPO_ID", "ray0rf1re/hyper-Nix.2")


def main() -> None:
    out = Path("hypernix-gguf")
    out.mkdir(exist_ok=True)

    model_dir = download_model(REPO_ID)
    fp16 = convert_to_gguf(model_dir, out / "hypernix-fp16.gguf", dtype="fp16")

    for spec in quant_recommended():
        if spec.name == "F16":
            continue  # already wrote it
        quantize_gguf(fp16, out / f"hypernix-{spec.name.lower()}.gguf", spec.name)

    print("wrote:", *sorted(out.glob("*.gguf")), sep="\n  ")


if __name__ == "__main__":
    main()
