"""scriptgen.cli — ``hnx scriptgen``.

Opens the GUI by default and falls back to generating from the command
line when there is no display. That fallback is the point: the machine
with the GPU is frequently a headless box, and a script builder that
only works where there is a window is a script builder you use on the
wrong machine and then scp from.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from .app import FormModel, launch
from .params import ALL_PARAMS, GROUPS
from .widgets import tk_available

__all__ = ["main", "cli_main"]


def _parse_set(pairs: list[str]) -> dict[str, Any]:
    """``--set learning_rate=3e-5`` into a values dict."""
    values: dict[str, Any] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit(f"--set needs name=value, got {pair!r}")
        name, _, raw = pair.partition("=")
        name = name.strip()
        if name not in ALL_PARAMS:
            close = [n for n in ALL_PARAMS if n.startswith(name[:4])][:5]
            raise SystemExit(
                f"Unknown parameter {name!r}"
                + (f". Did you mean: {', '.join(close)}?" if close else "")
            )
        values[name] = raw.strip()
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hnx scriptgen",
        description="Build a HyperNix training script, in a GUI or from the command line.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  hnx scriptgen                                  open the GUI\n"
            "  hnx scriptgen --cli -o train.py                generate with defaults\n"
            "  hnx scriptgen --cli --set learning_rate=3e-5 --set epochs=2 -o train.py\n"
            "  hnx scriptgen --cli --inject existing.py       inject a config block\n"
            "  hnx scriptgen --list-params                    every parameter and its range\n"
        ),
    )
    parser.add_argument("--cli", action="store_true", help="Skip the GUI")
    parser.add_argument("-o", "--output", help="Write the script here")
    parser.add_argument("--inject", metavar="SCRIPT",
                        help="Inject a config block into an existing script")
    parser.add_argument("--config-only", action="store_true",
                        help="Emit only the config, not a whole script")
    parser.add_argument("--format", choices=("python", "json", "env"), default="python")
    parser.add_argument("--set", action="append", dest="sets", metavar="NAME=VALUE",
                        help="Set a parameter (repeatable)")
    parser.add_argument("--preset", help="Load a preset .json first")
    parser.add_argument("--list-params", action="store_true",
                        help="List every parameter, then exit")
    args = parser.parse_args(argv)

    if args.list_params:
        return _list_params()

    model = FormModel()
    if args.preset:
        try:
            rejected = model.load_json(Path(args.preset).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"scriptgen: {exc}", file=sys.stderr)
            return 1
        for message in rejected:
            print(f"scriptgen: skipped — {message}", file=sys.stderr)

    problems = []
    for name, raw in _parse_set(args.sets or []).items():
        ok, message = model.set(name, raw)
        if not ok:
            problems.append(message)
    if problems:
        for message in problems:
            print(f"scriptgen: {message}", file=sys.stderr)
        return 1

    if args.inject:
        model.mode = "inject"
        model.target_path = Path(args.inject)
    elif args.config_only:
        model.mode = "config"
        model.config_format = args.format

    wants_gui = not (args.cli or args.output or args.inject or args.config_only)
    if wants_gui:
        ok, reason = tk_available()
        if ok:
            return launch(model.values)
        # Not an error: a headless machine is the normal case here.
        print(f"scriptgen: no GUI available — {reason}", file=sys.stderr)
        print("scriptgen: falling back to command-line generation.\n", file=sys.stderr)

    errors, warnings = model.validate()
    for warning in warnings:
        print(f"scriptgen: note — {warning}", file=sys.stderr)
    if errors:
        for error in errors:
            print(f"scriptgen: {error}", file=sys.stderr)
        return 1

    existing = ""
    if args.inject:
        target = Path(args.inject)
        if not target.exists():
            print(f"scriptgen: {args.inject} does not exist", file=sys.stderr)
            return 1
        existing = target.read_text(encoding="utf-8", errors="replace")

    output = model.preview(existing)
    destination = args.output or (args.inject if args.inject else "")
    if destination:
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        Path(destination).write_text(output, encoding="utf-8")
        print(f"scriptgen: wrote {destination} ({len(output.splitlines())} lines)")
    else:
        print(output)
    return 0


def _list_params() -> int:
    for group in GROUPS:
        print(f"\n{group.title}  —  {group.description}")
        for param in group.params:
            bounds = ""
            if param.minimum is not None or param.maximum is not None:
                bounds = f"  [{param.minimum} … {param.maximum}]"
            elif param.choices:
                bounds = "  {" + ", ".join(c[0] for c in param.choices) + "}"
            flag = " (advanced)" if param.advanced else ""
            print(f"  {param.name:26} {str(param.default):<22}{bounds}{flag}")
            if param.hint:
                print(f"  {'':26} {param.hint}")
    return 0


def cli_main() -> None:
    raise SystemExit(main())
