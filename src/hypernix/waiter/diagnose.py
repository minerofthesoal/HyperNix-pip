"""Why a connection to a T1 server failed, and what to do about it.

``Could not reach http://127.0.0.1:1234/hyperlink/pair: [Errno 111]
Connection refused`` is accurate and nearly useless. It names the address
and the errno and stops there, leaving three questions unanswered: is
anything listening at all, is *this* the address I meant, and what do I
type next.

That last one matters most, because the common causes have different
fixes and the message cannot tell them apart:

* the server is not running        -> start it
* the address is stale             -> re-point waiter
* the port belongs to something else (LM Studio's 1234, Ollama's 11434)
                                   -> that is a bridge target, not a T1 server

So this probes: does the TCP port accept a connection, and if it does,
does whatever answers look like a T1 API? Both probes are short and
best-effort — a diagnostic that hangs is worse than one that says less.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import urlsplit

__all__ = [
    "PortUse",
    "WELL_KNOWN_PORTS",
    "ConnectionDiagnosis",
    "diagnose",
    "format_diagnosis",
]

#: How long either probe may take. The operator is already waiting on a
#: command that failed; spending seconds to explain why is its own
#: annoyance.
PROBE_TIMEOUT = 1.0


@dataclass(frozen=True)
class PortUse:
    """A port that commonly belongs to something other than a T1 API."""

    port: int
    software: str
    note: str


#: Ports someone plausibly types by mistake when they meant the T1 API.
#: 1234 is the one that prompted this: it is LM Studio's default, and
#: `waiter lmstudio` legitimately talks to it — but it is a *bridge
#: target*, reached through the T1 server, never the T1 server itself.
WELL_KNOWN_PORTS: tuple[PortUse, ...] = (
    PortUse(1234, "LM Studio", "`waiter lmstudio` reaches it through the T1 server, not directly."),
    PortUse(11434, "Ollama", "Configure it on the server as a model source; waiter talks to the server."),
    PortUse(5432, "PostgreSQL", "That is the T1 API's database, not its HTTP port."),
    PortUse(6379, "Redis", ""),
    PortUse(3000, "a web dev server", ""),
)

#: The T1 API's own default, and what run_local.sh / install-t1.sh use.
T1_DEFAULT_PORT = 8000


@dataclass
class ConnectionDiagnosis:
    url: str
    host: str = ""
    port: int | None = None
    #: Where the address came from, phrased for the reader ("the saved
    #: config", "-I on the command line"). Knowing this is often the
    #: whole answer.
    source: str = ""
    reason: str = ""
    port_open: bool | None = None
    #: Set when something answers but is not a T1 API.
    responder: str = ""
    known_use: PortUse | None = None
    suggestions: list[str] = field(default_factory=list)

    @property
    def nothing_listening(self) -> bool:
        return self.port_open is False


def _split(url: str) -> tuple[str, int | None, str]:
    """Host, port and scheme, never raising.

    ``SplitResult.port`` raises ValueError on an out-of-range port, and
    ``urlsplit`` itself can raise on a malformed authority. This module
    only ever runs when something has *already* failed, so an exception
    here would replace a real error with a worse one.
    """
    try:
        parts = urlsplit(url)
        scheme = parts.scheme or "http"
        host = parts.hostname or ""
    except ValueError:
        return "", None, "http"
    try:
        port = parts.port
    except ValueError:
        # A port outside 0-65535 is itself worth reporting, but there is
        # no number to probe.
        return host, None, scheme
    if port is None:
        port = 443 if scheme == "https" else 80
    return host, port, scheme


def _port_accepts(host: str, port: int, timeout: float) -> bool:
    """Does anything accept a TCP connection here?

    Distinguishes "nothing is running" from "something is running and
    refused to answer as a T1 API", which have completely different fixes.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


#: Diagnostics talk to one named host and ask "is *this* up". A proxy in
#: between answers a different question — and an environment with
#: HTTP_PROXY set but no no_proxy for localhost (containers do this
#: routinely) would have every local probe fail through the proxy and be
#: reported as the server being down. So these requests are built with
#: proxies explicitly disabled. Ordinary API traffic is unaffected: it
#: goes through the SDK's transport, which honours the environment.
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get_json(url: str, *, timeout: float = PROBE_TIMEOUT) -> dict | None:
    """GET *url* and parse a JSON object, or None. Never raises."""
    try:
        request = urllib.request.Request(
            url, headers={"Accept": "application/json", "User-Agent": "waiter-diagnose"}
        )
        with _NO_PROXY.open(request, timeout=timeout) as response:
            data = json.loads(response.read(8192).decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return None
    return data if isinstance(data, dict) else None


def _identify(url: str, timeout: float) -> str:
    """Ask whatever is listening what it is, without believing it.

    Only used to sharpen the message. Any answer is a hint for a human,
    never an input to a decision — so a hostile responder can mislead the
    text of an error and nothing else.
    """
    parts = urlsplit(url)
    base = f"{parts.scheme or 'http'}://{parts.netloc}"
    # A definite identification wins over the vague one. An HTTP error is
    # only ever the fallback: a 404 on /status proves an HTTP server is
    # there and proves nothing about what it is, so it must not stop the
    # probe before /v1/models gets its turn — which is exactly what
    # distinguishes "LM Studio" from "some web server".
    fallback = ""
    for path, label in (
        ("/health", "T1"),
        ("/status", "T1"),
        ("/v1/models", "OpenAI-compatible"),
        ("/", ""),
    ):
        try:
            request = urllib.request.Request(
                base + path, headers={"Accept": "application/json", "User-Agent": "waiter-diagnose"}
            )
            with _NO_PROXY.open(request, timeout=timeout) as response:
                body = response.read(2048).decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            fallback = fallback or f"an HTTP server (it answered {exc.code} on {path})"
            continue
        except OSError:
            continue
        if label == "T1":
            try:
                data = json.loads(body)
            except ValueError:
                continue
            if isinstance(data, dict) and (
                "t1_version" in data or "t1_api_version" in data or "server_name" in data
            ):
                return "a T1 API server"
            continue
        if label == "OpenAI-compatible" and '"data"' in body:
            return "an OpenAI-compatible API (LM Studio, Ollama, vLLM or similar)"
        if body:
            fallback = fallback or "an HTTP server of some kind"
    return fallback


def diagnose(
    url: str,
    reason: str = "",
    *,
    source: str = "",
    timeout: float = PROBE_TIMEOUT,
    probe: bool = True,
) -> ConnectionDiagnosis:
    """Work out why *url* could not be reached.

    ``probe=False`` skips the network entirely, for callers that only want
    the static advice (and for tests that must not touch the network).
    """
    host, port, _ = _split(url)
    result = ConnectionDiagnosis(url=url, host=host, port=port, source=source, reason=reason)

    if port is not None:
        result.known_use = next((use for use in WELL_KNOWN_PORTS if use.port == port), None)

    if probe and host:
        result.port_open = _port_accepts(host, port, timeout) if port else None
        if result.port_open:
            result.responder = _identify(url, timeout)

    result.suggestions = _suggestions(result)
    return result


def _suggestions(result: ConnectionDiagnosis) -> list[str]:
    """Concrete next commands, most likely first."""
    out: list[str] = []

    if result.known_use is not None and result.port != T1_DEFAULT_PORT:
        out.append(
            f"Port {result.port} is {result.known_use.software}'s default, not the T1 API's "
            f"({T1_DEFAULT_PORT})."
        )
        if result.known_use.note:
            out.append(f"  {result.known_use.note}")
        out.append(
            f"  If you meant the T1 API:  waiter serv -A -I http://{result.host}:{T1_DEFAULT_PORT} -K <key>"
        )
        return out

    if result.nothing_listening:
        out.append(f"Nothing is listening on {result.host}:{result.port}.")
        out.append("  Start the server:        ./examples/t1api/run_local.sh")
        out.append("  or, if you installed it: ~/.hypernix/t1api/start-t1.sh")
        out.append("  Then re-run this command.")
        return out

    if result.responder and "T1 API" not in result.responder:
        out.append(
            f"Something is listening on {result.host}:{result.port}, but it looks like "
            f"{result.responder} rather than a T1 API."
        )
        out.append("  Point waiter at the right address:  waiter serv -A -I <server> -K <key>")
        return out

    out.append(f"Could not reach {result.host}:{result.port}.")
    out.append("  Check the address:  waiter config")
    out.append("  Re-point waiter:    waiter serv -A -I <server> -K <key>")
    return out


def format_diagnosis(result: ConnectionDiagnosis) -> str:
    """The whole explanation, as plain text ready for stderr."""
    lines: list[str] = []
    head = f"Could not reach {result.url}"
    if result.reason:
        head += f" ({result.reason})"
    lines.append(head)
    if result.source:
        lines.append(f"  Address from: {result.source}")
    lines.append("")
    lines.extend(result.suggestions)
    return "\n".join(lines)
