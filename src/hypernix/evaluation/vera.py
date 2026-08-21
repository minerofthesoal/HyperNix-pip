"""vera — Verify HyperNix module syntax and run smoke tests.

Vera is a tool to input a file path, lint it (via ast & ruff), smoke test it, 
pytest it if possible, run it, and intelligently explain errors using a small LLM.

Usage:
    hnx vera <python_file> [options]

Options:
    -dr, --dry-run   Run the file with dry-run flag
    -C               Fully run the file
    -FT              Test each argument one at a time
    -q <1-10>        Argument testing depth (default 1)
    -t <time>        Timeout
    -T <unit>        Timeout unit (s, M, ml). Default ml (milliseconds)
"""
from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console

console = Console()


@dataclass
class VeraResult:
    passed: bool = True
    output: str = ""
    error_context: str = ""

    def fail(self, msg: str, context: str = ""):
        self.passed = False
        self.output += f"\nError: {msg}"
        self.error_context += f"\n{context}"


@dataclass
class VerificationResult:
    """Result of a :class:`HyperNixVerifier` check on a single file."""

    name: str
    passed: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.passed = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


class HyperNixVerifier:
    """Lightweight, in-process syntax and style verifier.

    This complements the module-level :func:`lint_file` / :func:`smoke_test`
    helpers (which shell out to ``ruff`` and actually import the file) with
    a cheap, dependency-free check: syntax validity via :func:`ast.parse`
    plus a module-docstring convention check. In ``strict`` mode a missing
    module docstring is treated as an error; otherwise it's just a warning.
    """

    def __init__(self, strict: bool = False) -> None:
        self.strict = strict

    def verify_file(self, file_path: Path) -> VerificationResult:
        result = VerificationResult(name=str(file_path))

        try:
            source = file_path.read_text(encoding="utf-8")
        except OSError as e:
            result.add_error(f"Could not read file: {e}")
            return result

        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as e:
            result.add_error(f"SyntaxError: {e}")
            return result

        if ast.get_docstring(tree) is None:
            msg = "Missing module docstring"
            if self.strict:
                result.add_error(msg)
            else:
                result.add_warning(msg)

        return result


def get_ai_explanation(error_text: str, source_code: str) -> str:
    """Use a small qwen3.5 model to explain the error without crashing."""
    try:
        from hypernix.models.neo_oven import preheat
        oven = preheat("qwen3.5-4b", quiet=True)
        
        prompt = (
            f"An error occurred while testing a Python script.\n\n"
            f"Source code snippet:\n```python\n{source_code[:1500]}\n```\n\n"
            f"Error output:\n```\n{error_text[-1500:]}\n```\n\n"
            f"Explain what is wrong and tell me how to fix it, and mention the line numbers."
        )
        # Use chat format for a better response
        reply = oven.chat([{"role": "user", "content": prompt}], max_new_tokens=256)
        return reply
    except Exception as e:
        return f"[AI Explanation Unavailable]: Failed to load AI model: {e}"


def run_command(cmd: list[str], timeout_s: float | None = None) -> tuple[bool, str, str]:
    """Run a subprocess command and return (success, stdout, stderr)."""
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        return res.returncode == 0, res.stdout, res.stderr
    except subprocess.TimeoutExpired as e:
        return False, "", f"Timeout after {timeout_s}s: {e}"
    except Exception as e:
        return False, "", str(e)


def lint_file(file_path: Path) -> VeraResult:
    result = VeraResult()
    
    # 1. AST check
    try:
        source = file_path.read_text(encoding="utf-8")
        ast.parse(source)
    except SyntaxError as e:
        result.fail(f"AST SyntaxError: {e}", context=str(e))
        return result
    except Exception as e:
        result.fail(f"Read Error: {e}", context=str(e))
        return result

    # 2. Ruff check
    success, stdout, stderr = run_command(["ruff", "check", str(file_path)])
    if not success:
        result.fail("Ruff linting failed.", context=stdout + "\n" + stderr)

    return result


def smoke_test(file_path: Path) -> VeraResult:
    result = VeraResult()
    import importlib.util
    
    temp_name = f"_smoke_test_{file_path.stem}"
    try:
        spec = importlib.util.spec_from_file_location(temp_name, file_path)
        if spec is None or spec.loader is None:
            result.fail("Could not create module spec")
            return result
            
        module = importlib.util.module_from_spec(spec)
        sys.modules[temp_name] = module
        spec.loader.exec_module(module)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        result.fail(f"Smoke test failed: {e}", context=tb)
    
    return result


def run_pytest(file_path: Path, timeout_s: float | None) -> VeraResult:
    result = VeraResult()
    success, stdout, stderr = run_command(["pytest", str(file_path)], timeout_s)
    if not success:
        if "no tests ran" in stdout:
            # Not a failure if there are just no tests
            pass
        else:
            result.fail("Pytest failed.", context=stdout + "\n" + stderr)
    return result


def execute_file(file_path: Path, args: list[str], timeout_s: float | None) -> VeraResult:
    result = VeraResult()
    cmd = [sys.executable, str(file_path)] + args
    success, stdout, stderr = run_command(cmd, timeout_s)
    if not success:
        result.fail(f"Execution failed with args {args}", context=stdout + "\n" + stderr)
    return result


def test_arguments(file_path: Path, depth: int, timeout_s: float | None) -> VeraResult:
    """Test script functions or CLI arguments one at a time."""
    result = VeraResult()
    
    # Approach: we try to run the script with --help to find arguments
    success, stdout, stderr = run_command([sys.executable, str(file_path), "--help"], timeout_s)
    if success and "-h" in stdout or "--help" in stdout:
        # Extract simplistic arguments (lines starting with  - or --)
        args_to_test = []
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith("-") and not line.startswith("--help"):
                arg = line.split()[0].replace(",", "")
                args_to_test.append(arg)
        
        # Test them based on depth
        for i, arg in enumerate(args_to_test):
            if i >= depth:
                break
            cmd = [sys.executable, str(file_path), arg]
            succ, out, err = run_command(cmd, timeout_s)
            if not succ:
                result.fail(f"Argument test failed for {arg}", context=out + "\n" + err)
                break
    else:
        # No --help, try AST function execution testing
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            functions = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
            if functions:
                result.fail(f"Script has no standard CLI help, found functions: {functions[:depth]}. "
                            "Advanced FT argument probing failed.", context="No CLI arg parser detected.")
        except Exception as e:
            result.fail("Failed to parse script for FT.", context=str(e))
            
    return result


def cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hnx vera",
        description="Verify HyperNix module syntax, run smoke tests, and intelligently explain errors."
    )
    parser.add_argument("file", help="Python file to test")
    parser.add_argument("-dr", "--dry-run", action="store_true", help="Run the file with dry-run flag")
    parser.add_argument("-C", "--full-run", action="store_true", help="Fully run the file")
    parser.add_argument("-FT", "--function-test", action="store_true", help="Test each argument one at a time")
    parser.add_argument("-q", "--depth", type=int, default=1, help="Argument testing depth (1-10)")
    parser.add_argument("-t", "--timeout", type=float, default=None, help="Timeout value")
    parser.add_argument("-T", "--timeout-unit", choices=["s", "M", "ml"], default="ml", help="Timeout unit (s, M, ml)")
    
    # Allow unknown args to pass? No, just parse known.
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    file_path = Path(args.file)
    
    if not file_path.exists():
        console.print(f"[red]Error:[/] File not found: {file_path}")
        return 1

    timeout_s = None
    if args.timeout is not None:
        if args.timeout_unit == "ml":
            timeout_s = args.timeout / 1000.0
        elif args.timeout_unit == "s":
            timeout_s = args.timeout
        elif args.timeout_unit == "M":
            timeout_s = args.timeout * 60.0

    console.print(f"[bold cyan]Vera:[/] Analyzing {file_path} ...\n")
    
    stages = [
        ("Linting (AST + Ruff)", lambda: lint_file(file_path)),
        ("Smoke Testing", lambda: smoke_test(file_path)),
        ("Pytest", lambda: run_pytest(file_path, timeout_s)),
    ]
    
    if args.dry_run:
        stages.append(("Dry Run", lambda: execute_file(file_path, ["--dry-run"], timeout_s)))
        # Fallback to -dr if --dry-run isn't recognized could be added, but this suffices for the request.
    elif args.full_run:
        stages.append(("Full Run", lambda: execute_file(file_path, [], timeout_s)))
        
    if args.function_test:
        stages.append(("Argument Testing (-FT)", lambda: test_arguments(file_path, args.depth, timeout_s)))

    source_code = file_path.read_text(encoding="utf-8", errors="ignore")
    
    for stage_name, stage_fn in stages:
        console.print(f"Running [bold]{stage_name}[/] ...")
        res = stage_fn()
        if not res.passed:
            console.print(f"[red]✗ {stage_name} Failed![/]")
            if res.output:
                console.print(f"[dim]{res.output}[/]")
            
            console.print("\n[bold yellow]Vera AI Analysis:[/] (Using qwen3.5-4b)")
            with console.status("Generating explanation..."):
                explanation = get_ai_explanation(res.error_context, source_code)
            console.print(f"[green]{explanation}[/]")
            return 1
        else:
            console.print(f"[green]✓ {stage_name} Passed[/]\n")

    console.print("[bold green]All checks passed successfully![/]")
    return 0


if __name__ == "__main__":
    sys.exit(cli_main())
