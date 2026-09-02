"""``dflash2`` — put a draft model inside the model it drafts for.

    dflash2 attach model.Q4_K_M.gguf -o model.dflash2.gguf
    dflash2 info model.dflash2.gguf
    dflash2 extract model.dflash2.gguf -o draft.gguf
    dflash2 strip model.dflash2.gguf -o model.gguf

The attached file still runs anywhere the original ran: the draft's
tensors are namespaced and its metadata sits outside the keys upstream
uses, so a loader that has never heard of Dflash2 reads straight past it.
"""
from __future__ import annotations

import argparse
import json
import sys

from .dflash2 import (
    DEFAULT_DRAFT_TOKENS,
    Dflash2Error,
    attach,
    extract,
    read_draft_info,
    strip,
)

__all__ = ["main", "cli_main"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dflash2",
        description=(
            "Derive a draft model from a GGUF and carry it inside the same "
            "file, for speculative decoding. No llama.cpp binary is needed."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Speculative decoding produces exactly the tokens the base model\n"
            "would have produced alone -- a proposal is kept only where the base\n"
            "independently chose the same token. A poor draft costs time; it\n"
            "cannot cost correctness. `dflash2 info` reports the draft's size so\n"
            "you can see what the speed-up is costing you on disk.\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command")

    attach_parser = subparsers.add_parser("attach", help="Derive and embed a draft")
    attach_parser.add_argument("source")
    attach_parser.add_argument("-o", "--output", required=True)
    attach_parser.add_argument("--depth", type=float, default=0.25,
                               help="Fraction of the base's layers to keep (default 0.25)")
    attach_parser.add_argument("--layers", default="",
                               help="Explicit comma-separated layer indices instead")
    attach_parser.add_argument("--quant", default="Q4_0",
                               help="Block format for the draft's weights")
    attach_parser.add_argument("--draft-tokens", type=int, default=DEFAULT_DRAFT_TOKENS,
                               help="Tokens the draft proposes per round")
    attach_parser.add_argument("--no-share-embeddings", dest="share", action="store_false",
                               help="Give the draft its own copy of the embedding "
                                    "and output tensors instead of the base's")
    attach_parser.add_argument("--json", dest="as_json", action="store_true")
    attach_parser.add_argument("-q", "--quiet", action="store_true")

    info_parser = subparsers.add_parser("info", help="What draft a file carries")
    info_parser.add_argument("source")
    info_parser.add_argument("--json", dest="as_json", action="store_true")

    extract_parser = subparsers.add_parser(
        "extract", help="Write the embedded draft out as its own GGUF"
    )
    extract_parser.add_argument("source")
    extract_parser.add_argument("-o", "--output", required=True)

    strip_parser = subparsers.add_parser("strip", help="Remove the draft")
    strip_parser.add_argument("source")
    strip_parser.add_argument("-o", "--output", required=True)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2

    try:
        if args.command == "attach":
            layers = None
            if args.layers:
                try:
                    layers = [int(part) for part in args.layers.split(",") if part.strip()]
                except ValueError:
                    print("dflash2: --layers wants comma-separated integers",
                          file=sys.stderr)
                    return 2

            def _progress(event: dict) -> None:
                if args.quiet or args.as_json or event.get("event") != "tensor":
                    return
                mark = "draft" if event["draft"] else "copy "
                print(f"  [{event['index']:>4}/{event['total']}] {mark} {event['name']}",
                      file=sys.stderr)

            report = attach(
                args.source, args.output,
                layers=layers,
                depth=args.depth,
                quant=args.quant,
                draft_tokens=args.draft_tokens,
                share_embeddings=args.share,
                progress=None if args.quiet else _progress,
            )
            if args.as_json:
                print(json.dumps(report.to_dict(), indent=2))
            elif not args.quiet:
                print(report.describe())
                print(f"dflash2: wrote {args.output}")
            return 0

        if args.command == "info":
            info = read_draft_info(args.source)
            if args.as_json:
                print(json.dumps(info, indent=2))
                return 0
            if not info["present"]:
                print(f"{args.source}: no Dflash2 draft.")
                return 0
            print(f"{args.source}: Dflash2 v{info['version']}")
            print(f"  layers      : {info['block_count']} of "
                  f"{info['source_block_count']} ({info['layer_map']})")
            print(f"  quant       : {info['quant']}")
            print(f"  draft tokens: {info['draft_tokens']} per round")
            print(f"  size        : {info['bytes'] / 1e6:.1f} MB "
                  f"in {info['tensors']} tensor(s)")
            if info["shared"]:
                print(f"  shared      : {', '.join(info['shared'])}")
            return 0

        if args.command == "extract":
            result = extract(args.source, args.output)
            print(f"dflash2: wrote {result['path']} "
                  f"({result['bytes'] / 1e6:.1f} MB, {result['tensors']} tensors, "
                  f"{result['block_count']} blocks)")
            return 0

        result = strip(args.source, args.output)
        print(f"dflash2: wrote {result['path']} ({result['bytes'] / 1e6:.1f} MB)")
        return 0
    except Dflash2Error as exc:
        print(f"dflash2: {exc}", file=sys.stderr)
        return 1


def cli_main() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    cli_main()
