"""Key identity from a configuration source — ``gkey create -Con``.

A fleet does not want every key's V1 Server ID and SSPKID typed in by
hand at each machine. ``-Con`` points ``gkey create`` at a JSONL config
and takes the identity from there:

    gkey create -v v2 -Con https://config.example/keys.jsonl
    gkey create -Con 10.0.0.5              # → http://10.0.0.5/gkey.jsonl
    gkey create -Con ./fleet.jsonl

Why JSONL and not JSON
----------------------
Because the natural shape of this file is a log, not a document. A fleet
config gets appended to — a server is added, an index is reserved — and
an append-only file can be edited by two people without a merge. Lines
are applied in order and a later line overrides an earlier one for the
same field, so "the current setting" is the last thing anyone wrote.

A malformed line is skipped, not fatal. A config stream with one bad
line in the middle should still yield the settings around it; refusing
the whole file would make a stray character in an old entry break every
future key.

What it can set
---------------
``server_id``   The V1 Server ID a key belongs to (``00042-C1``).
``sspkid``      That key's identity on it (``00042-C1#3``), or
``sspkid_index``  an index to build one from, with ``server_id``.

Nothing else. A config source is a place someone else can write, so it
can move a key's identity and it cannot touch scopes, expiry, type or
access level — the things that decide what a key may do stay with the
operator running the command.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

__all__ = [
    "KeyConfig",
    "KeyConfigError",
    "DEFAULT_CONFIG_PATH",
    "MAX_CONFIG_BYTES",
    "load_key_config",
    "resolve_config_source",
]

#: What a bare IP or host gets appended to it.
DEFAULT_CONFIG_PATH = "/gkey.jsonl"

#: A config file is a handful of lines. Anything larger is either a
#: mistake or someone pointing this at a log, and reading it into memory
#: to find out is how a CLI gets killed by the OOM killer.
MAX_CONFIG_BYTES = 1 << 20  # 1 MiB

#: Only the fields that name a key's identity. Everything that decides
#: what a key may *do* stays with the operator running the command — a
#: config source is somewhere else, and possibly someone else.
_ACCEPTED_FIELDS = ("server_id", "sspkid", "sspkid_index")


class KeyConfigError(ValueError):
    """The config could not be read, or says something impossible."""


@dataclass(frozen=True)
class KeyConfig:
    """Identity settings resolved from a config source."""

    server_id: str = ""
    sspkid: str = ""
    sspkid_index: int | None = None
    source: str = ""
    lines_read: int = 0
    lines_skipped: int = 0

    @property
    def is_empty(self) -> bool:
        return not (self.server_id or self.sspkid or self.sspkid_index)

    def describe(self) -> str:
        parts = []
        if self.server_id:
            parts.append(f"server_id={self.server_id}")
        if self.sspkid:
            parts.append(f"sspkid={self.sspkid}")
        elif self.sspkid_index is not None:
            parts.append(f"sspkid_index={self.sspkid_index}")
        return ", ".join(parts) or "nothing"


def _is_windows_path(source: str) -> bool:
    """``C:\\keys\\gkey.jsonl`` or ``C:/keys/gkey.jsonl``.

    A drive letter is the one local path that reads as something else to
    both halves of this module: as ``host:port`` to the bare-host guess
    below, and as the URL scheme ``c`` to :func:`urlparse`. Neither is
    recoverable after the fact, so it is settled here once.
    """
    return len(source) > 1 and source[0].isalpha() and source[1] == ":"


def _looks_like_bare_host(source: str) -> bool:
    """An IP or host with no scheme and no path.

    ``10.0.0.5``, ``10.0.0.5:8080`` and ``config.example`` are hosts;
    ``./x.jsonl`` and ``/etc/x.jsonl`` are paths, and a Windows drive
    letter (``C:\\x``) is a path that superficially reads as host:port.
    """
    if "://" in source or source.startswith((".", "/", "~")):
        return False
    if _is_windows_path(source):
        return False
    host = source.split("/", 1)[0].split(":", 1)[0]
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    # A hostname needs a dot to be one; a bare word is a relative path.
    return "." in host and not source.endswith((".jsonl", ".json", ".txt"))


def resolve_config_source(source: str) -> str:
    """Turn what the operator typed into something fetchable.

    A bare IP or host becomes ``http://<host>/gkey.jsonl`` — plain HTTP
    because the case this exists for is a machine on a tailnet or a LAN,
    where there is no certificate to verify against and demanding https
    would just mean everyone passes ``-k`` to something.
    """
    source = source.strip()
    if not source:
        raise KeyConfigError("-Con needs an address, URL, or path.")
    if _looks_like_bare_host(source):
        return f"http://{source.rstrip('/')}{DEFAULT_CONFIG_PATH}"
    return source


def _read_source(resolved: str) -> str:
    parsed = urlparse(resolved)
    # urlparse calls the drive letter of ``C:\\keys\\gkey.jsonl`` a scheme
    # named "c", so on Windows every local path would be rejected as an
    # unsupported scheme rather than read.
    scheme = "" if _is_windows_path(resolved) else parsed.scheme
    if scheme in ("http", "https"):
        # Private and loopback addresses are the *point* here — this is a
        # fleet tool for a tailnet — so the SSRF guard runs with
        # allow_private, which still blocks the cloud-metadata endpoints
        # that are never a legitimate config source.
        try:
            from ..t1api.security import validate_remote_address

            validate_remote_address(resolved, allow_private=True)
        except ImportError:      # pragma: no cover - t1api extra absent
            pass
        except Exception as exc:
            raise KeyConfigError(f"Refusing to fetch {resolved}: {exc}") from exc

        request = urllib.request.Request(
            resolved, headers={"Accept": "application/jsonl, text/plain"}
        )
        try:
            # No proxy: the address is usually on the same tailnet, and a
            # proxy in between turns a reachable host into a timeout.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=15) as response:
                raw = response.read(MAX_CONFIG_BYTES + 1)
        except Exception as exc:
            raise KeyConfigError(f"Could not fetch {resolved}: {exc}") from exc
    elif scheme in ("", "file"):
        path = Path(parsed.path if scheme == "file" else resolved).expanduser()
        if not path.exists():
            raise KeyConfigError(f"No config at {path}")
        try:
            raw = path.read_bytes()[: MAX_CONFIG_BYTES + 1]
        except OSError as exc:
            raise KeyConfigError(f"Could not read {path}: {exc}") from exc
    else:
        raise KeyConfigError(
            f"Unsupported source scheme {scheme!r}; use http, https, or a path."
        )

    if len(raw) > MAX_CONFIG_BYTES:
        raise KeyConfigError(
            f"Config at {resolved} is larger than {MAX_CONFIG_BYTES} bytes. "
            "That is a log, not a config."
        )
    return raw.decode("utf-8", errors="replace")


def load_key_config(source: str) -> KeyConfig:
    """Read *source* and resolve it to one :class:`KeyConfig`.

    Later lines win. A line that is blank, a ``#`` comment, not an
    object, or not valid JSON is counted and skipped — one bad entry in
    an append-only file must not break every key minted after it.
    """
    resolved = resolve_config_source(source)
    text = _read_source(resolved)

    values: dict[str, object] = {}
    read = 0
    skipped = 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        read += 1
        try:
            record = json.loads(line)
        except ValueError:
            skipped += 1
            continue
        if not isinstance(record, dict):
            skipped += 1
            continue
        for field_name in _ACCEPTED_FIELDS:
            if field_name in record and record[field_name] not in (None, ""):
                values[field_name] = record[field_name]

    index = values.get("sspkid_index")
    if index is not None:
        try:
            index = int(index)
        except (TypeError, ValueError) as exc:
            raise KeyConfigError(
                f"sspkid_index must be a whole number, got {index!r}"
            ) from exc
        if index < 1:
            raise KeyConfigError(f"sspkid_index starts at 1, got {index}")

    server_id = str(values.get("server_id") or "")
    sspkid = str(values.get("sspkid") or "")
    if index is not None and not sspkid and not server_id:
        raise KeyConfigError(
            "sspkid_index needs a server_id to build an SSPKID from — an index "
            "on its own does not say which server it indexes."
        )

    config = KeyConfig(
        server_id=server_id,
        sspkid=sspkid,
        sspkid_index=index,
        source=resolved,
        lines_read=read,
        lines_skipped=skipped,
    )
    if config.is_empty:
        raise KeyConfigError(
            f"{resolved} set none of {', '.join(_ACCEPTED_FIELDS)}. "
            f"Read {read} line(s), skipped {skipped} as unparseable."
        )
    return config
