"""noodle.validate — verifiers for the self-correction loop.

A verifier answers one question: is the work in this workspace actually
correct? It returns ``(ok, feedback)`` and the feedback goes straight
back to the model, so it has to be readable by one — "SyntaxError: line
42" is actionable and "verification failed" is not.

Three are provided. :func:`syntax_verifier` is the cheap one and should
almost always be on; :func:`command_verifier` runs the project's own
tests; :func:`combine` runs several in order and stops at the first
failure, because reporting three failures when the first caused the
other two just makes the model fix the wrong one.
"""
from __future__ import annotations

import ast
import json
import logging
import subprocess
import time
from collections.abc import Sequence
from typing import Any

from .tools import ToolContext

logger = logging.getLogger(__name__)

__all__ = ["syntax_verifier", "command_verifier", "combine", "check_python_syntax"]


def check_python_syntax(source: str, filename: str = "<agent>") -> tuple[bool, str]:
    """Parse *source*, returning a message a model can act on."""
    try:
        ast.parse(source, filename=filename)
    except SyntaxError as exc:
        line = f" line {exc.lineno}" if exc.lineno else ""
        caret = f"\n    {exc.text.rstrip()}" if exc.text else ""
        return False, f"{filename}{line}: {exc.msg}{caret}"
    return True, ""


def syntax_verifier(patterns: Sequence[str] = ("*.py",)):
    """Check that every matching file in the workspace parses.

    Cheap, immediate, and catches the single most common way an agent's
    output is wrong: an edit that produced a file which no longer
    parses. Non-Python patterns are checked for balance rather than
    parsed, which catches truncation — a JSON file cut off mid-write is
    a real and frequent outcome of a token limit.
    """

    def verify(ctx: ToolContext) -> tuple[bool, str]:
        problems: list[str] = []
        for pattern in patterns:
            for path in sorted(ctx.root.rglob(pattern)):
                if not path.is_file():
                    continue
                try:
                    source = path.read_text(encoding="utf-8", errors="replace")
                except OSError as exc:
                    problems.append(f"{path.name}: could not read it ({exc})")
                    continue
                relative = path.relative_to(ctx.root)
                if path.suffix == ".py":
                    ok, message = check_python_syntax(source, str(relative))
                    if not ok:
                        problems.append(message)
                elif path.suffix == ".json":
                    try:
                        json.loads(source)
                    except json.JSONDecodeError as exc:
                        problems.append(f"{relative}: invalid JSON at line {exc.lineno}: {exc.msg}")
        if problems:
            return False, "These files do not parse:\n" + "\n".join(f"  - {p}" for p in problems)
        return True, ""

    return verify


def command_verifier(
    argv: Sequence[str],
    *,
    timeout: float = 300.0,
    expect_returncode: int = 0,
):
    """Run a command in the workspace and treat its exit code as the verdict.

    argv rather than a shell string, for the same reason ``execute_file``
    does it: this is a place where a string would eventually be built
    from something a model produced.
    """

    def verify(ctx: ToolContext) -> tuple[bool, str]:
        started = time.monotonic()
        try:
            proc = subprocess.run(  # noqa: S603 - argv list, no shell
                list(argv), cwd=str(ctx.root), capture_output=True,
                text=True, timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            return False, f"`{' '.join(argv)}` did not finish within {timeout:.0f}s."
        except OSError as exc:
            # A missing binary is the caller's configuration problem, not
            # the agent's work being wrong. Saying so keeps the model
            # from spending its correction budget on someone else's bug.
            return False, (
                f"Could not run `{argv[0]}` ({exc}). This is a verifier configuration "
                "problem rather than a fault in the work."
            )
        if proc.returncode == expect_returncode:
            return True, ""
        output = (proc.stdout + "\n" + proc.stderr).strip()
        return False, (
            f"`{' '.join(argv)}` exited {proc.returncode} after "
            f"{time.monotonic() - started:.1f}s:\n{output[-4000:]}"
        )

    return verify


def combine(*verifiers: Any):
    """Run verifiers in order, stopping at the first failure.

    Stopping matters: a syntax error will also fail the test suite, and
    reporting both makes the model choose which to fix. Ordered
    cheapest-first by convention so a broken file is caught in
    milliseconds rather than after a full test run.
    """

    def verify(ctx: ToolContext) -> tuple[bool, str]:
        for verifier in verifiers:
            ok, feedback = verifier(ctx)
            if not ok:
                return False, feedback
        return True, ""

    return verify
