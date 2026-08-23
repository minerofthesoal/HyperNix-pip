"""hyperlink.discovery — "what addresses can my phone actually reach me on?"

The PC is the one machine that knows all its own addresses, and the
phone is the one that has to pick. So the PC enumerates and ranks; the
phone tries them in order and keeps the first that answers. That split
is why this module exists at all — the alternative is asking the user to
know their own LAN IP, which they do not, and which changes.

The ranking, best first:

1. **Tailscale DNS name** (``desktop.tailnet.ts.net``) — works from
   anywhere, survives the laptop moving between networks, and is stable
   across DHCP leases. Slower than LAN on the same network, but correct
   on every network, and correctness beats a few milliseconds when the
   alternative is "the app stops working when you leave the house".
2. **Tailscale IP** (``100.x.y.z``) — same reachability, no DNS
   dependency. The fallback for when MagicDNS is off.
3. **LAN address** (``192.168.x.y``) — fastest at home, useless
   elsewhere.
4. **Loopback** — only useful to something on this machine, but that
   includes the simulator, which is where the iOS app is first run.

Ordering is a preference, not a promise: the app probes and takes what
answers, because a Tailscale name is worthless when Tailscale is not
running on the phone, and this module cannot know that.
"""
from __future__ import annotations

import ipaddress
import json
import os
import shutil
import socket
import subprocess
from dataclasses import dataclass
from typing import Any

__all__ = ["Endpoint", "local_endpoints", "tailscale_self", "lan_addresses", "advertise"]


@dataclass(frozen=True)
class Endpoint:
    url: str
    kind: str          # tailscale-dns | tailscale-ip | lan | loopback | configured
    priority: int
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"url": self.url, "kind": self.kind, "priority": self.priority, "note": self.note}


def _tailscale_binary() -> str:
    found = shutil.which("tailscale")
    if found:
        return found
    mac = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
    return mac if os.path.exists(mac) else ""


def tailscale_self(*, timeout: float = 4.0) -> tuple[str, list[str]]:
    """``(dns_name, ipv4_addresses)`` for *this* node, or ``("", [])``.

    Never raises. Tailscale not being installed is the common case, and
    a missing optional network is not an error condition for a server
    that also works perfectly well on a LAN.
    """
    exe = _tailscale_binary()
    if not exe:
        return "", []
    try:
        proc = subprocess.run(  # noqa: S603
            [exe, "status", "--json"], capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return "", []
    if proc.returncode != 0 or not proc.stdout.strip():
        return "", []
    try:
        status = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return "", []
    myself = status.get("Self")
    if not isinstance(myself, dict):
        return "", []
    dns = str(myself.get("DNSName") or "").rstrip(".")
    ips = [
        addr
        for addr in (myself.get("TailscaleIPs") or [])
        if isinstance(addr, str) and ":" not in addr
    ]
    return dns, ips


def lan_addresses() -> list[str]:
    """Private IPv4 addresses this host answers on.

    Found by opening a UDP socket toward a public address and asking
    which local address the kernel picked. No packet is sent — UDP
    ``connect`` only sets the socket's peer — so this works with no
    network traffic and no DNS, and it picks the interface that actually
    routes rather than the first one ``getaddrinfo`` happens to name.
    """
    found: list[str] = []
    for probe in ("8.8.8.8", "1.1.1.1"):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((probe, 80))
            addr = sock.getsockname()[0]
        except OSError:
            continue
        finally:
            sock.close()
        if addr and addr not in found and _is_private(addr):
            found.append(addr)

    # Also take whatever the hostname resolves to: on a machine with
    # several interfaces the route probe finds one, and the phone may be
    # on the other.
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addr = info[4][0]
            if _is_private(addr) and addr not in found and not addr.startswith("127."):
                found.append(addr)
    except (OSError, socket.gaierror):
        pass
    return found


def _is_private(addr: str) -> bool:
    try:
        parsed = ipaddress.ip_address(addr)
    except ValueError:
        return False
    # Tailscale's 100.64/10 CGNAT range is "private" to ipaddress but is
    # reported separately as a tailscale endpoint, so exclude it here to
    # avoid the same address appearing twice with different labels.
    if parsed in ipaddress.ip_network("100.64.0.0/10"):
        return False
    return parsed.is_private and not parsed.is_loopback


def local_endpoints(
    *,
    port: int = 8000,
    scheme: str = "http",
    include_loopback: bool = True,
    configured: str = "",
    check_tailscale: bool = True,
) -> list[Endpoint]:
    """Every address a client could try, best first.

    ``configured`` is an explicit public URL (a reverse proxy, a
    Cloudflare tunnel) and always ranks first when set: an operator who
    has told us the address knows better than any probe.
    """
    endpoints: list[Endpoint] = []
    if configured:
        endpoints.append(
            Endpoint(configured.rstrip("/"), "configured", 0, "T1_HYPERLINK_PUBLIC_URL")
        )
    if check_tailscale:
        dns, ips = tailscale_self()
        if dns:
            endpoints.append(
                Endpoint(f"{scheme}://{dns}:{port}", "tailscale-dns", 1, "works off the LAN")
            )
        for ip in ips:
            endpoints.append(
                Endpoint(f"{scheme}://{ip}:{port}", "tailscale-ip", 2, "works off the LAN")
            )
    for addr in lan_addresses():
        endpoints.append(Endpoint(f"{scheme}://{addr}:{port}", "lan", 3, "same network only"))
    if include_loopback:
        endpoints.append(
            Endpoint(f"{scheme}://127.0.0.1:{port}", "loopback", 4, "this machine / simulator")
        )

    seen: set[str] = set()
    unique = [e for e in endpoints if not (e.url in seen or seen.add(e.url))]
    return sorted(unique, key=lambda e: e.priority)


def advertise(
    *,
    port: int = 8000,
    scheme: str = "http",
    configured: str = "",
    server_name: str = "",
    t1_version: str = "",
) -> dict[str, Any]:
    """The payload ``GET /hyperlink/endpoints`` returns.

    ``tailscale`` is reported as a plain boolean so the app can say
    "install Tailscale to use this away from home" rather than leaving
    the user to work out why it only works in one room.
    """
    endpoints = local_endpoints(port=port, scheme=scheme, configured=configured)
    return {
        "server_name": server_name or socket.gethostname(),
        "t1_version": t1_version,
        "endpoints": [e.to_dict() for e in endpoints],
        "tailscale": any(e.kind.startswith("tailscale") for e in endpoints),
        "reachable_off_lan": any(e.kind in ("tailscale-dns", "tailscale-ip", "configured") for e in endpoints),
    }
