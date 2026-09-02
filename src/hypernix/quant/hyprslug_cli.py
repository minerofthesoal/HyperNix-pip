"""``hyprslug`` — quantise a GGUF without llama.cpp.

Also installed as ``doomslug``, ``doomslugthedestroyer`` and ``dstd``.

    hyprslug model.f16.gguf Q4_K_M -o model.q4km.gguf
    hyprslug model.f16.gguf IQ0.5_XXXL -o model.iq05.gguf
    doomslug model.q8_0.gguf Q4_K_M --imatrix imatrix.json
    dstd --list-tiers
"""
from __future__ import annotations

import argparse
import json
import sys

from .hyprslug import (
    ALIASES,
    RECIPES,
    TIER_TYPES,
    HyprslugError,
    quantize_gguf,
)
from .subbit import PACKINGS

__all__ = ["main", "cli_main"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hyprslug",
        description=(
            "Quantise a GGUF to a llama.cpp quant type or a HyperNix sub-bit "
            "tier. No llama.cpp binary is looked for, downloaded or built at "
            "any point, for either."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Also answers to: " + ", ".join(a for a in ALIASES if a != "hyprslug") + "\n\n"
            "The Q* targets are upstream llama.cpp types and produce a GGUF any\n"
            "llama.cpp reads. The IQ0.x tiers are HyperNix extension types and\n"
            "stock llama.cpp will refuse those by name — which is the point of the\n"
            "type ids being far above anything upstream has allocated. Below ~1.5\n"
            "bits a model stops being a worse version of itself; evaluate before\n"
            "shipping one.\n"
        ),
    )
    parser.add_argument("source", nargs="?",
                        help="Input GGUF (unquantised, or an existing quant "
                             "to requantise from)")
    parser.add_argument("tier", nargs="?",
                        help="Target, e.g. Q4_K_M or IQ0.5_XXXL")
    parser.add_argument("-o", "--output", help="Output path")
    parser.add_argument("--imatrix", help="Importance matrix as JSON: {tensor: [weights]}")
    parser.add_argument("--quantize-embeddings", action="store_true", default=None,
                        help="Include token embeddings (they dominate a small model)")
    parser.add_argument("--no-quantize-embeddings", dest="quantize_embeddings",
                        action="store_false", help="Leave token embeddings alone")
    parser.add_argument("--quantize-output", action="store_true", default=None,
                        help="Include the output head")
    parser.add_argument("--no-quantize-output", dest="quantize_output",
                        action="store_false", help="Leave the output head alone")
    parser.add_argument("--list-tiers", action="store_true")
    parser.add_argument("--json", dest="as_json", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)

    if args.list_tiers:
        # --json applies here too; this branch used to return before ever
        # looking at it, so a script that asked for JSON got a human
        # table and a parse error.
        if args.as_json:
            print(json.dumps({
                "recipes": [
                    {
                        "name": name,
                        "base": recipe.base,
                        "bits_per_weight": round(recipe.bits_per_weight, 3),
                        "overrides": {frag: fmt for frag, fmt in recipe.overrides},
                        "output": recipe.output,
                        "upstream": True,
                        "summary": recipe.summary,
                    }
                    for name, recipe in sorted(
                        RECIPES.items(), key=lambda kv: -kv[1].bits_per_weight
                    )
                ],
                "sub_bit_tiers": [
                    {
                        "name": tier,
                        "ggml_type": type_id,
                        "packing": packing,
                        "bits_per_weight": PACKINGS[packing].bits_per_weight,
                        "signs_kept": PACKINGS[packing].kept,
                        "group": PACKINGS[packing].group,
                        "upstream": False,
                        "summary": (
                            "HyperNix extension type; stock llama.cpp refuses it by name."
                        ),
                    }
                    for tier, (type_id, packing) in TIER_TYPES.items()
                ],
            }, indent=2))
            return 0
        print("llama.cpp quant types (any llama.cpp reads the result):")
        for name, recipe in sorted(
            RECIPES.items(), key=lambda kv: -kv[1].bits_per_weight
        ):
            widened = ", ".join(sorted({fmt for _, fmt in recipe.overrides}))
            note = f"  wider: {widened}" if widened else ""
            print(f"  {name:8} {recipe.bits_per_weight:5.2f} bits/weight  "
                  f"{recipe.summary}{note}")
        print()
        print("HyperNix sub-bit tiers (stock llama.cpp refuses these by name):")
        for tier, (type_id, packing) in TIER_TYPES.items():
            spec = PACKINGS[packing]
            print(
                f"  {tier:12} {spec.bits_per_weight:5.3f} bits/weight  "
                f"type {type_id}  {spec.kept} of every {spec.group} signs kept"
            )
        return 0

    if not args.source or not args.tier:
        parser.error("source and tier are required (or use --list-tiers)")

    output = args.output or f"{args.source.rsplit('.', 1)[0]}.{args.tier}.gguf"

    def _progress(event: dict) -> None:
        if args.quiet or args.as_json or event.get("event") != "tensor":
            return
        mark = "pack" if event["quantized"] else "copy"
        print(f"  [{event['index']:>4}/{event['total']}] {mark} {event['name']}",
              file=sys.stderr)

    try:
        report = quantize_gguf(
            args.source, output, args.tier,
            imatrix=args.imatrix,
            quantize_embeddings=args.quantize_embeddings,
            quantize_output=args.quantize_output,
            progress=None if args.quiet else _progress,
        )
    except HyprslugError as exc:
        print(f"hyprslug: {exc}", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps(report.to_dict(), indent=2))
    elif not args.quiet:
        print(report.describe())
        print(f"hyprslug: wrote {output}")
    return 0


def cli_main() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    cli_main()
