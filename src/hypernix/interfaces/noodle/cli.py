"""``noodle`` — run a swarm from the command line."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .providers import PROVIDERS, ProviderError, available_providers
from .swarm import Swarm
from .validate import combine, command_verifier, syntax_verifier

__all__ = ["main", "cli_main"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="noodle",
        description="Run one or more AI agents against a task, in a sandboxed workspace.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  noodle --providers                              what this machine can use\n"
            "  noodle -m ollama:llama3.2 'write fizzbuzz.py'\n"
            "  noodle -m ollama:llama3.2 -m anthropic -f tasks.txt --parallel 2\n"
            "  noodle -m ollama:llama3.2 --execute --verify 'pytest -q' 'fix the failing test'\n"
            "\n"
            "--execute lets agents run code they wrote. It is off by default, and it should\n"
            "stay off unless the workspace is disposable.\n"
        ),
    )
    parser.add_argument("task", nargs="*", help="The task, as free text")
    parser.add_argument("-m", "--model", action="append", dest="roster", metavar="PROVIDER[:MODEL]",
                        help="Add a model to the roster (repeatable)")
    parser.add_argument("-f", "--tasks-file", help="One task per line")
    parser.add_argument("-w", "--workspace", default="./noodle-work",
                        help="Sandbox root (default ./noodle-work)")
    parser.add_argument("--parallel", type=int, default=4)
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--execute", action="store_true",
                        help="Allow agents to run code they wrote")
    parser.add_argument("--memory", action="store_true",
                        help="Allow durable memory (server-enabled equivalent)")
    parser.add_argument("--verify", metavar="COMMAND",
                        help="Shell-free command to verify the work, e.g. 'pytest -q'")
    parser.add_argument("--no-syntax-check", action="store_true")
    parser.add_argument("--providers", action="store_true",
                        help="List providers and whether this machine has credentials")
    parser.add_argument("--json", dest="as_json", action="store_true")
    parser.add_argument("--quiet", action="store_true", help="Only print the summary")
    args = parser.parse_args(argv)

    if args.providers:
        usable = {s.provider for s in available_providers()}
        for spec in PROVIDERS.values():
            mark = "ready" if spec.provider in usable else "no credential"
            keys = ", ".join(spec.env_keys) or "none needed"
            print(f"  {spec.label:22} {mark:14} {spec.wire:10} {keys}")
        return 0

    tasks: list[str] = []
    if args.tasks_file:
        try:
            tasks = [
                line.strip()
                for line in Path(args.tasks_file).read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")
            ]
        except OSError as exc:
            print(f"noodle: {exc}", file=sys.stderr)
            return 1
    if args.task:
        tasks.append(" ".join(args.task))
    if not tasks:
        parser.error("give a task, or -f a file of them")

    roster = args.roster or [s.provider.value for s in available_providers()][:1]
    if not roster:
        print(
            "noodle: no usable model. Set a provider key, or run Ollama locally.\n"
            "        `noodle --providers` lists what each one needs.",
            file=sys.stderr,
        )
        return 1

    verifiers = []
    if not args.no_syntax_check:
        verifiers.append(syntax_verifier())
    if args.verify:
        verifiers.append(command_verifier(args.verify.split()))
    verifier = combine(*verifiers) if verifiers else None

    def on_event(event) -> None:
        if args.quiet or args.as_json:
            return
        detail = event.detail
        if event.kind == "thought" and detail.get("text"):
            print(f"  [{event.agent}] {str(detail['text'])[:160]}")
        elif event.kind == "tool_call":
            print(f"  [{event.agent}] -> {detail.get('tool')}({_brief(detail.get('arguments'))})")
        elif event.kind == "tool_result" and not detail.get("ok"):
            print(f"  [{event.agent}] !! {detail.get('tool')}: {str(detail.get('preview'))[:120]}")
        elif event.kind == "correction":
            print(f"  [{event.agent}] correcting (attempt {detail.get('attempt')})")

    try:
        swarm = Swarm(
            roster=roster, root=args.workspace, max_parallel=args.parallel,
            allow_execute=args.execute, memory_enabled=args.memory,
            verifier=verifier, on_event=on_event,
        )
    except (ProviderError, ValueError) as exc:
        print(f"noodle: {exc}", file=sys.stderr)
        return 1

    if not args.quiet and not args.as_json:
        for entry in swarm.describe_roster():
            print(f"  roster: {entry['label']} ({entry['model']})")
        print(f"  workspace: {Path(args.workspace).resolve()}")
        if args.execute:
            print("  execution: ENABLED — agents may run code they wrote")
        print()

    for task in tasks:
        swarm.submit(task, max_turns=args.max_turns)
    report = swarm.run()

    if args.as_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print()
        for result in report.results:
            mark = "ok " if result.ok else "FAIL"
            print(f"  {mark} {result.agent:10} {result.provider:10} "
                  f"{result.turns:2} turns  {result.tool_calls:2} tools  "
                  f"{result.seconds:6.1f}s")
            if result.error:
                print(f"       {result.error[:150]}")
        inp, out = report.total_tokens
        print(f"\n  {len(report.results)} task(s), {len(report.failed)} failed, "
              f"{inp} in / {out} out tokens in {report.seconds:.1f}s")
    return 0 if report.ok else 1


def _brief(arguments) -> str:
    if not isinstance(arguments, dict):
        return ""
    parts = []
    for key, value in list(arguments.items())[:2]:
        rendered = str(value)
        parts.append(f"{key}={rendered[:40]}{'…' if len(rendered) > 40 else ''}")
    return ", ".join(parts)


def cli_main() -> None:
    raise SystemExit(main())
