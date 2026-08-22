"""``python -m hypernix`` — the entry point that always works.

This is the one invocation that cannot be broken by a PATH problem, which
is why the automatic PATH setup runs from here as well as from the console
script: someone typing ``python -m hypernix`` after ``hypernix`` failed is
exactly the person it exists for. ``hypernix.interfaces.cli.main`` itself
stays free of it, so importing and calling the CLI in-process (tests, other
tools) never touches a home directory.
"""
from hypernix.interfaces.cli import main

if __name__ == "__main__":
    try:
        from hypernix.system.pathfix import maybe_autoconfigure
        maybe_autoconfigure()
    except Exception:  # noqa: BLE001 - a PATH convenience must never block the CLI
        pass
    raise SystemExit(main())
