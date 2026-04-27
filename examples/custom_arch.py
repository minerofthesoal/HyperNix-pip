"""Convert a custom-architecture HyperNix variant of any size.

Nothing is hard-coded: the converter introspects the state dict so this
script works for a tiny 92M checkpoint, a 1B variant, or anything else
ray0rf1re publishes under the HyperNix line.
"""
import argparse
from pathlib import Path

from hypernix import convert_to_gguf, download_model, quantize_gguf


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--repo-id", default="ray0rf1re/hyper-Nix.2",
        help="HF repo to convert (default: hyper-Nix.2 chat model; the original "
             "ray0rf1re/hyper-nix.1 is still fully supported).",
    )
    ap.add_argument("--out", default="./hypernix-gguf")
    ap.add_argument("--n-head", type=int, default=None, help="Override head count.")
    ap.add_argument("--ctx", type=int, default=None, help="Override context length.")
    ap.add_argument(
        "--quants",
        nargs="*",
        # v0.51.3: any of the 49 aliases in hypernix.QUANT_TYPES works
        # here — see `hypernix.quant_list_types()` for the full set.
        default=["fp32", "fp16", "q8_0", "q6_k", "q5_k_m", "q4_k_m"],
    )
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    model_dir = download_model(args.repo_id)

    produced: dict[str, Path] = {}
    if "fp32" in args.quants:
        produced["fp32"] = convert_to_gguf(
            model_dir, out / "fp32.gguf", dtype="fp32",
            n_head_hint=args.n_head, context_length=args.ctx,
        )
    if any(q not in {"fp32"} for q in args.quants):
        produced["fp16"] = convert_to_gguf(
            model_dir, out / "fp16.gguf", dtype="fp16",
            n_head_hint=args.n_head, context_length=args.ctx,
        )

    for q in args.quants:
        if q in {"fp32", "fp16"}:
            continue
        produced[q] = quantize_gguf(produced["fp16"], out / f"{q}.gguf", q)

    for q, p in produced.items():
        print(f"{q:<8} {p.stat().st_size / 1e6:8.1f} MB  {p}")


if __name__ == "__main__":
    main()
