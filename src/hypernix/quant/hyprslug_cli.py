"""``hyprslug`` — quantise a GGUF without llama.cpp.

Also installed as ``doomslug``, ``doomslugthedestroyer`` and ``dstd``.

    hyprslug model.f16.gguf IQ0.5_XXXL -o model.iq05.gguf
    doomslug model.f16.gguf IQ0.9_L --imatrix imatrix.json
    dstd --list-tiers
"""
from __future__ import annotations

import argparse
import json
import sys

from .hyprslug import ALIASES, TIER_TYPES, HyprslugError, quantize_gguf
from .subbit import PACKINGS

__all__ = ["main", "cli_main"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hyprslug",
        description=(
            "Quantise a GGUF to a HyperNix sub-bit tier. No llama.cpp binary is "
            "looked for, downloaded or built at any point."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Also answers to: " + ", ".join(a for a in ALIASES if a != "hyprslug") + "\n\n"
            "These are HyperNix extension types. Stock llama.cpp will refuse the\n"
            "resulting GGUF by name — which is the point of the type ids being far\n"
            "above anything upstream has allocated. Below ~1.5 bits a model stops\n"
            "being a worse version of itself; evaluate before shipping one.\n"
        ),
    )
    parser.add_argument("source", nargs="?", help="Input GGUF (F32, F16 or BF16)")
    parser.add_argument("tier", nargs="?", help="Target tier, e.g. IQ0.5_XXXL")
    parser.add_argument("-o", "--output", help="Output path")
    parser.add_argument("--imatrix", help="Importance matrix as JSON: {tensor: [weights]}")
    parser.add_argument("--quantize-embeddings", action="store_true",
                        help="Include token embeddings (they dominate a small model)")
    parser.add_argument("--quantize-output", action="store_true",
                        help="Include the output head")
    parser.add_argument("--list-tiers", action="store_true")
    parser.add_argument("--json", dest="as_json", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args(argv)

    if args.list_tiers:
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
