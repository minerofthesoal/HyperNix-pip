"""waiter.cli — argparse-based CLI for the ``waiter`` console script.

Complete as of Beta 3: every flag in the spec's ``serv`` list is wired to
real behaviour. The ones Beta 1/2 could only record locally
(``-B``/``-W``/``-a``/``-r`` and the full ``-G``/``-Rf``/``-y``) now call
the server endpoints that Beta 3 added — see ``t1api/routers/security.py``
for the blacklist/whitelist/appeal/forced-limit surface and
``waiter/tui.py`` for the curses dashboard.

``-B``/``-W``/``-a``/``-r`` keep writing to the local config *as well as*
the server. That is deliberate rather than redundant: the local copy is
what ``waiter config`` shows and what a re-run of ``waiter serv -A``
re-applies against a rebuilt server, and it is the only record available
when the operator's key isn't admin (in which case the server call is
refused and the CLI says so plainly instead of pretending it worked).

Style matches ``hypernix.gkey_cli``: manual dispatch dict, rich-formatted
output with a plain-text fallback when ``rich`` isn't installed (it's a
core hypernix dependency, so the fallback is mostly defensive).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from .client import T1Client, T1ClientError
from .local_config import WaiterConfigStore, WaiterLocalConfig

# ---------------------------------------------------------------------------
# Rich helpers (graceful degradation — mirrors hypernix.gkey_cli)
# ---------------------------------------------------------------------------


def _try_rich() -> bool:
    try:
        import rich  # noqa: F401

        return True
    except ImportError:
        return False


_HAS_RICH = _try_rich()


def _ok(text: str) -> None:
    if _HAS_RICH:
        from rich.console import Console

        Console().print(f"[green]\u2713[/green] {text}")
    else:
        print(f"OK: {text}")


def _warn(text: str) -> None:
    if _HAS_RICH:
        from rich.console import Console

        Console(stderr=True).print(f"[yellow]![/yellow] {text}")
    else:
        print(f"WARNING: {text}", file=sys.stderr)


def _err(text: str) -> None:
    if _HAS_RICH:
        from rich.console import Console

        Console(stderr=True).print(f"[red]\u2717[/red] {text}", style="red")
    else:
        print(f"ERROR: {text}", file=sys.stderr)


def _info(text: str) -> None:
    if _HAS_RICH:
        from rich.console import Console

        Console().print(text)
    else:
        print(text)


def _print_table(headers: list[str], rows: list[list[str]], title: str = "") -> None:
    if _HAS_RICH:
        from rich.console import Console
        from rich.table import Table

        t = Table(title=title, header_style="bold cyan", border_style="dim")
        for h in headers:
            t.add_column(h, overflow="fold")
        for row in rows:
            t.add_row(*row)
        Console().print(t)
    else:
        if title:
            print(f"\n{title}")
        print("  ".join(headers))
        for row in rows:
            print("  ".join(row))


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _mask(secret: str | None, keep: int = 8) -> str:
    if not secret:
        return "-"
    return secret[:keep] + "…" if len(secret) > keep else secret


# ---------------------------------------------------------------------------
# Config / client resolution shared by every subcommand
# ---------------------------------------------------------------------------


def _add_common_connection_args(parser: argparse.ArgumentParser) -> None:
    """-I/-K/-F/-P/-H are meaningful outside of `serv` too (e.g. `waiter
    models -I ... -K ...` without ever running `serv`), so every subcommand
    accepts them as overrides on top of the saved local config."""
    parser.add_argument("-I", "--server", dest="server", default=None, help="Server IP/Tailscale IP/URL")
    parser.add_argument("-K", "--key", dest="key", default=None, help="T1 token")
    parser.add_argument("-F", "--config-file", dest="config_file", default=None, help="Local config file path")
    parser.add_argument("-P", "--port", dest="port", type=int, default=None, help="Server port")
    parser.add_argument("-H", "--home", dest="home_url", default=None, help="Home page URL override")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Print raw JSON instead of a table")


def _load_store(args: argparse.Namespace, *, encrypt: bool | None = None) -> WaiterConfigStore:
    enc = encrypt if encrypt is not None else bool(getattr(args, "encrypt", False))
    return WaiterConfigStore(args.config_file, encrypt=enc)


def _resolve_config(args: argparse.Namespace) -> WaiterLocalConfig:
    store = _load_store(args)
    saved = store.load() or WaiterLocalConfig()
    if args.server:
        saved.server = args.server
    if args.key:
        saved.key = args.key
    if getattr(args, "port", None) is not None:
        saved.port = args.port
    if getattr(args, "home_url", None):
        saved.home_url = args.home_url
    return saved


def _base_url(cfg: WaiterLocalConfig) -> str:
    if not cfg.server:
        raise T1ClientError(
            "No server configured. Run 'waiter serv -A -I <server> -K <key>' first, "
            "or pass -I explicitly."
        )
    server = cfg.server
    if not server.startswith(("http://", "https://")):
        scheme = "http" if cfg.local_only else "https"
        server = f"{scheme}://{server}"
    if cfg.port and f":{cfg.port}" not in server:
        server = f"{server}:{cfg.port}"
    return server


def _client_for(args: argparse.Namespace) -> tuple[T1Client, WaiterLocalConfig]:
    cfg = _resolve_config(args)
    return T1Client(base_url=_base_url(cfg), credential=cfg.key), cfg


# ---------------------------------------------------------------------------
# `waiter serv` — single-command automatic setup
# ---------------------------------------------------------------------------

_SERV_HELP = """\
waiter serv — configure and (re)validate this machine's connection to a T1
API server. One-shot automatic setup:

    waiter serv -A -I <server> -K <T1_TOKEN> -E

Every flag is wired as of Beta 3. -B/-W/-a/-r apply to the server (admin
key required) and are also saved locally; -G opens the full TUI; -Rf does
a complete refresh across models, servers, modules and events; -y
synchronizes local config against the server's /config and /models.
"""


def _build_serv_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="waiter serv", description=_SERV_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    _add_common_connection_args(p)
    p.add_argument("-A", "--auto", action="store_true", help="Automatic configuration: validate + save in one step")
    p.add_argument("-E", "--encrypt", action="store_true", help="Encrypt the local config/secrets at rest")
    p.add_argument("-s", "--save", action="store_true", help="Save current server/local configuration to a .jsonl file")
    p.add_argument("-L", "--local-only", action="store_true", help="Local/Tailscale/localhost-only mode")
    p.add_argument("-B", "--blacklist", action="append", default=[], metavar="IP_OR_CIDR", help="Blacklist an IP or CIDR range on the server (repeatable; admin key required)")
    p.add_argument("-W", "--whitelist", action="append", default=[], metavar="IP_OR_CIDR", help="Allowlist an IP or CIDR range on the server (repeatable; admin key required)")
    p.add_argument("-r", "--force-limit", action="append", default=[], metavar="SUBJECT=LIMIT", help="Force a limit on a T1 key/server, e.g. key:abc123=60/60s (admin key required)")
    p.add_argument("-a", "--appeal", action="append", default=[], metavar="IP_OR_CIDR", help="Appeal: remove an IP/CIDR from the server allow/block lists (admin key required)")
    p.add_argument("-C", "--config", dest="extra_config", action="append", default=[], metavar="KEY=VALUE", help="Additional configuration settings")
    p.add_argument("-G", "--gui", action="store_true", help="Open the full curses TUI dashboard")
    p.add_argument("-g", "--cli", action="store_true", help="Open an interactive CLI session")
    p.add_argument("-R", "--refresh", action="store_true", help="Quick refresh: re-validate + re-fetch models")
    p.add_argument("-Rf", "--force-refresh", dest="force_refresh", action="store_true", help="Force a full refresh: models, servers, modules, events, and config")
    p.add_argument("-y", "--sync", action="store_true", help="Synchronize local config against the server's current /config + /models")
    p.add_argument("--promote-admin", dest="promote_admin", action="store_true", help="After validating, request admin promotion for this key (requires the authenticating key to already be admin-scoped — see POST /auth/t1/admin/rotate)")
    return p


def _parse_kv_list(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            _warn(f"Ignoring malformed -C value (expected KEY=VALUE): {item!r}")
            continue
        k, _, v = item.partition("=")
        out[k.strip()] = v.strip()
    return out


def _parse_forced_limit(spec: str) -> dict[str, object] | None:
    """Parse a ``-r`` value into a forced-limit request.

    Accepted forms (the subject prefix is optional and defaults to
    ``key``, since capping a key is the common case)::

        key:abc123=60/60s      60 requests per 60 seconds
        server:srv-1=120/1m    120 requests per minute
        abc123=1000t/1h        1000 tokens per hour

    Returns None (with a warning) rather than raising on a malformed
    value: one bad ``-r`` in a long command line should not discard the
    rest of the setup.
    """
    if "=" not in spec:
        _warn(f"Ignoring malformed -r value (expected SUBJECT=LIMIT/WINDOW): {spec!r}")
        return None
    subject, _, limit_spec = spec.partition("=")
    subject_type, _, subject_id = subject.partition(":")
    if not subject_id:
        subject_type, subject_id = "key", subject_type
    if subject_type not in ("key", "server"):
        _warn(f"Ignoring -r value with unknown subject type {subject_type!r} (use key: or server:)")
        return None
    if "/" not in limit_spec:
        _warn(f"Ignoring malformed -r limit {limit_spec!r} (expected COUNT/WINDOW, e.g. 60/60s)")
        return None
    count_text, _, window_text = limit_spec.partition("/")
    is_tokens = count_text.strip().lower().endswith("t")
    try:
        count = int(count_text.strip().rstrip("tT"))
        window = _parse_duration(window_text.strip())
    except ValueError:
        _warn(f"Ignoring -r value with unparseable numbers: {spec!r}")
        return None
    return {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "tokens_per_window" if is_tokens else "requests_per_window": count,
        "window_seconds": window,
        "reason": "set via waiter serv -r",
    }


def _parse_duration(text: str) -> float:
    """``30s`` / ``5m`` / ``2h`` / ``1d`` / a bare number of seconds."""
    text = text.strip().lower()
    multipliers = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}
    if text and text[-1] in multipliers:
        return float(text[:-1]) * multipliers[text[-1]]
    return float(text)


def _apply_network_policy(client: T1Client, args: argparse.Namespace) -> None:
    """Push -B/-W/-a/-r to the server.

    Each entry is applied independently so one refusal doesn't abort the
    rest, and an admin-scope refusal is reported once with what it means
    rather than repeated per entry.
    """
    denied_reported = False

    def report(exc: T1ClientError, what: str) -> None:
        nonlocal denied_reported
        if exc.code in ("AUTH_ADMIN_REQUIRED", "AUTH_INSUFFICIENT_SCOPE"):
            if not denied_reported:
                _err(
                    "Server refused the network/limit changes: they need an admin-scoped T1 key. "
                    "They have still been saved to your local config."
                )
                denied_reported = True
        else:
            _err(f"{what}: {exc}")

    for cidr in args.blacklist:
        try:
            client.blacklist_ip(cidr, reason="set via waiter serv -B")
            _ok(f"Blacklisted {cidr} on the server")
        except T1ClientError as exc:
            report(exc, f"Could not blacklist {cidr}")

    for cidr in args.whitelist:
        try:
            client.whitelist_ip(cidr, reason="set via waiter serv -W")
            _ok(f"Allowlisted {cidr} on the server")
        except T1ClientError as exc:
            report(exc, f"Could not allowlist {cidr}")

    for cidr in args.appeal:
        try:
            client.appeal_ip(cidr)
            _ok(f"Appealed {cidr} — entry removed on the server")
        except T1ClientError as exc:
            if exc.code == "NOT_FOUND":
                _info(f"  {cidr} had no server-side entry (removed locally only).")
            else:
                report(exc, f"Could not appeal {cidr}")

    for spec in args.force_limit:
        parsed = _parse_forced_limit(spec)
        if parsed is None:
            continue
        try:
            client.set_forced_limit(**parsed)
            _ok(
                f"Forced limit on {parsed['subject_type']}:{str(parsed['subject_id'])[:12]} "
                f"applied on the server"
            )
        except T1ClientError as exc:
            report(exc, f"Could not force a limit for {spec}")


def _cmd_serv(rest: list[str]) -> int:
    args = _build_serv_parser().parse_args(rest)

    if not (args.auto or args.save or args.refresh or args.force_refresh or args.sync or args.cli or args.gui):
        _warn("No action flag given (-A/-s/-R/-Rf/-y/-g/-G). Nothing to do — see 'waiter serv --help'.")
        return 1

    cfg = _resolve_config(args)
    cfg.local_only = cfg.local_only or args.local_only
    if args.blacklist:
        cfg.blacklist = sorted(set(cfg.blacklist) | set(args.blacklist))
    if args.appeal:
        before = set(cfg.blacklist)
        cfg.blacklist = sorted(before - set(args.appeal))
        cfg.whitelist = sorted(set(cfg.whitelist) - set(args.appeal))
        removed = before - set(cfg.blacklist)
        if removed:
            _info(f"Appealed (removed from local blacklist): {', '.join(sorted(removed))}")
    if args.whitelist:
        cfg.whitelist = sorted(set(cfg.whitelist) | set(args.whitelist))
    if args.extra_config:
        cfg.extra_config.update(_parse_kv_list(args.extra_config))
    if args.force_limit:
        cfg.forced_limits = sorted(set(cfg.forced_limits) | set(args.force_limit))

    store = _load_store(args, encrypt=args.encrypt)
    policy_flags = bool(args.blacklist or args.whitelist or args.appeal or args.force_limit)

    if args.auto:
        if not cfg.server or not cfg.key:
            _err("-A requires both -I <server> and -K <T1_TOKEN>.")
            return 1
        client = T1Client(base_url=_base_url(cfg), credential=cfg.key)
        try:
            validated = client.validate()
        except T1ClientError as exc:
            _err(f"Automatic setup failed: {exc}")
            return 1
        _ok(f"Connected to {cfg.server} — key {_mask(validated.get('key_id'))} ({validated.get('key_type')})")
        if validated.get("scopes"):
            _info(f"  scopes: {', '.join(validated['scopes'])}")

        if args.promote_admin:
            if not validated.get("is_admin"):
                _warn("--promote-admin requested, but the authenticating key is not admin-scoped — skipped.")
            else:
                try:
                    promoted = client.admin_rotate(validated["key_id"], promote_to_admin=True)
                    cfg.key = promoted["key"]
                    client.credential = promoted["key"]
                    _ok(f"Promoted to admin key {_mask(promoted['key_id'])}")
                except T1ClientError as exc:
                    _err(f"Admin promotion failed: {exc}")

        if policy_flags:
            _apply_network_policy(client, args)

        # Show the operator what the server thinks of its own setup —
        # the single most useful thing to surface right after connecting.
        try:
            status = client.status()
            if not status.get("production_ready", True) and status.get("environment") == "production":
                _warn(
                    f"Server reports {len(status.get('production_warnings', []))} production "
                    "configuration warning(s) — run 'waiter doctor' to see them."
                )
        except T1ClientError:
            pass

        path = store.save(cfg)
        _ok(f"Saved config to {path}" + (" (encrypted)" if args.encrypt else ""))
        if args.gui:
            return _launch_tui(cfg)
        return 0

    if args.save:
        path = store.save(cfg)
        _ok(f"Saved config to {path}" + (" (encrypted)" if args.encrypt else ""))

    if policy_flags and not args.auto:
        if not cfg.server or not cfg.key:
            _warn("-B/-W/-a/-r were saved locally, but there's no configured server+key to apply them to.")
        else:
            _apply_network_policy(T1Client(base_url=_base_url(cfg), credential=cfg.key), args)
            store.save(cfg)

    if args.refresh or args.force_refresh:
        try:
            client = T1Client(base_url=_base_url(cfg), credential=cfg.key)
            validated = client.validate()
            models = client.list_models()
        except T1ClientError as exc:
            _err(f"Refresh failed: {exc}")
            return 1
        _ok(f"Refreshed — key {_mask(validated.get('key_id'))} still valid, {models.get('count', 0)} model(s) visible.")
        if args.force_refresh:
            # -Rf: everything, not just identity + models.
            for label, fetch in (
                ("servers", lambda: client.list_servers().get("count", 0)),
                ("modules", lambda: client.list_modules().get("count", 0)),
                ("events", lambda: client.list_events(limit=50).get("count", 0)),
            ):
                try:
                    _info(f"  {label}: {fetch()}")
                except T1ClientError as exc:
                    _warn(f"  {label}: unavailable ({exc.code or exc})")
            try:
                remote_config = client.config()["config"]
                _info(f"  server config: {len(remote_config)} setting(s) visible")
            except T1ClientError as exc:
                _warn(f"  server config: unavailable ({exc.code or exc})")

    if args.sync:
        try:
            client = T1Client(base_url=_base_url(cfg), credential=cfg.key)
            remote_config = client.config()["config"]
            models = client.list_models()
        except T1ClientError as exc:
            _err(f"Sync failed: {exc}")
            return 1
        # Mirror the server's own view of the settings a client cares
        # about, so `waiter config` reflects the server rather than
        # whatever was typed weeks ago.
        cfg.extra_config.update(
            {
                "server_environment": str(remote_config.get("environment", "")),
                "server_default_plan": str(remote_config.get("default_plan", "")),
                "server_storage_backend": str(remote_config.get("storage_backend", "")),
                "server_model_count": str(models.get("count", 0)),
            }
        )
        _ok(f"Synchronized against {cfg.server} — {models.get('count', 0)} model(s), "
            f"plan '{remote_config.get('default_plan', '?')}'.")
        if args.as_json:
            _print_json(remote_config)
        store.save(cfg)

    if args.gui:
        return _launch_tui(cfg)

    if args.cli:
        return _interactive_session(cfg, store)

    return 0


def _launch_tui(cfg: WaiterLocalConfig) -> int:
    """Open the curses dashboard (``-G`` / ``waiter tui``)."""
    if not cfg.server:
        _err("No server configured — run 'waiter serv -A -I <server> -K <key>' first.")
        return 1
    from .tui import run as run_tui

    return run_tui(T1Client(base_url=_base_url(cfg), credential=cfg.key))


def _interactive_session(cfg: WaiterLocalConfig, store: WaiterConfigStore) -> int:
    """-g: a minimal interactive REPL over the same subcommands available
    one-shot from the top level. Not the full curses TUI (-G, Beta 3) —
    just enough to poke at a server without re-typing -I/-K every time."""
    if not cfg.server:
        _err("No server configured — run 'waiter serv -A -I <server> -K <key>' first.")
        return 1
    client = T1Client(base_url=_base_url(cfg), credential=cfg.key)
    _info("waiter interactive session — commands: models, status, usage, whoami, quit")
    while True:
        try:
            line = input("waiter> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in ("quit", "exit", "q"):
            return 0
        try:
            if line == "models":
                _render_model_list(client.list_models())
            elif line == "status":
                _print_json(client.status())
            elif line == "usage":
                _print_json(client.usage_current())
            elif line == "whoami":
                _print_json(client.validate())
            elif line == "help":
                _info("commands: models, status, usage, whoami, quit")
            else:
                _warn(f"Unknown command: {line!r} (try: models, status, usage, whoami, quit)")
        except T1ClientError as exc:
            _err(str(exc))


def _render_model_list(payload: dict[str, Any], *, as_json: bool = False) -> None:
    if as_json:
        _print_json(payload)
        return
    models = payload.get("models", [])
    rows = [
        [
            m["model_id"],
            m["display_name"],
            m["status"],
            m["minimum_plan"],
            "yes" if m["free_tier_available"] else "no",
            str(m["routing_priority"]),
        ]
        for m in models
    ]
    _print_table(
        ["model_id", "display_name", "status", "min_plan", "free_tier", "priority"],
        rows,
        title=f"Models ({payload.get('count', len(models))})",
    )
    if not models:
        _info(
            "No models visible. If you expect the shipped example registry, the server "
            "needs T1_ENABLE_EXAMPLE_MODELS=1 — see wiki/T1-API.md#model-registry."
        )


# ---------------------------------------------------------------------------
# Other subcommands
# ---------------------------------------------------------------------------


def _cmd_models(rest: list[str]) -> int:
    p = argparse.ArgumentParser(prog="waiter models", description="List models visible in the server's registry.")
    _add_common_connection_args(p)
    args = p.parse_args(rest)
    try:
        client, _ = _client_for(args)
        payload = client.list_models()
    except T1ClientError as exc:
        _err(str(exc))
        return 1
    _render_model_list(payload, as_json=args.as_json)
    return 0


def _cmd_model(rest: list[str]) -> int:
    p = argparse.ArgumentParser(prog="waiter model", description="Show detail, availability, and usage for one model.")
    p.add_argument("model_id")
    _add_common_connection_args(p)
    args = p.parse_args(rest)
    try:
        client, cfg = _client_for(args)
        detail = client.get_model(args.model_id)
        availability = client.model_availability(args.model_id)
        usage = None
        if cfg.key:
            try:
                usage = client.model_usage(args.model_id)
            except T1ClientError:
                usage = None  # unauthenticated or key lacks access — detail/availability still shown
    except T1ClientError as exc:
        _err(str(exc))
        return 1

    if args.as_json:
        _print_json({"model": detail.get("model"), "availability": availability, "usage": usage})
        return 0

    m = detail["model"]
    _info(f"[bold]{m['display_name']}[/bold] ({m['model_id']})" if _HAS_RICH else f"{m['display_name']} ({m['model_id']})")
    rows = [
        ["status", m["status"]],
        ["architecture", m["architecture"]],
        ["total_parameters (B)", str(m["total_parameters"])],
        ["active_parameters (B)", str(m["active_parameters"])],
        ["context_limit", str(m["context_limit"])],
        ["input_token_limit", str(m["input_token_limit"])],
        ["output_token_limit", str(m["output_token_limit"])],
        ["minimum_plan", m["minimum_plan"]],
        ["free_tier_available", str(m["free_tier_available"])],
        ["fallback_model", str(m["fallback_model"])],
        ["available now", str(availability["available"])],
    ]
    _print_table(["field", "value"], rows, title=m["display_name"])
    if usage:
        _print_table(
            ["input_remaining", "output_remaining", "exhausted"],
            [[str(usage["input_remaining"]), str(usage["output_remaining"]), str(usage["is_exhausted"])]],
            title="Your usage",
        )
    elif cfg.key:
        _info("(usage unavailable for this key/model)")
    return 0


def _cmd_status(rest: list[str]) -> int:
    p = argparse.ArgumentParser(prog="waiter status", description="Show T1 API server status.")
    _add_common_connection_args(p)
    args = p.parse_args(rest)
    try:
        client, _ = _client_for(args)
        payload = client.status()
    except T1ClientError as exc:
        _err(str(exc))
        return 1
    if args.as_json:
        _print_json(payload)
    else:
        rows = [[k, str(v)] for k, v in payload.items() if k != "request_id"]
        _print_table(["field", "value"], rows, title="T1 API status")
    return 0


def _cmd_health(rest: list[str]) -> int:
    p = argparse.ArgumentParser(prog="waiter health", description="Check T1 API server liveness.")
    _add_common_connection_args(p)
    args = p.parse_args(rest)
    try:
        client, cfg = _client_for(args)
        payload = client.health()
    except T1ClientError as exc:
        _err(str(exc))
        return 1
    if args.as_json:
        _print_json(payload)
    else:
        _ok(f"{cfg.server} is healthy ({payload.get('status')})")
    return 0


def _cmd_whoami(rest: list[str]) -> int:
    p = argparse.ArgumentParser(prog="waiter whoami", description="Validate the configured key and show its scopes.")
    _add_common_connection_args(p)
    args = p.parse_args(rest)
    cfg = _resolve_config(args)
    if not cfg.key:
        _err("No key configured. Pass -K or run 'waiter serv -A' first.")
        return 1
    try:
        client = T1Client(base_url=_base_url(cfg), credential=cfg.key)
        payload = client.validate()
    except T1ClientError as exc:
        _err(str(exc))
        return 1
    if args.as_json:
        _print_json(payload)
    else:
        rows = [[k, str(v)] for k, v in payload.items() if k != "request_id"]
        _print_table(["field", "value"], rows, title="Identity")
    return 0


def _cmd_usage(rest: list[str]) -> int:
    p = argparse.ArgumentParser(prog="waiter usage", description="Show current usage, or remaining allowance for one model with --model.")
    p.add_argument("--model", dest="model_id", default=None, help="Show remaining allowance for this model_id instead of the full summary")
    _add_common_connection_args(p)
    args = p.parse_args(rest)
    try:
        client, _ = _client_for(args)
        if args.model_id:
            payload = client.usage_remaining(args.model_id)
        else:
            payload = client.usage_current()
    except T1ClientError as exc:
        _err(str(exc))
        return 1
    if args.as_json:
        _print_json(payload)
        return 0
    if args.model_id:
        rows = [[k, str(v)] for k, v in payload.items() if k != "request_id"]
        _print_table(["field", "value"], rows, title=f"Remaining — {args.model_id}")
    else:
        _print_table(
            ["window requests", "window tokens", "all-time requests", "all-time tokens"],
            [[
                str(payload["current_window"]["requests"]),
                str(payload["current_window"]["total_tokens"]),
                str(payload["all_time"]["requests"]),
                str(payload["all_time"]["total_tokens"]),
            ]],
            title="Usage summary",
        )
        by_model = payload.get("by_model", [])
        if by_model:
            _print_table(
                ["model_id", "requests", "input_tokens", "output_tokens"],
                [[r["model_id"], str(r["requests"]), str(r["input_tokens"]), str(r["output_tokens"])] for r in by_model],
                title="By model (current window)",
            )
    return 0


def _cmd_config(rest: list[str]) -> int:
    p = argparse.ArgumentParser(prog="waiter config", description="Show the locally saved waiter config (key is masked).")
    _add_common_connection_args(p)
    args = p.parse_args(rest)
    cfg = _resolve_config(args)
    d = cfg.to_dict()
    d["key"] = _mask(d.get("key"))
    if args.as_json:
        _print_json(d)
    else:
        _print_table(["field", "value"], [[k, str(v)] for k, v in d.items()], title="Local waiter config")
    return 0


# ---------------------------------------------------------------------------
# Beta 2 subcommands — servers, modules, jobs, events, billing, route
# ---------------------------------------------------------------------------


def _cmd_route(rest: list[str]) -> int:
    p = argparse.ArgumentParser(prog="waiter route", description="Ask the T1 API's routing engine which model to use.")
    p.add_argument("--plan", required=True, help="Your plan (e.g. free, paired)")
    p.add_argument("--model", dest="model_id", default=None, help="Manual selection instead of automatic routing")
    p.add_argument("--input-tokens", type=int, default=0)
    p.add_argument("--auto-fallback", action="store_true", help="Fall through the cascade if --model is exhausted")
    _add_common_connection_args(p)
    args = p.parse_args(rest)
    client, _ = _client_for(args)
    payload = client.route(
        plan=args.plan, model_id=args.model_id, input_tokens=args.input_tokens, automatic_fallback=args.auto_fallback
    )
    if args.as_json:
        _print_json(payload)
        return 0
    _ok(f"Routed to {payload['model_id']} ({payload['reason']})")
    return 0


def _cmd_servers(rest: list[str]) -> int:
    p = argparse.ArgumentParser(prog="waiter servers", description="List / register servers.")
    p.add_argument("--register", metavar="NAME", default=None, help="Register a new server with this name")
    p.add_argument("--address", default=None, help="Required with --register")
    p.add_argument("--allow-private", action="store_true", help="Allow a private/Tailscale/localhost address")
    _add_common_connection_args(p)
    args = p.parse_args(rest)
    client, _ = _client_for(args)
    if args.register:
        if not args.address:
            _err("--register requires --address")
            return 1
        payload = client.register_server(name=args.register, address=args.address, allow_private_address=args.allow_private)
        if args.as_json:
            _print_json(payload)
        else:
            s = payload["server"]
            _ok(f"Registered {s['name']} ({s['server_id'][:8]}…) — trust_level={s['trust_level']}")
        return 0
    payload = client.list_servers()
    if args.as_json:
        _print_json(payload)
        return 0
    rows = [[s["server_id"][:8] + "…", s["name"], s["address"], s["trust_level"], s["status"]] for s in payload["servers"]]
    _print_table(["server_id", "name", "address", "trust", "status"], rows, title=f"Servers ({payload['count']})")
    return 0


def _cmd_modules(rest: list[str]) -> int:
    p = argparse.ArgumentParser(prog="waiter modules", description="List modules, or create/upload/sync one.")
    p.add_argument("--create", metavar="NAME", default=None, help="Create a new module with this name")
    p.add_argument("--version", default="1.0.0", help="Version for --create (default 1.0.0)")
    p.add_argument("--upload", metavar="MODULE_ID", default=None, help="Upload a local file to this module_id")
    p.add_argument("--file", default=None, help="Local file path for --upload")
    p.add_argument("--sync", metavar="MODULE_ID", default=None, help="Sync this module_id to --server-id")
    p.add_argument("--server-id", default=None, help="Target server_id for --sync")
    _add_common_connection_args(p)
    args = p.parse_args(rest)
    client, _ = _client_for(args)

    if args.create:
        payload = client.create_module(name=args.create, version=args.version)
        m = payload["module"]
        _ok(f"Created {m['name']}@{m['version']} ({m['module_id'][:8]}…) status={m['status']}")
        return 0
    if args.upload:
        if not args.file:
            _err("--upload requires --file")
            return 1
        payload = client.upload_module_local(args.upload, args.file)
        m = payload["module"]
        _ok(f"Uploaded {m['size_bytes']} bytes, checksum={m['checksum'][:12]}…, status={m['status']}")
        return 0
    if args.sync:
        if not args.server_id:
            _err("--sync requires --server-id")
            return 1
        payload = client.sync_module(args.sync, args.server_id)
        _ok(f"Queued module_sync job {payload['job_id'][:8]}… (status={payload['status']})")
        _info("  check progress with: waiter jobs get " + payload["job_id"])
        return 0

    payload = client.list_modules()
    if args.as_json:
        _print_json(payload)
        return 0
    rows = [
        [m["module_id"][:8] + "…", f"{m['name']}@{m['version']}", m["status"], str(m["size_bytes"] or "-")]
        for m in payload["modules"]
    ]
    _print_table(["module_id", "name@version", "status", "size_bytes"], rows, title=f"Modules ({payload['count']})")
    return 0


def _cmd_jobs(rest: list[str]) -> int:
    p = argparse.ArgumentParser(prog="waiter jobs", description="Get or cancel a job by ID.")
    p.add_argument("action", choices=["get", "cancel"], help="get: show status/result. cancel: request cancellation.")
    p.add_argument("job_id")
    _add_common_connection_args(p)
    args = p.parse_args(rest)
    client, _ = _client_for(args)
    payload = client.cancel_job(args.job_id) if args.action == "cancel" else client.get_job(args.job_id)
    if args.as_json:
        _print_json(payload)
        return 0
    j = payload["job"]
    rows = [[k, str(v)] for k, v in j.items()]
    _print_table(["field", "value"], rows, title=f"Job {j['job_id'][:8]}…")
    return 0


def _cmd_events(rest: list[str]) -> int:
    p = argparse.ArgumentParser(prog="waiter events", description="Poll recent events.")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--since", dest="since_id", default=None, help="Only events after this event_id")
    _add_common_connection_args(p)
    args = p.parse_args(rest)
    client, _ = _client_for(args)
    payload = client.list_events(limit=args.limit, since_id=args.since_id)
    if args.as_json:
        _print_json(payload)
        return 0
    rows = [[e["type"], e["source"], str(e["data"])[:60]] for e in payload["events"]]
    _print_table(["type", "source", "data"], rows, title=f"Events ({payload['count']})")
    return 0


def _cmd_billing(rest: list[str]) -> int:
    p = argparse.ArgumentParser(prog="waiter billing", description="Show balance/transactions, or redeem a payment token.")
    p.add_argument("--redeem", metavar="TOKEN", default=None, help="Redeem a payment token into your account")
    p.add_argument("--transactions", action="store_true", help="Show transaction history instead of just balance")
    _add_common_connection_args(p)
    args = p.parse_args(rest)
    client, _ = _client_for(args)
    if args.redeem:
        payload = client.redeem_payment_token(args.redeem)
        _ok(f"Redeemed — new balance: {payload['balance']} ({payload['account_type']}:{payload['account_id']})")
        return 0
    if args.transactions:
        payload = client.billing_transactions()
        if args.as_json:
            _print_json(payload)
            return 0
        rows = [[t["transaction_id"], t["kind"], f"{t['amount']:+.2f}", f"{t['balance_after']:.2f}", t["note"]] for t in payload["transactions"]]
        _print_table(["txn_id", "kind", "amount", "balance_after", "note"], rows, title="Transactions")
        return 0
    payload = client.billing_balance()
    if args.as_json:
        _print_json(payload)
        return 0
    _info(f"Balance: {payload['balance']} ({payload['account_type']}:{payload['account_id']})")
    return 0


# ---------------------------------------------------------------------------
# Beta 3 subcommands — keys, audit, security, cost, deploy, tui, doctor, smoke
# ---------------------------------------------------------------------------


def _cmd_tui(rest: list[str]) -> int:
    p = argparse.ArgumentParser(prog="waiter tui", description="Open the full curses dashboard (same as `waiter serv -G`).")
    _add_common_connection_args(p)
    args = p.parse_args(rest)
    return _launch_tui(_resolve_config(args))


def _cmd_keys(rest: list[str]) -> int:
    p = argparse.ArgumentParser(prog="waiter keys", description="List keys, or assign a plan/account/models to one.")
    p.add_argument("--assign", metavar="KEY_ID", default=None, help="Assign settings to this key_id (admin)")
    p.add_argument("--plan", default=None, help="Plan to assign with --assign")
    p.add_argument("--account", dest="account_id", default=None)
    p.add_argument("--user", dest="user_id", default=None)
    p.add_argument("--models", default=None, help="Comma-separated model_ids to narrow this key to")
    p.add_argument("--servers", default=None, help="Comma-separated server_ids to bind this key to")
    p.add_argument("--import-file", dest="import_file", default=None, help="Import a Keymaster export JSON file (admin)")
    p.add_argument("--include-inactive", action="store_true")
    _add_common_connection_args(p)
    args = p.parse_args(rest)
    client, _ = _client_for(args)

    if args.import_file:
        with open(args.import_file, encoding="utf-8") as handle:
            payload = json.load(handle)
        result = client.import_keys(payload)
        _ok(f"Imported {result['imported']} key(s), skipped {result['skipped']} duplicate(s).")
        return 0

    if args.assign:
        fields: dict[str, Any] = {}
        if args.plan is not None:
            fields["plan"] = args.plan
        if args.account_id is not None:
            fields["account_id"] = args.account_id
        if args.user_id is not None:
            fields["user_id"] = args.user_id
        if args.models is not None:
            fields["allowed_models"] = [m.strip() for m in args.models.split(",") if m.strip()]
        if args.servers is not None:
            fields["server_ids"] = [s.strip() for s in args.servers.split(",") if s.strip()]
        if not fields:
            _err("--assign needs at least one of --plan/--account/--user/--models/--servers.")
            return 1
        assignment = client.assign_key(args.assign, **fields)["assignment"]
        _ok(f"Assigned {assignment['key_id']} → plan '{assignment['plan']}'")
        if assignment["allowed_models"]:
            _info(f"  restricted to: {', '.join(assignment['allowed_models'])}")
        return 0

    keys = client.list_keys(include_inactive=args.include_inactive)
    if args.as_json:
        _print_json([k.raw for k in keys])
        return 0
    rows = [
        [
            k.key_id,
            k.key_type,
            ",".join(k.scopes),
            k.plan or "-",
            "yes" if k.active else "no",
            str(k.request_count),
        ]
        for k in keys
    ]
    _print_table(["key_id", "type", "scopes", "plan", "active", "requests"], rows, title=f"Keys ({len(keys)})")
    if not keys:
        _info("No keys visible. A non-admin key only ever sees itself.")
    return 0


def _cmd_audit(rest: list[str]) -> int:
    p = argparse.ArgumentParser(prog="waiter audit", description="Read the server's audit trail (admin only).")
    p.add_argument("--category", default=None, help="admin | security | write | billing")
    p.add_argument("--action", default=None, help="e.g. keys.assign")
    p.add_argument("--outcome", default=None, help="success | denied | failure")
    p.add_argument("--limit", type=int, default=50)
    _add_common_connection_args(p)
    args = p.parse_args(rest)
    client, _ = _client_for(args)
    payload = client.audit_events(
        category=args.category, action=args.action, outcome=args.outcome, limit=args.limit
    )
    if args.as_json:
        _print_json(payload)
        return 0
    rows = [
        [
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e["ts"])),
            e["category"],
            e["action"],
            e["outcome"],
            e["actor_key_id"] or "-",
            e["client_ip"] or "-",
        ]
        for e in payload["events"]
    ]
    _print_table(
        ["when", "category", "action", "outcome", "actor", "ip"],
        rows,
        title=f"Audit ({payload['count']} of {payload['total']})",
    )
    return 0


def _cmd_security(rest: list[str]) -> int:
    p = argparse.ArgumentParser(prog="waiter security", description="Inspect and edit the server's network policy and forced limits.")
    p.add_argument("--block", metavar="CIDR", default=None, help="Blacklist an IP/CIDR")
    p.add_argument("--allow", metavar="CIDR", default=None, help="Allowlist an IP/CIDR")
    p.add_argument("--appeal", metavar="CIDR", default=None, help="Remove an allow/block entry")
    p.add_argument("--reason", default="", help="Reason recorded with --block/--allow")
    p.add_argument("--allow-unlisted", dest="allow_unlisted", choices=["on", "off"], default=None,
                   help="Whether clients on neither list may connect")
    p.add_argument("--limits", action="store_true", help="Show forced limits instead of the IP lists")
    p.add_argument("--my-rate-limits", action="store_true", help="Show your own remaining rate-limit budget")
    _add_common_connection_args(p)
    args = p.parse_args(rest)
    client, _ = _client_for(args)

    if args.my_rate_limits:
        payload = client.rate_limit_status()
        rows = [[r["rule"], f"{r['remaining']:.0f}/{r['capacity']:.0f}", f"{r['refill_per_second']}/s"] for r in payload["rules"]]
        _print_table(["rule", "remaining", "refill"], rows, title=f"Your rate limits (enabled={payload['enabled']})")
        return 0

    if args.block:
        client.blacklist_ip(args.block, reason=args.reason)
        _ok(f"Blocked {args.block}")
    if args.allow:
        client.whitelist_ip(args.allow, reason=args.reason)
        _ok(f"Allowlisted {args.allow}")
    if args.appeal:
        client.appeal_ip(args.appeal)
        _ok(f"Removed {args.appeal} from the server's lists")
    if args.allow_unlisted is not None:
        client.set_allow_unlisted(args.allow_unlisted == "on")
        _ok(f"Unlisted clients may now connect: {args.allow_unlisted == 'on'}")

    if args.limits:
        limits = client.list_forced_limits()
        rows = [
            [
                f"{limit['subject_type']}:{limit['subject_id']}",
                str(limit["requests_per_window"] or "-"),
                str(limit["tokens_per_window"] or "-"),
                f"{limit['window_seconds']:g}s",
                limit["reason"],
            ]
            for limit in limits
        ]
        _print_table(["subject", "requests", "tokens", "window", "reason"], rows, title=f"Forced limits ({len(limits)})")
        return 0

    payload = client.network_policy()
    if args.as_json:
        _print_json(payload)
        return 0
    rows = [[e["cidr"], e["kind"], e["reason"], "expired" if e["expired"] else "active"] for e in payload["entries"]]
    _print_table(["cidr", "kind", "reason", "state"], rows, title=f"Network policy ({payload['count']})")
    _info(
        f"  unlisted clients may connect: {payload['allow_unlisted_clients']} "
        f"(policy enforcement enabled: {payload['enabled']})"
    )
    return 0


def _cmd_cost(rest: list[str]) -> int:
    p = argparse.ArgumentParser(prog="waiter cost", description="Show spend, breakdowns, and a forecast.")
    p.add_argument("--group-by", dest="group_by", default="model_id",
                   help="model_id | key_id | server_id | module_id | user_id | account_id | endpoint")
    p.add_argument("--range", dest="range_", default="30d", help="1h | 24h | 7d | 30d | all")
    p.add_argument("--forecast", action="store_true", help="Include a spend forecast")
    p.add_argument("--estimate-model", dest="estimate_model", default=None, help="Estimate a prospective call instead")
    p.add_argument("--input-tokens", dest="input_tokens", type=int, default=0)
    p.add_argument("--output-tokens", dest="output_tokens", type=int, default=None)
    _add_common_connection_args(p)
    args = p.parse_args(rest)
    client, _ = _client_for(args)

    if args.estimate_model:
        estimate = client.estimate_cost(
            model_id=args.estimate_model,
            input_tokens=args.input_tokens,
            output_tokens=args.output_tokens,
        )
        if args.as_json:
            _print_json(estimate)
            return 0
        _print_table(
            ["field", "value"],
            [[k, str(v)] for k, v in estimate.items() if k != "request_id"],
            title=f"Estimate — {args.estimate_model}",
        )
        return 0

    report = client.usage_cost(group_by=args.group_by, range=args.range_, forecast=args.forecast)
    if args.as_json:
        _print_json(report.raw)
        return 0
    rows = [
        [line["value"], str(line["requests"]), str(line["total_tokens"]), f"{line['total_cost']:.6f}"]
        for line in report.lines
    ]
    _print_table(
        [args.group_by, "requests", "tokens", "cost"],
        rows,
        title=f"Cost — {report.total_cost:.6f} {report.currency} over {args.range_}",
    )
    if report.unpriced_models:
        _warn(
            "Usage recorded against models no longer in the registry (priced at 0): "
            + ", ".join(report.unpriced_models)
        )
    if report.forecast:
        f = report.forecast
        _info(
            f"  Forecast: {f['projected_cost']:.6f} {f['currency']} over "
            f"{f['horizon_seconds'] / 86400:.0f}d — {f['confidence']} confidence. {f['basis']}"
        )
    return 0


def _cmd_deploy(rest: list[str]) -> int:
    p = argparse.ArgumentParser(prog="waiter deploy", description="Push a module to one or more trusted servers and watch the job.")
    p.add_argument("module_id")
    p.add_argument("--to", dest="server_ids", required=True, help="Comma-separated server_ids")
    p.add_argument("--wait", action="store_true", help="Block until the deployment job settles")
    p.add_argument("--timeout", type=float, default=300.0)
    _add_common_connection_args(p)
    args = p.parse_args(rest)
    client, _ = _client_for(args)
    server_ids = [s.strip() for s in args.server_ids.split(",") if s.strip()]

    queued = client.deploy_module(args.module_id, server_ids)
    _ok(f"Queued deployment job {queued['job_id'][:8]}… to {len(server_ids)} server(s)")
    if not args.wait:
        _info(f"  watch it with: waiter jobs get {queued['job_id']}")
        return 0

    job = client.wait_for_job(queued["job_id"], timeout=args.timeout)
    if not job.succeeded:
        _err(f"Deployment {job.status}: {job.error or 'no error recorded'}")
        for failure in (job.result or {}).get("failed", []):
            _info(f"  {failure['server_id']}: {failure['error_code']} — {failure['message']}")
        return 1
    delivered = (job.result or {}).get("delivered", [])
    _ok(f"Deployed to {len(delivered)} server(s)")
    for item in delivered:
        _info(f"  {item['server_id']}: {item['bytes_transferred']} bytes, sha256={item['checksum'][:12]}…")
    return 0


def _cmd_doctor(rest: list[str]) -> int:
    p = argparse.ArgumentParser(prog="waiter doctor", description="Check a server's configuration and report anything unsafe for production.")
    _add_common_connection_args(p)
    args = p.parse_args(rest)
    client, cfg = _client_for(args)
    status = client.status()

    if args.as_json:
        _print_json(status.raw)
        return 0

    _print_table(
        ["check", "value"],
        [
            ["environment", status.environment],
            ["beta", status.beta],
            ["t1 api version", status.t1_api_version],
            ["hypernix version", status.hypernix_version],
            ["storage backend", status.storage_backend],
            ["TLS", str(status.tls_enabled)],
            ["mTLS mode", status.mtls_mode],
            ["rate limiting", str(status.rate_limit_enabled)],
            ["audit logging", str(status.audit_enabled)],
            ["network policy", str(status.network_policy_enabled)],
            ["unlisted clients", str(status.allow_unlisted_clients)],
            ["remote deployment", str(status.remote_deployment_enabled)],
            ["production ready", str(status.production_ready)],
        ],
        title=f"Server health — {cfg.server}",
    )
    secrets = status.secrets_configured
    if secrets:
        _print_table(
            ["secret", "configured"],
            [[name, "yes" if value else "NO"] for name, value in secrets.items()],
            title="Secrets (set/unset only — values are never exposed)",
        )
    if status.production_warnings:
        _warn(f"{len(status.production_warnings)} configuration warning(s):")
        for warning in status.production_warnings:
            _info(f"  • {warning}")
        return 0 if status.environment != "production" else 1
    _ok("No configuration warnings reported.")
    return 0


def _cmd_smoke(rest: list[str]) -> int:
    """CLI smoke-testing tool (spec deliverable #11)."""
    from .smoke import run_smoke_tests

    p = argparse.ArgumentParser(prog="waiter smoke", description="Run read-only smoke tests against a T1 API server.")
    p.add_argument("--write", action="store_true", help="Also run write tests (creates and deletes a scratch module)")
    p.add_argument("--fail-fast", action="store_true", help="Stop at the first failure")
    _add_common_connection_args(p)
    args = p.parse_args(rest)
    client, cfg = _client_for(args)
    return run_smoke_tests(
        client,
        base_url=cfg.server or "",
        include_write=args.write,
        fail_fast=args.fail_fast,
        as_json=args.as_json,
    )


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_USAGE = """\
waiter — the official T1 API TUI/CLI

Usage:
  waiter serv     One-shot automatic setup: waiter serv -A -I <server> -K <T1_TOKEN> -E
  waiter models   List models visible in the server's registry
  waiter model    Show detail/availability/usage for one model
  waiter route    Ask the routing engine which model to use (--plan, --model, --auto-fallback)
  waiter status   Server status
  waiter health   Server liveness check
  waiter whoami   Validate the configured key and show its scopes
  waiter usage    Show current usage (or --model <id> for remaining allowance)
  waiter servers  List / register servers (--register NAME --address ...)
  waiter modules  List modules, or --create/--upload/--sync one
  waiter jobs     get|cancel <job_id>
  waiter events   Poll recent events (--limit, --since)
  waiter billing  Balance/transactions, or --redeem <token>
  waiter cost     Spend, per-model/server breakdowns, forecasts, estimates
  waiter keys     List keys; --assign a plan/account/models; --import-file
  waiter deploy   Push a module to trusted servers (--to, --wait)
  waiter security Network policy (--block/--allow/--appeal), forced limits
  waiter audit    Read the server's audit trail (admin)
  waiter doctor   Check a server's configuration for production readiness
  waiter smoke    Run smoke tests against a server
  waiter tui      Open the full curses dashboard (same as `waiter serv -G`)
  waiter config   Show the locally saved config

Every subcommand accepts -I/-K/-F/-P/-H to override the saved config for
just that call, and --json for raw JSON output.

Run `waiter <subcommand> --help` for detailed options.
"""


def main(argv: list[str] | None = None) -> int:
    """Entry point for the `waiter` console script."""
    raw = list(sys.argv[1:] if argv is None else argv)

    if not raw or raw[0] in ("-h", "--help"):
        print(_USAGE)
        return 0

    if raw[0] in ("-V", "--version"):
        from . import __waiter_version__

        print(f"waiter {__waiter_version__}")
        return 0

    cmd, rest = raw[0], raw[1:]
    dispatch = {
        "serv": _cmd_serv,
        "models": _cmd_models,
        "model": _cmd_model,
        "status": _cmd_status,
        "health": _cmd_health,
        "whoami": _cmd_whoami,
        "usage": _cmd_usage,
        "config": _cmd_config,
        "route": _cmd_route,
        "servers": _cmd_servers,
        "modules": _cmd_modules,
        "jobs": _cmd_jobs,
        "events": _cmd_events,
        "billing": _cmd_billing,
        "keys": _cmd_keys,
        "audit": _cmd_audit,
        "security": _cmd_security,
        "cost": _cmd_cost,
        "deploy": _cmd_deploy,
        "tui": _cmd_tui,
        "doctor": _cmd_doctor,
        "smoke": _cmd_smoke,
    }

    if cmd not in dispatch:
        print(f"Unknown subcommand: {cmd!r}\n", file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        return 1

    try:
        return dispatch[cmd](rest)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    except T1ClientError as exc:
        _err(str(exc))
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"[waiter {cmd}] Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
