"""t1api.transport — remote multi-server deployment: real byte transport.

Beta 2's module "sync" was bookkeeping: it trust-gated a target server
and recorded that a sync happened, moving no bytes, and said so plainly
in its own docstring. Beta 3 makes it real, which means confronting the
part that made it worth deferring — moving bytes between machines is the
single most dangerous thing this API does, and the spec's security
section is unusually specific about it:

  Prevent SSRF. Prevent arbitrary remote code execution through module
  upload/deployment. Verify remote server trust before remote uploads.
  Validate remote URLs before fetching.

So the transport is built around four rules, each enforced in code
rather than documented as an expectation:

1. **The target must already be trusted.** A push goes only to a server
   the operator promoted to ``trusted``/``local`` — never to an address
   supplied in the request. The caller names a *server_id*; the address
   comes from the registry. There is no code path that pushes to a URL
   a client provided.

2. **Every transfer is authenticated and integrity-checked.** Pushes
   carry an HMAC-SHA256 signature over ``method|path|timestamp|
   body-digest`` using the shared deployment secret, plus the expected
   SHA-256 of the payload. The receiver recomputes both. A signature
   that's missing, stale (outside :data:`SIGNATURE_MAX_SKEW_SECONDS`),
   or wrong is rejected before the body is stored.

3. **Bytes are never executed, imported, or interpreted.** Not on the
   sending side, not on the receiving side. A module is an opaque blob
   with a checksum. That is the whole answer to "prevent arbitrary
   remote code execution through module upload/deployment": there is no
   deserialization step to attack, because there is no deserialization.

4. **Fetches are bounded and pinned.** Remote-source fetches re-validate
   the URL against the SSRF guard, refuse to follow redirects (a
   redirect is the classic way to turn a validated public URL into an
   internal one *after* the check), cap the response size, and stream to
   disk rather than into memory.

Transport is stdlib ``urllib`` — the same choice, for the same reason,
as :mod:`hypernix.waiter.client`: no new runtime dependency for a
feature that only needs HTTP.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import T1APIError, T1ErrorCode
from .security import validate_remote_address

logger = logging.getLogger(__name__)

# A signed request older (or newer) than this is refused. Replaying a
# capture is then bounded to a short window rather than being valid
# forever, and a badly-skewed clock produces a clear error instead of
# silent, intermittent auth failures.
SIGNATURE_MAX_SKEW_SECONDS = 300.0

HEADER_SIGNATURE = "X-T1-Signature"
HEADER_TIMESTAMP = "X-T1-Timestamp"
HEADER_CHECKSUM = "X-T1-Content-SHA256"
HEADER_MODULE_ID = "X-T1-Module-ID"

# Hard ceiling regardless of configuration. A deployment can lower the
# cap; it cannot raise it past this without editing the source, which is
# the point — an accidental `max_bytes=10**12` in a config file should
# not be able to fill a disk.
ABSOLUTE_MAX_TRANSFER_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB


def compute_signature(secret: str, *, method: str, path: str, timestamp: str, body_digest: str) -> str:
    """HMAC-SHA256 over the canonical request string.

    The method and path are inside the signature so a body signed for
    ``POST /modules/receive`` can't be replayed against a different
    endpoint.
    """
    canonical = f"{method.upper()}|{path}|{timestamp}|{body_digest}"
    return hmac.new(secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_signature(
    secret: str,
    *,
    method: str,
    path: str,
    timestamp: str,
    body: bytes,
    signature: str,
    now: float | None = None,
) -> None:
    """Verify an inbound signed transfer, or raise.

    Checks the timestamp window first: an expired signature is rejected
    without doing the HMAC comparison at all, and a valid HMAC over a
    stale timestamp still fails.
    """
    if not secret:
        raise T1APIError(
            T1ErrorCode.AUTH_MISSING_CREDENTIALS,
            "This server has no deployment secret configured, so it cannot accept module "
            "transfers. Set T1_DEPLOY_SECRET on both ends.",
            http_status=403,
        )
    if not signature or not timestamp:
        raise T1APIError(
            T1ErrorCode.AUTH_MISSING_CREDENTIALS,
            "Module transfer requires the X-T1-Signature and X-T1-Timestamp headers.",
            http_status=401,
        )
    try:
        sent_at = float(timestamp)
    except ValueError as exc:
        raise T1APIError(
            T1ErrorCode.AUTH_INVALID_TOKEN, "Malformed X-T1-Timestamp header.", http_status=401
        ) from exc
    current = time.time() if now is None else now
    if abs(current - sent_at) > SIGNATURE_MAX_SKEW_SECONDS:
        raise T1APIError(
            T1ErrorCode.AUTH_EXPIRED_TOKEN,
            f"Transfer signature is outside the {SIGNATURE_MAX_SKEW_SECONDS:g}s freshness window "
            "(replay protection). Check clock synchronisation between the two servers.",
            http_status=401,
        )
    expected = compute_signature(
        secret,
        method=method,
        path=path,
        timestamp=timestamp,
        body_digest=hashlib.sha256(body).hexdigest(),
    )
    if not hmac.compare_digest(expected, signature):
        raise T1APIError(
            T1ErrorCode.AUTH_INVALID_TOKEN,
            "Transfer signature mismatch — the payload, path, or shared secret differs.",
            http_status=401,
        )


@dataclass
class TransferResult:
    """Outcome of one push or fetch."""

    ok: bool
    bytes_transferred: int
    checksum: str
    target: str
    status_code: int | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "bytes_transferred": self.bytes_transferred,
            "checksum": self.checksum,
            "target": self.target,
            "status_code": self.status_code,
            "detail": self.detail,
        }


class ModuleTransport:
    """Pushes module blobs to trusted servers and fetches remote sources.

    Args:
        deploy_secret: Shared HMAC secret. Both ends of a deployment
            must hold the same value; without one, pushes are refused
            rather than sent unauthenticated.
        max_bytes: Per-transfer size cap, clamped to
            :data:`ABSOLUTE_MAX_TRANSFER_BYTES`.
        allow_private_targets: True for Tailscale/LAN deployments, where
            the target addresses are private *by design*. Mirrors the
            same explicit opt-in :mod:`t1api.security` requires.
        timeout: Per-request socket timeout.
        opener: Injection point for tests — anything with the
            ``urlopen(request, timeout=...)`` signature.
    """

    def __init__(
        self,
        *,
        deploy_secret: str = "",
        max_bytes: int = 256 * 1024 * 1024,
        allow_private_targets: bool = False,
        timeout: float = 60.0,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.deploy_secret = deploy_secret
        self.max_bytes = min(int(max_bytes), ABSOLUTE_MAX_TRANSFER_BYTES)
        self.allow_private_targets = allow_private_targets
        self.timeout = timeout
        self._urlopen = opener or urllib.request.urlopen

    # ------------------------------------------------------------------
    # Push: this server → a trusted remote server
    # ------------------------------------------------------------------

    def push_module(
        self,
        *,
        server_address: str,
        module_id: str,
        content: bytes,
        metadata: dict[str, Any] | None = None,
        path: str = "/modules/receive",
    ) -> TransferResult:
        """Push one module blob to *server_address*.

        The address must come from the server registry (the caller is
        expected to have called ``ServerRegistry.require_trusted`` first
        — :class:`DeploymentCoordinator` does exactly that). It is
        re-validated here anyway: a registry row could have been written
        before a policy tightened, and the cost of checking twice is
        nothing compared to the cost of being wrong once.
        """
        if not self.deploy_secret:
            raise T1APIError(
                T1ErrorCode.AUTH_MISSING_CREDENTIALS,
                "Remote deployment requires T1_DEPLOY_SECRET to be set on this server "
                "(and the same value on the target). Refusing to push unauthenticated bytes.",
                http_status=403,
            )
        if len(content) > self.max_bytes:
            raise T1APIError(
                T1ErrorCode.PAYLOAD_TOO_LARGE,
                f"Module is {len(content)} bytes, over this server's {self.max_bytes}-byte "
                "transfer cap (T1_MAX_TRANSFER_BYTES).",
                details={"size_bytes": len(content), "max_bytes": self.max_bytes},
                http_status=413,
            )
        validate_remote_address(server_address, allow_private=self.allow_private_targets)

        checksum = hashlib.sha256(content).hexdigest()
        timestamp = f"{time.time():.3f}"
        url = server_address.rstrip("/") + path
        signature = compute_signature(
            self.deploy_secret,
            method="POST",
            path=path,
            timestamp=timestamp,
            body_digest=checksum,
        )
        headers = {
            "Content-Type": "application/octet-stream",
            HEADER_SIGNATURE: signature,
            HEADER_TIMESTAMP: timestamp,
            HEADER_CHECKSUM: checksum,
            HEADER_MODULE_ID: module_id,
        }
        if metadata:
            # Metadata rides in a header as compact JSON so the body stays
            # exactly the bytes the checksum covers — mixing metadata into
            # the body would mean the checksum no longer describes the
            # module itself.
            headers["X-T1-Module-Metadata"] = json.dumps(metadata, separators=(",", ":"))[:4096]

        request = urllib.request.Request(url, data=content, headers=headers, method="POST")
        try:
            with self._urlopen(request, timeout=self.timeout) as response:
                status = getattr(response, "status", None) or response.getcode()
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = _safe_error_detail(exc)
            raise T1APIError(
                T1ErrorCode.TRANSPORT_FAILED,
                f"Target server rejected the module transfer (HTTP {exc.code}): {detail}",
                details={"status_code": exc.code, "target": _redact(url)},
                http_status=502,
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise T1APIError(
                T1ErrorCode.TRANSPORT_FAILED,
                f"Could not reach the target server: {exc}",
                details={"target": _redact(url)},
                http_status=502,
            ) from exc

        # The receiver echoes back what it stored. If its digest differs
        # from ours the bytes changed in flight and the deployment is a
        # failure, however cheerful the status code was.
        remote_checksum = _extract_checksum(body)
        if remote_checksum and remote_checksum != checksum:
            raise T1APIError(
                T1ErrorCode.CHECKSUM_MISMATCH,
                "Target server stored a different digest than we sent — transfer corrupted.",
                details={"expected": checksum, "received": remote_checksum},
                http_status=502,
            )
        return TransferResult(
            ok=True,
            bytes_transferred=len(content),
            checksum=checksum,
            target=_redact(url),
            status_code=status,
            detail="delivered",
        )

    # ------------------------------------------------------------------
    # Fetch: a validated remote source → this server
    # ------------------------------------------------------------------

    def fetch_source(
        self,
        source_url: str,
        *,
        destination: Path,
        expected_checksum: str | None = None,
        allow_private: bool = False,
    ) -> TransferResult:
        """Fetch a registered remote source to *destination*.

        Streams in chunks with a running size check, so an oversized
        response is abandoned mid-download rather than after it has
        already been buffered. Redirects are refused outright — see the
        module docstring for why following one would undo the URL
        validation that just passed.
        """
        validate_remote_address(source_url, allow_private=allow_private)
        request = urllib.request.Request(source_url, method="GET", headers={"Accept": "*/*"})
        opener = urllib.request.build_opener(_NoRedirect)
        urlopen = self._urlopen if self._urlopen is not urllib.request.urlopen else opener.open

        digest = hashlib.sha256()
        written = 0
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = destination.with_suffix(destination.suffix + ".part")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = getattr(response, "status", None) or response.getcode()
                declared = response.headers.get("Content-Length") if hasattr(response, "headers") else None
                if declared and int(declared) > self.max_bytes:
                    raise T1APIError(
                        T1ErrorCode.PAYLOAD_TOO_LARGE,
                        f"Remote source declares {declared} bytes, over the "
                        f"{self.max_bytes}-byte cap.",
                        http_status=413,
                    )
                with tmp_path.open("wb") as handle:
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > self.max_bytes:
                            raise T1APIError(
                                T1ErrorCode.PAYLOAD_TOO_LARGE,
                                f"Remote source exceeded the {self.max_bytes}-byte cap mid-download.",
                                http_status=413,
                            )
                        digest.update(chunk)
                        handle.write(chunk)
        except T1APIError:
            tmp_path.unlink(missing_ok=True)
            raise
        except urllib.error.HTTPError as exc:
            tmp_path.unlink(missing_ok=True)
            raise T1APIError(
                T1ErrorCode.TRANSPORT_FAILED,
                f"Remote source returned HTTP {exc.code}.",
                details={"status_code": exc.code},
                http_status=502,
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            tmp_path.unlink(missing_ok=True)
            raise T1APIError(
                T1ErrorCode.TRANSPORT_FAILED,
                f"Could not fetch the remote source: {exc}",
                http_status=502,
            ) from exc

        checksum = digest.hexdigest()
        if expected_checksum and checksum != expected_checksum:
            tmp_path.unlink(missing_ok=True)
            raise T1APIError(
                T1ErrorCode.CHECKSUM_MISMATCH,
                "Fetched content does not match the expected SHA-256.",
                details={"expected": expected_checksum, "actual": checksum},
                http_status=502,
            )
        tmp_path.replace(destination)
        return TransferResult(
            ok=True,
            bytes_transferred=written,
            checksum=checksum,
            target=_redact(source_url),
            status_code=status,
            detail="fetched",
        )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Turns any redirect into an error.

    Following a redirect after validating the original URL is how an
    SSRF check gets bypassed: the first hop passes validation, the second
    goes wherever the attacker wants. Registering a new source URL is
    cheap; silently following one is not.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102, ANN001
        raise T1APIError(
            T1ErrorCode.SSRF_BLOCKED,
            f"Remote source redirected to {_redact(newurl)}; redirects are not followed. "
            "Register the final URL directly if it is the one you intend to fetch.",
            details={"status_code": code},
            http_status=400,
        )


def _redact(url: str) -> str:
    """Strip any userinfo and query string before a URL reaches a log or
    an error message — either can carry a credential."""
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(url)
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))


def _safe_error_detail(exc: urllib.error.HTTPError, limit: int = 300) -> str:
    """A remote error body, truncated. Never assumed to be JSON, never
    echoed at full length — it's attacker-influenced text."""
    try:
        raw = exc.read()
    except Exception:  # noqa: BLE001
        return exc.reason if isinstance(exc.reason, str) else "no detail"
    text = raw.decode("utf-8", errors="replace").strip()
    return text[:limit] if text else (exc.reason if isinstance(exc.reason, str) else "no detail")


def _extract_checksum(body: bytes) -> str | None:
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return None
    if isinstance(payload, dict):
        value = payload.get("checksum") or payload.get("module", {}).get("checksum")
        return value if isinstance(value, str) else None
    return None


__all__ = [
    "ABSOLUTE_MAX_TRANSFER_BYTES",
    "HEADER_CHECKSUM",
    "HEADER_MODULE_ID",
    "HEADER_SIGNATURE",
    "HEADER_TIMESTAMP",
    "ModuleTransport",
    "SIGNATURE_MAX_SKEW_SECONDS",
    "TransferResult",
    "compute_signature",
    "verify_signature",
]
