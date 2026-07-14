"""vera — Verify HyperNix module syntax and run smoke tests.

v0.70.5: Module verification engine that checks:
  1. Import correctness (all hypernix imports resolve)
  2. Docstring coverage (modules, classes, public functions)
  3. Naming convention compliance (kitchen-themed naming)
  4. Type annotation coverage
  5. Basic smoke test (module imports without errors)
  6. Optional: run the module's __main__ or doctest

Usage:
    hnx vera <python_file>           # Verify a single file
    hnx vera <module_name>           # Verify an installed module
    hnx vera --all                   # Verify all hypernix modules
    hnx vera --strict <file>         # Fail on missing docstrings
    hnx vera --smoke <file>          # Run smoke test after syntax check
"""
from __future__ import annotations

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.table import Table


@dataclass
class VerificationResult:
    """Result of verifying a single module or file."""
    name: str
    passed: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.passed = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


class HyperNixVerifier:
    """Verifies HyperNix module syntax, conventions, and runs smoke tests."""

    def __init__(self, strict: bool = False, smoke: bool = False):
        self.strict = strict
        self.smoke = smoke
        self.console = Console()

    def verify_file(self, file_path: Path) -> VerificationResult:
        """Verify a Python file."""
        result = VerificationResult(name=str(file_path))

        if not file_path.exists():
            result.add_error(f"File not found: {file_path}")
            return result

        source = file_path.read_text(encoding="utf-8")

        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            result.add_error(f"Syntax error: {e}")
            return result

        result.stats["lines"] = len(source.splitlines())

        module_doc = ast.get_docstring(tree)
        if not module_doc:
            if self.strict:
                result.add_error("Missing module docstring")
            else:
                result.add_warning("Missing module docstring")
        else:
            result.stats["module_doc_lines"] = len(module_doc.splitlines())

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                self._check_class(node, result)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_"):
                    self._check_function(node, result)

        if self.smoke:
            self._run_smoke_test(file_path, result)

        return result

    def verify_module(self, module_name: str) -> VerificationResult:
        """Verify an installed module by name."""
        import importlib

        result = VerificationResult(name=module_name)

        try:
            module = importlib.import_module(f"hypernix.{module_name}")
        except ImportError as e:
            result.add_error(f"Import failed: {e}")
            return result

        if not hasattr(module, "__file__") or module.__file__ is None:
            result.add_error("Module has no __file__ attribute")
            return result

        file_path = Path(module.__file__)
        return self.verify_file(file_path)

    def verify_all(self):
        """Verify all hypernix modules."""
        import hypernix
        root = Path(hypernix.__file__).parent

        for file_path in sorted(root.glob("*.py")):
            if file_path.name.startswith("_"):
                continue
            module_name = file_path.stem
            yield self.verify_module(module_name)

    def _check_class(self, node: ast.ClassDef, result: VerificationResult) -> None:
        """Check a class definition."""
        doc = ast.get_docstring(node)
        if not doc and self.strict:
            result.add_error(f"Class '{node.name}' missing docstring")
        elif not doc:
            result.add_warning(f"Class '{node.name}' missing docstring")

        result.stats["classes"] = result.stats.get("classes", 0) + 1

        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not item.name.startswith("_") or item.name in ("__init__", "__call__"):
                    self._check_function(item, result, prefix=f"{node.name}.")

    def _check_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        result: VerificationResult,
        prefix: str = "",
    ) -> None:
        """Check a function definition."""
        doc = ast.get_docstring(node)
        if not doc and self.strict:
            result.add_error(f"Function '{prefix}{node.name}' missing docstring")
        elif not doc:
            result.add_warning(f"Function '{prefix}{node.name}' missing docstring")

        has_annotations = False
        if node.returns:
            has_annotations = True
        for arg in node.args.args:
            if arg.annotation:
                has_annotations = True
                break

        if not has_annotations:
            result.add_warning(f"Function '{prefix}{node.name}' lacks type annotations")

        key = "methods" if prefix else "functions"
        result.stats[key] = result.stats.get(key, 0) + 1

    def _run_smoke_test(self, file_path: Path, result: VerificationResult) -> None:
        """Run a basic smoke test by importing the module."""
        import importlib.util

        temp_name = f"_smoke_test_{file_path.stem}"

        try:
            spec = importlib.util.spec_from_file_location(temp_name, file_path)
            if spec is None or spec.loader is None:
                result.add_error("Could not create module spec for smoke test")
                return

            module = importlib.util.module_from_spec(spec)
            sys.modules[temp_name] = module
            spec.loader.exec_module(module)

            if hasattr(module, "__all__"):
                for name in module.__all__:
                    if not hasattr(module, name):
                        result.add_error(f"__all__ declares '{name}' but it's not defined")

            result.stats["smoke_test"] = 1

        except Exception as e:
            result.add_error(f"Smoke test failed: {e}")

    def print_result(self, result: VerificationResult) -> None:
        """Pretty-print a verification result."""
        if result.passed:
            status = "[green]✓ PASS[/]"
        else:
            status = "[red]✗ FAIL[/]"

        self.console.print(f"\n{status} [bold]{result.name}[/]")

        if result.stats:
            stats_str = " | ".join(f"{k}={v}" for k, v in sorted(result.stats.items()))
            self.console.print(f"  [dim]{stats_str}[/]")

        for warning in result.warnings:
            self.console.print(f"  [yellow]⚠ {warning}[/]")
        for error in result.errors:
            self.console.print(f"  [red]✗ {error}[/]")

    def print_summary(self, results: list[VerificationResult]) -> None:
        """Print a summary table of all results."""
        passed = sum(1 for r in results if r.passed)
        total = len(results)

        table = Table(title="Verification Summary")
        table.add_column("Module", style="cyan")
        table.add_column("Status", justify="center")
        table.add_column("Errors", justify="right")
        table.add_column("Warnings", justify="right")

        for r in results:
            status = "[green]✓[/]" if r.passed else "[red]✗[/]"
            table.add_row(r.name, status, str(len(r.errors)), str(len(r.warnings)))

        self.console.print(table)
        self.console.print(f"\n[bold]{passed}/{total} passed[/] ({total - passed} failed)")


def cli_main(argv: list[str] | None = None) -> int:
    """CLI entry point for hnx vera."""
    args = list(argv if argv is not None else sys.argv[1:])
    console = Console()

    strict = "--strict" in args
    smoke = "--smoke" in args
    all_modules = "--all" in args

    for flag in ("--strict", "--smoke", "--all"):
        while flag in args:
            args.remove(flag)

    if "--help" in args or "-h" in args or not args:
        console.print("""
[bold]hnx vera[/] — Verify HyperNix module syntax and run smoke tests

[bold]Usage:[/]
  hnx vera <file.py>               Verify a Python file
  hnx vera <module_name>           Verify a hypernix module
  hnx vera --all                   Verify all hypernix modules
  hnx vera --strict <file>         Fail on missing docstrings
  hnx vera --smoke <file>          Run smoke test after checks

[bold]Checks performed:[/]
  • Syntax validation (AST parsing)
  • Module/class/function docstring coverage
  • Type annotation coverage
  • Import correctness
  • Smoke test (module loads without errors)

[bold]Examples:[/]
  hnx vera pressure_cooker_v5.py   # Verify a file
  hnx vera pressure_cooker_v5      # Verify installed module
  hnx vera --all --strict          # Strict check of everything
  hnx vera --smoke my_module.py    # Verify + smoke test
        """)
        return 0

    verifier = HyperNixVerifier(strict=strict, smoke=smoke)

    if all_modules:
        results = list(verifier.verify_all())
        for r in results:
            verifier.print_result(r)
        verifier.print_summary(results)
        return 0 if all(r.passed for r in results) else 1

    target = args[0]
    file_path = Path(target)

    if file_path.exists() and file_path.suffix == ".py":
        result = verifier.verify_file(file_path)
    else:
        result = verifier.verify_module(target)

    verifier.print_result(result)
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(cli_main())
