"""``steamroller`` — the descending quantiser, from the command line."""
from __future__ import annotations

import argparse
import json
import sys

from .steamroller import SOURCE_FORMATS, TIERS, Steamroller, SteamrollerError, plan

__all__ = ["main", "cli_main"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="steamroller",
        description="Roll a model down to a narrower quantisation, staging through Q3_K_L.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Tiers: " + ", ".join(TIERS) + "\n"
            "Sources: " + ", ".join(SOURCE_FORMATS) + "\n\n"
            "The IQ0.x tiers are HyperNix extension types, not upstream llama.cpp quant\n"
            "types: stock llama.cpp will refuse the resulting GGUF. Below ~1.5 bits a model\n"
            "stops being a worse version of itself — evaluate before shipping one.\n"
        ),
    )
    parser.add_argument("source", nargs="?", help="Input GGUF")
    parser.add_argument("target", nargs="?", help="Target tier, e.g. IQ1_M")
    parser.add_argument("-o", "--output", help="Output path")
    parser.add_argument("--source-format", default="FP16", choices=list(SOURCE_FORMATS))
    parser.add_argument("--imatrix", help="Importance matrix (strongly advised below 3 bits)")
    parser.add_argument("--parameters", type=float, default=0,
                        help="Parameter count, for a size estimate (e.g. 7e9)")
    parser.add_argument("--no-staging", action="store_true",
                        help="Skip the Q3_K_L staging pass (worse output; ignored for "
                             "extension tiers, which are packed from it)")
    parser.add_argument("--keep-intermediates", action="store_true")
    parser.add_argument("--plan", action="store_true", help="Show the plan and stop")
    parser.add_argument("--list-tiers", action="store_true")
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args(argv)

    if args.list_tiers:
        for tier in TIERS.values():
            mark = "upstream" if tier.upstream else "HyperNix extension"
            print(f"  {tier.name:12} {tier.bits_per_weight:5.2f} bits  {mark:18} {tier.summary}")
        return 0

    if not args.source or not args.target:
        parser.error("source and target are required (or use --list-tiers)")

    try:
        if args.plan:
            the_plan = plan(
                args.source_format, args.target,
                parameters=int(args.parameters),
                have_imatrix=bool(args.imatrix),
                force_staging=False if args.no_staging else None,
            )
            if args.as_json:
                print(json.dumps(the_plan.to_dict(), indent=2))
            else:
                print(the_plan.describe())
                for step in the_plan.steps:
                    print(f"  {step.index}. {step.kind:9} -> {step.target:12} {step.reason}")
                for warning in the_plan.warnings:
                    print(f"  ! {warning}")
            return 0

        output = args.output or f"{args.source.rsplit('.', 1)[0]}.{args.target}.gguf"
        result = Steamroller(keep_intermediates=args.keep_intermediates).run(
            args.source, args.target, output,
            source_format=args.source_format,
            imatrix=args.imatrix,
            parameters=int(args.parameters),
            force_staging=False if args.no_staging else None,
        )
    except SteamrollerError as exc:
        print(f"steamroller: {exc}", file=sys.stderr)
        if exc.hint:
            print(f"  {exc.hint}", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        for step in result["steps"]:
            print(f"  {step['index']}. {step['target']:12} {step['bytes'] / 1e9:6.2f} GB"
                  f"  {step['seconds']:6.1f}s")
        print(f"steamroller: wrote {result['output']} ({result['bytes'] / 1e9:.2f} GB)")
        for warning in result.get("warnings", []):
            print(f"  ! {warning}")
    return 0


def cli_main() -> None:
    raise SystemExit(main())
