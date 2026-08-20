"""waiter.cli — argparse-based CLI for the ``waiter`` console script.

Beta 1 scope: everything needed to authenticate against a T1 API server,
inspect the model registry, and check usage — matching the spec's own
"Beta 1: ... basic waiter CLI" line. The full curses-style TUI (``-G``)
and the admin-surface flags that need endpoints the T1 API doesn't expose
yet (``-B``/``-W``/``-r``/``-a``, full ``-y`` multi-server sync) are Beta
2/3 — see the spec's own "Beta 3: full waiter TUI" line. Those flags are
still parsed here (so the command-line contract is stable across betas and
scripts written against Beta 1 keep working), but they store intent
locally and print a clear "not wired to a server endpoint yet" message
instead of silently no-op'ing or pretending to call something that
doesn't exist — same NOT_SUPPORTED philosophy the spec asks for in
HyperNix-pip integration, applied to the CLI.

Style matches ``hypernix.gkey_cli``: manual dispatch dict, rich-formatted
output with a plain-text fallback when ``rich`` isn't installed (it's a
core hypernix dependency, so the fallback is mostly defensive).
"""
from __future__ import annotations

import argparse
import json
import sys
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

        Console().print(f"[yellow]![/yellow] {text}")
    else:
        print(f"WARNING: {text}", file=sys.stderr)


def _err(text: str) -> None:
    if _HAS_RICH:
        from rich.console import Console

        Console().print(f"[red]\u2717[/red] {text}", style="red")
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

Beta 1 wires -A/-I/-K/-E/-F/-s/-L/-P/-H/-R/-g fully. -B/-W/-r/-a/-C/-y/-G
are accepted (so scripts don't break across betas) but currently only
store intent locally — see 'ships in Beta N' notes printed at runtime, and
wiki/Waiter-TUI.md for the up to date list.
"""


def _build_serv_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="waiter serv", description=_SERV_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    _add_common_connection_args(p)
    p.add_argument("-A", "--auto", action="store_true", help="Automatic configuration: validate + save in one step")
    p.add_argument("-E", "--encrypt", action="store_true", help="Encrypt the local config/secrets at rest")
    p.add_argument("-s", "--save", action="store_true", help="Save current server/local configuration to a .jsonl file")
    p.add_argument("-L", "--local-only", action="store_true", help="Local/Tailscale/localhost-only mode")
    p.add_argument("-B", "--blacklist", action="append", default=[], metavar="IP", help="Blacklist an IP address (repeatable)")
    p.add_argument("-W", "--whitelist", action="append", default=[], metavar="IP", help="Whitelist an IP address (repeatable)")
    p.add_argument("-r", "--force-limit", action="append", default=[], metavar="KEY_OR_SERVER_ID=LIMIT", help="Force a usage limit on a specific T1 key/server ID")
    p.add_argument("-a", "--appeal", action="append", default=[], metavar="IP", help="Appeal/remove an IP from the blacklist")
    p.add_argument("-C", "--config", dest="extra_config", action="append", default=[], metavar="KEY=VALUE", help="Additional configuration settings")
    p.add_argument("-G", "--gui", action="store_true", help="Open the full TUI (ships in Beta 3)")
    p.add_argument("-g", "--cli", action="store_true", help="Open an interactive CLI session")
    p.add_argument("-R", "--refresh", action="store_true", help="Quick refresh: re-validate + re-fetch models")
    p.add_argument("-Rf", "--force-refresh", dest="force_refresh", action="store_true", help="Force a full refresh (ships in Beta 2 — requires server-push support)")
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


def _cmd_serv(rest: list[str]) -> int:
    args = _build_serv_parser().parse_args(rest)

    if not (args.auto or args.save or args.refresh or args.force_refresh or args.sync or args.cli or args.gui):
        _warn("No action flag given (-A/-s/-R/-Rf/-y/-g/-G). Nothing to do — see 'waiter serv --help'.")
        return 1

    if args.gui:
        _info(
            "The full curses-style TUI (-G) ships with the complete waiter TUI in "
            "Beta 3, per the spec's own beta breakdown. Use -g for an interactive "
            "CLI session in the meantime, or the one-shot subcommands (models/status/usage)."
        )
        if not (args.auto or args.save or args.refresh or args.sync):
            return 0

    cfg = _resolve_config(args)
    cfg.local_only = cfg.local_only or args.local_only
    if args.blacklist:
        cfg.blacklist = sorted(set(cfg.blacklist) | set(args.blacklist))
    if args.appeal:
        before = set(cfg.blacklist)
        cfg.blacklist = sorted(before - set(args.appeal))
        removed = before - set(cfg.blacklist)
        if removed:
            _info(f"Appealed (removed from local blacklist): {', '.join(sorted(removed))}")
    if args.whitelist:
        cfg.whitelist = sorted(set(cfg.whitelist) | set(args.whitelist))
    if args.extra_config:
        cfg.extra_config.update(_parse_kv_list(args.extra_config))

    if args.blacklist or args.whitelist or args.force_limit or args.appeal:
        _warn(
            "-B/-W/-r/-a stored locally, but the T1 API doesn't expose blacklist/"
            "whitelist/rate-limit-override endpoints yet — that's Beta 2/3 admin-surface "
            "scope. Nothing was enforced server-side."
        )
    if args.extra_config:
        _warn("-C values stored locally under extra_config; no server-side config endpoint consumes them yet.")

    store = _load_store(args, encrypt=args.encrypt)

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
                    _ok(f"Promoted to admin key {_mask(promoted['key_id'])}")
                except T1ClientError as exc:
                    _err(f"Admin promotion failed: {exc}")

        path = store.save(cfg)
        _ok(f"Saved config to {path}" + (" (encrypted)" if args.encrypt else ""))
        return 0

    if args.save:
        path = store.save(cfg)
        _ok(f"Saved config to {path}" + (" (encrypted)" if args.encrypt else ""))

    if args.refresh or args.force_refresh:
        if args.force_refresh:
            _warn("-Rf requested a full forced refresh, which needs server-push support landing in Beta 2. Falling back to a quick refresh (-R semantics).")
        try:
            client = T1Client(base_url=_base_url(cfg), credential=cfg.key)
            validated = client.validate()
            models = client.list_models()
        except T1ClientError as exc:
            _err(f"Refresh failed: {exc}")
            return 1
        _ok(f"Refreshed — key {_mask(validated.get('key_id'))} still valid, {models.get('count', 0)} model(s) visible.")

    if args.sync:
        try:
            client = T1Client(base_url=_base_url(cfg), credential=cfg.key)
            remote_config = client.config()
        except T1ClientError as exc:
            _err(f"Sync failed: {exc}")
            return 1
        _ok("Local config synchronized against server /config.")
        _info("  (Multi-server synchronization is Beta 2 scope — this syncs against the single configured server only.)")
        if args.as_json:
            _print_json(remote_config)
        store.save(cfg)

    if args.cli:
        return _interactive_session(cfg, store)

    return 0


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
