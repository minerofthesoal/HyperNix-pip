"""Minimal end-to-end example.

Downloads ray0rf1re/hyper-nix.1, writes an fp16 GGUF, then produces
Q8_0 / Q6_K / Q4_K_M quantizations using llama-quantize.

Run:
    python examples/quickstart.py
"""
from pathlib import Path

from hypernix import convert_to_gguf, download_model, quantize_gguf


def main() -> None:
    out = Path("hypernix-gguf")
    out.mkdir(exist_ok=True)

    model_dir = download_model("ray0rf1re/hyper-nix.1")
    fp16 = convert_to_gguf(model_dir, out / "hyper-nix-fp16.gguf", dtype="fp16")

    for q in ("q8_0", "q6_k", "q4_k_m"):
        quantize_gguf(fp16, out / f"hyper-nix-{q}.gguf", q)

    print("wrote:", *sorted(out.glob("*.gguf")), sep="\n  ")


if __name__ == "__main__":
    main()
