"""``hnx-imatrix`` — measure an importance matrix, or convert one.

    hnx-imatrix measure ./Llama-3.2-1B -t calibration.txt -o model.imatrix
    hnx-imatrix convert model.imatrix -o model.json
    hnx-imatrix show model.imatrix

Measuring runs the model, so it needs a Hugging Face checkpoint rather
than a GGUF — the tensor names match either way, so the result applies
to the GGUF you convert from it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .imatrix import Imatrix, ImatrixError, collect_from_pretrained

__all__ = ["main", "cli_main"]


def _read_texts(paths: list[str]) -> list[str]:
    texts = []
    for entry in paths:
        path = Path(entry)
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and child.suffix in (".txt", ".md", ".jsonl"):
                    texts.append(child.read_text(encoding="utf-8", errors="replace"))
        elif path.exists():
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
        else:
            # A literal string, so `-t "some prose"` works for a quick check.
            texts.append(entry)
    return texts


def _add_measure(subparsers) -> None:
    parser = subparsers.add_parser(
        "measure", help="Run calibration text through a model and record it"
    )
    parser.add_argument("model", help="Hugging Face checkpoint directory or id")
    parser.add_argument("-t", "--text", action="append", default=[],
                        help="Calibration file, directory, or literal text. Repeatable.")
    parser.add_argument("-o", "--output", required=True,
                        help="Where to write it (.imatrix for llama.cpp's format)")
    parser.add_argument("--chunk-tokens", type=int, default=512)
    parser.add_argument("--max-chunks", type=int, default=None,
                        help="Stop after this many chunks (a quick, worse imatrix)")
    parser.add_argument("--device", default=None, help="e.g. cuda, mps")
    parser.add_argument("--json", dest="as_json", action="store_true",
                        help="Write JSON even if --output does not end in .json")
    parser.add_argument("--simple", action="store_true",
                        help="JSON as a bare {tensor: [weights]} mapping")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hnx-imatrix",
        description=(
            "Measure an importance matrix, or convert between llama.cpp's "
            "binary format and JSON. Nothing here needs llama.cpp."
        ),
    )
    subparsers = parser.add_subparsers(dest="command")
    _add_measure(subparsers)

    convert = subparsers.add_parser("convert", help="Between .imatrix and .json")
    convert.add_argument("source")
    convert.add_argument("-o", "--output", required=True)
    convert.add_argument("--simple", action="store_true",
                         help="JSON as a bare {tensor: [weights]} mapping")

    show = subparsers.add_parser("show", help="What is in one")
    show.add_argument("source")
    show.add_argument("-n", "--tensors", type=int, default=10,
                      help="How many tensor names to list")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2

    try:
        if args.command == "measure":
            texts = _read_texts(args.text)
            if not texts:
                print(
                    "hnx-imatrix: no calibration text. An imatrix measured on "
                    "nothing is not a faster imatrix, it is no imatrix.",
                    file=sys.stderr,
                )
                return 2
            matrix = collect_from_pretrained(
                args.model, texts,
                chunk_tokens=args.chunk_tokens,
                max_chunks=args.max_chunks,
                device=args.device,
                dataset=",".join(args.text),
                progress=lambda event: print(
                    f"  {event['chunks']} chunk(s), {event['tokens']} token(s)",
                    file=sys.stderr,
                ),
            )
            _write(matrix, args.output, as_json=args.as_json, simple=args.simple)
            print(matrix.describe())
            print(f"hnx-imatrix: wrote {args.output}")
            return 0

        if args.command == "convert":
            matrix = Imatrix.load(args.source)
            _write(matrix, args.output, as_json=False, simple=args.simple)
            print(f"hnx-imatrix: wrote {args.output} ({len(matrix)} tensors)")
            return 0

        matrix = Imatrix.load(args.source)
        print(matrix.describe())
        for name in sorted(matrix.entries)[: args.tensors]:
            entry = matrix.entries[name]
            values = entry.means
            top = max(values) if values else 0.0
            print(f"  {name:34} {len(values):6d} channels  peak {top:.4g}")
        if len(matrix) > args.tensors:
            print(f"  ... and {len(matrix) - args.tensors} more")
        return 0
    except ImatrixError as exc:
        print(f"hnx-imatrix: {exc}", file=sys.stderr)
        return 1


def _write(matrix: Imatrix, output: str, *, as_json: bool, simple: bool) -> None:
    """JSON when the name says so, llama.cpp's binary otherwise."""
    if as_json or simple or output.endswith(".json"):
        matrix.save_json(output, simple=simple)
    else:
        matrix.save_binary(output)


def cli_main() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    cli_main()
