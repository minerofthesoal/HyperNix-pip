"""gkey_cli — Unified CLI for Gatekeeper and Keymaster.

Entry point: ``gkey`` (console script) or ``hypernix gkey``.

Subcommands
-----------
::

    gkey create     [--type dev|user|service|session|admin]
                    [--scopes read,write,admin,plugin,service]
                    [--expires YYYY-MM-DD] [--cap N] [--limit N]
                    [--prefix LABEL] [--tags k=v ...] [--body-len N]
                    [--note TEXT]

    gkey revoke     <key-id>  [--reason TEXT]

    gkey list       [--type TYPE] [--scope SCOPE]
                    [--all]  (include expired)
                    [--json]

    gkey list id    <key-id>    show full metadata for one key

    gkey stats      [--key KEY-ID]  [--log N]  [--json]

    gkey quota      --key KEY-ID
                    [--set max-requests=N,max-tokens=N,window=N]

    gkey permissions  --key KEY-ID

    gkey rotate     <key-id>

    gkey export     [--key KEY-ID] [--out FILE]

    gkey import     <FILE>

All output is rich-formatted when the ``rich`` package is available,
plain text otherwise.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Rich helpers (graceful degradation)
# ---------------------------------------------------------------------------


def _try_rich() -> bool:
    try:
        import rich  # noqa: F401
        return True
    except ImportError:
        return False


_HAS_RICH = _try_rich()


def _console():
    if _HAS_RICH:
        from rich.console import Console
        return Console()
    return None


def _print_rich(text: str, style: str = "") -> None:
    if _HAS_RICH:
        from rich.console import Console
        Console().print(text, style=style or "default")
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
            print("-" * len(title))
        widths = [max(len(h), max((len(r[i]) for r in rows), default=0)) for i, h in enumerate(headers)]
        fmt = "  ".join(f"{{:<{w}}}" for w in widths)
        print(fmt.format(*headers))
        print("  ".join("-" * w for w in widths))
        for row in rows:
            print(fmt.format(*row))


def _print_panel(content: str, title: str = "") -> None:
    if _HAS_RICH:
        from rich.console import Console
        from rich.panel import Panel
        Console().print(Panel(content, title=title, border_style="cyan"))
    else:
        if title:
            print(f"\n=== {title} ===")
        print(content)


# ---------------------------------------------------------------------------
# Shared Keymaster / Gatekeeper factory
# ---------------------------------------------------------------------------


def _get_km(store: Path | None = None):
    """Return a Keymaster instance (auto_rotate=False for CLI use)."""
    from .keymaster import Keymaster
    return Keymaster(store_dir=store, auto_rotate=False)


def _get_gk(km, data: Path | None = None):
    """Return a Gatekeeper backed by *km*."""
    from .gatekeeper import Gatekeeper
    return Gatekeeper(km, data_dir=data)


# ---------------------------------------------------------------------------
# Argument parsing helpers
# ---------------------------------------------------------------------------


def _parse_scopes(raw: str):
    from .keymaster import KeyScope
    mapping = {s.value: s for s in KeyScope}
    result = set()
    for part in raw.split(","):
        part = part.strip()
        if part not in mapping:
            raise SystemExit(
                f"Unknown scope: {part!r}. Valid: {', '.join(mapping)}"
            )
        result.add(mapping[part])
    return result


def _parse_expires(raw: str) -> float:
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        raise SystemExit(
            f"Invalid date format: {raw!r}. Use YYYY-MM-DD."
        ) from None


def _parse_tags(raw_list: list[str]) -> dict[str, str]:
    tags: dict[str, str] = {}
    for item in raw_list:
        if "=" not in item:
            raise SystemExit(f"Invalid tag format: {item!r}. Use key=value.")
        k, v = item.split("=", 1)
        tags[k.strip()] = v.strip()
    return tags


def _fmt_ts(ts: float | None) -> str:
    if ts is None:
        return "—"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ---------------------------------------------------------------------------
# Subcommand: create
# ---------------------------------------------------------------------------


def _cmd_create(args: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="gkey create")
    p.add_argument("--type", dest="key_type", default="user",
                   choices=["dev", "development", "user", "service", "session", "admin"])
    p.add_argument("--scopes", default="read",
                   help="Comma-separated scopes: read,write,admin,plugin,service")
    p.add_argument("--expires", default=None, metavar="YYYY-MM-DD")
    p.add_argument("--cap", type=int, default=None, metavar="TOKENS",
                   help="Lifetime token cap")
    p.add_argument("--limit", type=int, default=None, metavar="REQUESTS",
                   help="Lifetime request limit")
    p.add_argument("--prefix", default="", help="Short human label for the key")
    p.add_argument("--tags", nargs="*", default=[], metavar="KEY=VALUE")
    p.add_argument("--body-len", type=int, default=24, metavar="N",
                   help="Body length of generated key (default 24, min 16)")
    p.add_argument("--note", default="", help="Free-text note attached to the key")
    p.add_argument("--rotation-window", type=int, default=24, metavar="HOURS",
                   help="Hours before expiry to auto-rotate (default 24)")
    ns = p.parse_args(args)

    from .keymaster import KeyType
    type_map = {
        "dev": KeyType.DEVELOPMENT,
        "development": KeyType.DEVELOPMENT,
        "user": KeyType.USER,
        "service": KeyType.SERVICE,
        "session": KeyType.SESSION,
        "admin": KeyType.ADMIN,
    }
    scopes = _parse_scopes(ns.scopes)
    expires = _parse_expires(ns.expires) if ns.expires else None
    tags = _parse_tags(ns.tags)

    km = _get_km()
    meta = km.create(
        key_type=type_map[ns.key_type],
        scopes=scopes,
        expires_at=expires,
        usage_cap=ns.cap,
        request_limit=ns.limit,
        prefix=ns.prefix,
        tags=tags,
        rotation_window=ns.rotation_window,
        note=ns.note,
        body_length=ns.body_len,
    )
    km.stop()

    content_lines = [
        f"[bold green]Key created successfully![/bold green]",
        "",
        f"[bold]Key ID:[/bold]     {meta.key_id}",
        f"[bold]Key:[/bold]        [yellow]{meta.key}[/yellow]",
        f"[bold]Type:[/bold]       {meta.key_type.value}",
        f"[bold]Scopes:[/bold]     {', '.join(s.value for s in sorted(meta.scopes, key=lambda x: x.value))}",
        f"[bold]Expires:[/bold]    {_fmt_ts(meta.expires_at)}",
        f"[bold]Server ID:[/bold]  {meta.server_id}",
        f"[bold]Prefix:[/bold]     {meta.prefix or '—'}",
        f"[bold]Note:[/bold]       {meta.note or '—'}",
    ]
    if tags:
        content_lines.append(f"[bold]Tags:[/bold]       {json.dumps(tags)}")

    if _HAS_RICH:
        _print_panel("\n".join(content_lines), title="gkey create")
    else:
        print("Key created successfully!")
        print(f"  Key ID:    {meta.key_id}")
        print(f"  Key:       {meta.key}")
        print(f"  Type:      {meta.key_type.value}")
        print(f"  Scopes:    {', '.join(s.value for s in sorted(meta.scopes, key=lambda x: x.value))}")
        print(f"  Expires:   {_fmt_ts(meta.expires_at)}")
        print(f"  Server ID: {meta.server_id}")

    return 0


# ---------------------------------------------------------------------------
# Subcommand: revoke
# ---------------------------------------------------------------------------


def _cmd_revoke(args: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="gkey revoke")
    p.add_argument("key_id", help="Key ID to revoke")
    p.add_argument("--reason", default="", help="Reason for revocation")
    ns = p.parse_args(args)

    km = _get_km()
    try:
        km.revoke(ns.key_id, reason=ns.reason)
        km.stop()
        _print_rich(f"[bold red]✗[/bold red] Key [cyan]{ns.key_id[:8]}…[/cyan] revoked.")
        return 0
    except KeyError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        km.stop()
        return 1


# ---------------------------------------------------------------------------
# Subcommand: list
# ---------------------------------------------------------------------------


def _cmd_list(args: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="gkey list")
    p.add_argument("key_id", nargs="?", default=None,
                   help="If 'id <key-id>', show detailed info for one key")
    p.add_argument("--type", dest="key_type", default=None,
                   choices=["dev", "development", "user", "service", "session", "admin"])
    p.add_argument("--scope", default=None)
    p.add_argument("--all", dest="include_all", action="store_true",
                   help="Include expired keys")
    p.add_argument("--json", dest="as_json", action="store_true")
    ns = p.parse_args(args)

    km = _get_km()

    # `gkey list id <key-id>` form
    if ns.key_id == "id":
        print("Usage: gkey list id <key-id>", file=sys.stderr)
        km.stop()
        return 1

    if ns.key_id is not None:
        # Single-key detail view
        meta = km.get(ns.key_id)
        if meta is None:
            print(f"Key not found: {ns.key_id!r}", file=sys.stderr)
            km.stop()
            return 1
        km.stop()
        if ns.as_json:
            print(json.dumps(meta.to_dict(), indent=2))
        else:
            _print_detail(meta)
        return 0

    from .keymaster import KeyScope, KeyType
    type_map = {
        "dev": KeyType.DEVELOPMENT, "development": KeyType.DEVELOPMENT,
        "user": KeyType.USER, "service": KeyType.SERVICE,
        "session": KeyType.SESSION, "admin": KeyType.ADMIN,
    }
    key_type = type_map[ns.key_type] if ns.key_type else None
    scope = None
    if ns.scope:
        scope_map = {s.value: s for s in KeyScope}
        scope = scope_map.get(ns.scope)

    keys = km.list(
        key_type=key_type,
        scope=scope,
        active_only=not ns.include_all,
        include_expired=ns.include_all,
    )
    km.stop()

    if ns.as_json:
        print(json.dumps([m.to_dict() for m in keys], indent=2))
        return 0

    if not keys:
        _print_rich("[dim]No keys found.[/dim]")
        return 0

    headers = ["Key ID (short)", "Type", "Scopes", "Expires", "Status", "Prefix"]
    rows = []
    for m in keys:
        scopes_str = ",".join(s.value for s in sorted(m.scopes, key=lambda x: x.value))
        status = "active" if (m.active and not m.is_expired) else (
            "expired" if m.is_expired else "revoked"
        )
        rows.append([
            m.key_id[:12] + "…",
            m.key_type.value,
            scopes_str,
            _fmt_ts(m.expires_at),
            status,
            m.prefix or "—",
        ])
    _print_table(headers, rows, title=f"Keys ({len(keys)})")
    return 0


def _print_detail(meta: Any) -> None:
    """Print full key metadata."""
    lines = [
        f"Key ID:          {meta.key_id}",
        f"Key:             {meta.key}",
        f"Type:            {meta.key_type.value}",
        f"Scopes:          {', '.join(s.value for s in sorted(meta.scopes, key=lambda x: x.value))}",
        f"Created:         {_fmt_ts(meta.created_at)}",
        f"Expires:         {_fmt_ts(meta.expires_at)}",
        f"Rotation window: {meta.rotation_window}h",
        f"Usage cap:       {meta.usage_cap or '—'}",
        f"Request limit:   {meta.request_limit or '—'}",
        f"Usage count:     {meta.usage_count}",
        f"Request count:   {meta.request_count}",
        f"Server ID:       {meta.server_id}",
        f"Prefix:          {meta.prefix or '—'}",
        f"Tags:            {json.dumps(meta.tags) if meta.tags else '—'}",
        f"Active:          {meta.active}",
        f"Note:            {meta.note or '—'}",
    ]
    if meta.rotated_from:
        lines.append(f"Rotated from:    {meta.rotated_from}")
    if meta.revoked_at:
        lines.append(f"Revoked at:      {_fmt_ts(meta.revoked_at)}")
    _print_panel("\n".join(lines), title=f"Key Detail — {meta.key_id[:8]}…")


# ---------------------------------------------------------------------------
# Subcommand: list id (separate positional form)
# ---------------------------------------------------------------------------


def _cmd_list_id(args: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="gkey list id")
    p.add_argument("key_id", help="Key ID to inspect")
    p.add_argument("--json", dest="as_json", action="store_true")
    ns = p.parse_args(args)

    km = _get_km()
    meta = km.get(ns.key_id)
    km.stop()
    if meta is None:
        print(f"Key not found: {ns.key_id!r}", file=sys.stderr)
        return 1
    if ns.as_json:
        print(json.dumps(meta.to_dict(), indent=2))
    else:
        _print_detail(meta)
    return 0


# ---------------------------------------------------------------------------
# Subcommand: stats
# ---------------------------------------------------------------------------


def _cmd_stats(args: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="gkey stats")
    p.add_argument("--key", default=None, metavar="KEY-ID",
                   help="Show stats for a single key")
    p.add_argument("--log", type=int, default=0, metavar="N",
                   help="Also print the last N usage log entries")
    p.add_argument("--json", dest="as_json", action="store_true")
    ns = p.parse_args(args)

    km = _get_km()
    gk = _get_gk(km)

    if ns.key:
        data = gk.get_stats(ns.key)
        result: Any = data
    else:
        result = gk.get_all_stats()

    log_entries: list[dict[str, Any]] = []
    if ns.log > 0:
        log_entries = gk.get_usage_log(key_id=ns.key, limit=ns.log)

    km.stop()
    gk.stop()

    if ns.as_json:
        out: Any = result
        if log_entries:
            if isinstance(out, dict):
                out["log"] = log_entries
            else:
                out = {"stats": out, "log": log_entries}
        print(json.dumps(out, indent=2))
        return 0

    # Pretty print
    if isinstance(result, dict):
        _print_stats_single(result)
    else:
        if not result:
            _print_rich("[dim]No usage data recorded yet.[/dim]")
        else:
            headers = ["Key ID", "Type", "Requests", "Tokens", "Last Used"]
            rows = []
            for s in result:
                rows.append([
                    s["key_id"][:12] + "…",
                    s.get("key_type", "—"),
                    str(s.get("total_requests", 0)),
                    str(s.get("total_tokens", 0)),
                    _fmt_ts(s.get("last_used")),
                ])
            _print_table(headers, rows, title="Usage Statistics")

    if log_entries:
        log_headers = ["Time", "Key ID", "Endpoint", "Model", "Tokens"]
        log_rows = []
        for e in log_entries:
            log_rows.append([
                _fmt_ts(e.get("timestamp")),
                e.get("key_id", "")[:12] + "…",
                e.get("endpoint", "—"),
                e.get("model", "—"),
                str(e.get("tokens_used", 0)),
            ])
        _print_table(log_headers, log_rows, title="Recent Log Entries")

    return 0


def _print_stats_single(s: dict[str, Any]) -> None:
    lines = [
        f"Key ID:          {s['key_id']}",
        f"Type:            {s.get('key_type', '—')}",
        f"Active:          {s.get('active', False)}",
        f"Scopes:          {', '.join(s.get('scopes', []))}",
        f"Total requests:  {s.get('total_requests', 0)}",
        f"Total tokens:    {s.get('total_tokens', 0)}",
        f"Lifetime reqs:   {s.get('lifetime_request_count', 0)}",
        f"Lifetime tokens: {s.get('lifetime_token_count', 0)}",
        f"Request limit:   {s.get('request_limit') or '—'}",
        f"Token cap:       {s.get('usage_cap') or '—'}",
        f"Last used:       {_fmt_ts(s.get('last_used'))}",
        f"Window reqs:     {s.get('window_requests', 0)}",
        f"Window tokens:   {s.get('window_tokens', 0)}",
    ]
    if s.get("quota"):
        q = s["quota"]
        lines.append(
            f"Quota:           {q.get('max_requests', '∞')} req / "
            f"{q.get('max_tokens', '∞')} tok per {q.get('window_seconds', 60)}s"
        )
    _print_panel("\n".join(lines), title=f"Stats — {s['key_id'][:8]}…")


# ---------------------------------------------------------------------------
# Subcommand: quota
# ---------------------------------------------------------------------------


def _cmd_quota(args: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="gkey quota")
    p.add_argument("--key", required=True, metavar="KEY-ID")
    p.add_argument("--set", dest="quota_set", default=None,
                   metavar="max-requests=N,max-tokens=N,window=N",
                   help="Set quota values (comma-separated key=value pairs)")
    ns = p.parse_args(args)

    km = _get_km()
    gk = _get_gk(km)

    if ns.quota_set:
        from .gatekeeper import Quota
        qargs: dict[str, Any] = {}
        for part in ns.quota_set.split(","):
            part = part.strip()
            if "=" not in part:
                print(f"Invalid quota spec: {part!r}", file=sys.stderr)
                km.stop(); gk.stop()
                return 1
            k, v = part.split("=", 1)
            k = k.strip().replace("-", "_")
            try:
                qargs[k] = float(v) if "." in v else int(v)
            except ValueError:
                print(f"Invalid value for {k}: {v!r}", file=sys.stderr)
                km.stop(); gk.stop()
                return 1
        quota = Quota(
            max_requests=qargs.get("max_requests"),
            max_tokens=qargs.get("max_tokens"),
            window_seconds=float(qargs.get("window", 60)),
        )
        gk.set_quota(ns.key, quota)
        gk._save_usage()
        _print_rich(
            f"[green]✓[/green] Quota set for [cyan]{ns.key[:8]}…[/cyan]: "
            f"max_requests={quota.max_requests}, max_tokens={quota.max_tokens}, "
            f"window={quota.window_seconds}s"
        )
    else:
        quota = gk.get_quota(ns.key)
        if quota is None:
            _print_rich(f"[dim]No quota configured for {ns.key[:8]}…[/dim]")
        else:
            _print_panel(
                f"max_requests: {quota.max_requests or '∞'}\n"
                f"max_tokens:   {quota.max_tokens or '∞'}\n"
                f"window:       {quota.window_seconds}s",
                title=f"Quota — {ns.key[:8]}…",
            )
    km.stop(); gk.stop()
    return 0


# ---------------------------------------------------------------------------
# Subcommand: permissions
# ---------------------------------------------------------------------------


def _cmd_permissions(args: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="gkey permissions")
    p.add_argument("--key", required=True, metavar="KEY-ID")
    ns = p.parse_args(args)

    km = _get_km()
    meta = km.get(ns.key)
    km.stop()

    if meta is None:
        print(f"Key not found: {ns.key!r}", file=sys.stderr)
        return 1

    scopes = sorted(s.value for s in meta.scopes)
    if _HAS_RICH:
        from rich.console import Console
        from rich.table import Table
        t = Table(title=f"Permissions — {ns.key[:8]}…", header_style="bold cyan")
        t.add_column("Scope")
        t.add_column("Granted")
        from .keymaster import KeyScope
        all_scopes = [s.value for s in KeyScope]
        for s in all_scopes:
            granted = s in scopes
            t.add_row(s, "[green]✓[/green]" if granted else "[red]✗[/red]")
        Console().print(t)
    else:
        from .keymaster import KeyScope
        print(f"Permissions for {ns.key[:8]}…:")
        for s in KeyScope:
            mark = "✓" if s.value in scopes else "✗"
            print(f"  {mark} {s.value}")
    return 0


# ---------------------------------------------------------------------------
# Subcommand: rotate
# ---------------------------------------------------------------------------


def _cmd_rotate(args: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="gkey rotate")
    p.add_argument("key_id", help="Key ID to rotate")
    ns = p.parse_args(args)

    km = _get_km()
    try:
        new_meta = km.rotate(ns.key_id)
        km.stop()
        _print_rich(
            f"[green]✓[/green] Key rotated.\n"
            f"  Old: [red]{ns.key_id[:8]}…[/red]\n"
            f"  New: [green]{new_meta.key_id}[/green]\n"
            f"  Key: [yellow]{new_meta.key}[/yellow]"
        )
        return 0
    except KeyError as exc:
        km.stop()
        print(f"Error: {exc}", file=sys.stderr)
        return 1


# ---------------------------------------------------------------------------
# Subcommand: export
# ---------------------------------------------------------------------------


def _cmd_export(args: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="gkey export")
    p.add_argument("--key", default=None, metavar="KEY-ID",
                   help="Export a single key (default: all)")
    p.add_argument("--out", default=None, metavar="FILE",
                   help="Output file path (default: stdout)")
    ns = p.parse_args(args)

    km = _get_km()
    try:
        payload = km.export(path=ns.out, key_id=ns.key)
        km.stop()
    except KeyError as exc:
        km.stop()
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if ns.out:
        _print_rich(
            f"[green]✓[/green] Exported {len(payload['keys'])} key(s) to [cyan]{ns.out}[/cyan]"
        )
    else:
        print(json.dumps(payload, indent=2))
    return 0


# ---------------------------------------------------------------------------
# Subcommand: import
# ---------------------------------------------------------------------------


def _cmd_import(args: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="gkey import")
    p.add_argument("file", help="JSON file to import")
    ns = p.parse_args(args)

    path = Path(ns.file)
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 1

    km = _get_km()
    imported = km.import_keys(path)
    km.stop()
    _print_rich(
        f"[green]✓[/green] Imported [bold]{len(imported)}[/bold] key(s) from [cyan]{path}[/cyan]"
    )
    return 0


# ---------------------------------------------------------------------------
# Usage / dispatch
# ---------------------------------------------------------------------------

_USAGE = """\
gkey — Gatekeeper + Keymaster unified CLI

Usage:
  gkey create       Generate a new T1 API key
  gkey revoke       Revoke an existing key
  gkey list         List keys (gkey list id <id> for detail)
  gkey stats        Show usage statistics
  gkey quota        View or set rate-limit quotas
  gkey permissions  Show permission scopes for a key
  gkey rotate       Rotate (replace) a key with a fresh one
  gkey export       Export key(s) to JSON
  gkey import       Import key(s) from JSON

Run `gkey <subcommand> --help` for detailed options.
"""


def main(argv: list[str] | None = None) -> int:
    """Entry point for the `gkey` console script."""
    raw = list(sys.argv[1:] if argv is None else argv)

    if not raw or raw[0] in ("-h", "--help"):
        if _HAS_RICH:
            from rich.console import Console
            from rich.panel import Panel
            from rich.table import Table
            from rich.text import Text
            console = Console()
            title = Text("gkey", style="bold cyan")
            title.append(" — Gatekeeper + Keymaster unified CLI", style="dim")
            t = Table(show_header=True, header_style="bold magenta", border_style="cyan")
            t.add_column("Command")
            t.add_column("Description")
            cmds = [
                ("create", "Generate a new T1 API key"),
                ("revoke", "Revoke an existing key"),
                ("list", "List all keys; `list id <key-id>` for detail"),
                ("stats", "Show usage statistics and access logs"),
                ("quota", "View or set rate-limit quotas"),
                ("permissions", "Show permission scopes for a key"),
                ("rotate", "Rotate (replace) a key with a fresh one"),
                ("export", "Export key(s) to a JSON file"),
                ("import", "Import key(s) from a JSON file"),
            ]
            for cmd, desc in cmds:
                t.add_row(f"[green]{cmd}[/green]", desc)
            console.print(Panel.fit(title))
            console.print(t)
            console.print("\n[dim]Run `gkey <subcommand> --help` for detailed options.[/dim]")
        else:
            print(_USAGE)
        return 0

    if raw[0] in ("-V", "--version"):
        from . import __version__
        print(f"gkey (hypernix {__version__})")
        return 0

    cmd, rest = raw[0], raw[1:]

    # `gkey list id <key-id>` — detect and reroute
    if cmd == "list" and rest and rest[0] == "id":
        return _cmd_list_id(rest[1:])

    dispatch = {
        "create": _cmd_create,
        "revoke": _cmd_revoke,
        "list": _cmd_list,
        "stats": _cmd_stats,
        "quota": _cmd_quota,
        "permissions": _cmd_permissions,
        "rotate": _cmd_rotate,
        "export": _cmd_export,
        "import": _cmd_import,
    }

    if cmd not in dispatch:
        print(f"Unknown subcommand: {cmd!r}\n", file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        return 1

    try:
        return dispatch[cmd](rest)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    except Exception as exc:  # noqa: BLE001
        print(f"[gkey {cmd}] Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
