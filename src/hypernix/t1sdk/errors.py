"""t1sdk.errors — the SDK's exception hierarchy.

Mapped one-to-one from the server's stable ``T1ErrorCode`` values, so an
SDK user can catch the *category* they care about
(:class:`T1AuthError`, :class:`T1QuotaError`) without matching on
strings, while :attr:`T1Error.code` keeps the exact server code available
for the cases where the distinction matters.

Every exception carries the server's ``request_id`` when there was one.
That is the single most useful thing to put in a bug report against a T1
deployment: it ties a client-side failure to the server's own audit and
log records.
"""
from __future__ import annotations

from typing import Any


class T1Error(Exception):
    """Base class for every SDK failure.

    Args:
        message: Human-readable summary, taken from the server when it
            sent one.
        code: The server's stable error code (``MODEL_NOT_SUPPORTED``,
            ``RATE_LIMITED``, ...), or None for transport-level failures
            where no server response was received.
        status: HTTP status, if a response arrived at all.
        request_id: The server's request id, when present.
        details: The server's structured ``error.details`` payload.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status: int | None = None,
        request_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.status = status
        self.request_id = request_id
        self.details = details or {}
        super().__init__(message)

    def __str__(self) -> str:
        base = super().__str__()
        parts = [base]
        if self.code:
            parts.append(f"[{self.code}]")
        if self.request_id:
            parts.append(f"(request_id={self.request_id})")
        return " ".join(parts)


class T1TransportError(T1Error):
    """The request never reached a T1 server, or its reply was unusable —
    DNS failure, connection refused, timeout, TLS failure, non-JSON body."""


class T1AuthError(T1Error):
    """Authentication or authorization was refused (401/403).

    Covers a bad key, an expired token, insufficient scope, a missing
    admin scope, a blocked IP, and a failed mTLS check — all cases where
    the answer is "not with these credentials", and none of which are
    worth retrying without changing something.
    """


class T1NotFoundError(T1Error):
    """The addressed resource does not exist (404), including
    ``MODEL_NOT_SUPPORTED`` — a model that isn't in the registry does not
    exist as far as this API is concerned."""


class T1ValidationError(T1Error):
    """The request was malformed or semantically invalid (400/409/422),
    including ``CONFIRMATION_REQUIRED`` for a destructive call that
    didn't confirm."""


class T1QuotaError(T1Error):
    """A limit was hit (429): rate limit, model quota exhaustion, or a
    fully-exhausted routing cascade.

    :attr:`retry_after` carries the server's ``Retry-After`` when it sent
    one, so a caller writing their own backoff doesn't have to guess.
    """

    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs: Any) -> None:
        self.retry_after = retry_after
        super().__init__(message, **kwargs)


class T1ServerError(T1Error):
    """The server failed (5xx). Usually worth retrying; the SDK already
    does, so seeing this means the retries were also exhausted."""


class T1NotSupportedError(T1Error):
    """The operation exists in the contract but this deployment can't
    perform it (501) — e.g. a HyperNix-pip capability the installed
    version doesn't have, or a job kind with no registered handler."""


# Server error code → exception class. Codes absent here fall back to a
# status-based mapping (see `exception_for`), so a code added
# server-side still raises something sensible from an older SDK.
_CODE_MAP: dict[str, type[T1Error]] = {
    "AUTH_MISSING_CREDENTIALS": T1AuthError,
    "AUTH_INVALID_KEY": T1AuthError,
    "AUTH_EXPIRED_KEY": T1AuthError,
    "AUTH_REVOKED_KEY": T1AuthError,
    "AUTH_INVALID_TOKEN": T1AuthError,
    "AUTH_EXPIRED_TOKEN": T1AuthError,
    "AUTH_INSUFFICIENT_SCOPE": T1AuthError,
    "AUTH_ADMIN_REQUIRED": T1AuthError,
    "IP_BLOCKED": T1AuthError,
    "IP_NOT_ALLOWLISTED": T1AuthError,
    "MTLS_REQUIRED": T1AuthError,
    "MTLS_INVALID": T1AuthError,
    "SERVER_UNTRUSTED": T1AuthError,
    "MODEL_NOT_SUPPORTED": T1NotFoundError,
    "NOT_FOUND": T1NotFoundError,
    "MODULE_NOT_FOUND": T1NotFoundError,
    "SERVER_NOT_FOUND": T1NotFoundError,
    "JOB_NOT_FOUND": T1NotFoundError,
    "VALIDATION_ERROR": T1ValidationError,
    "CONFLICT": T1ValidationError,
    "MODULE_ALREADY_EXISTS": T1ValidationError,
    "MODULE_UPLOAD_REJECTED": T1ValidationError,
    "JOB_NOT_CANCELLABLE": T1ValidationError,
    "PATH_TRAVERSAL_REJECTED": T1ValidationError,
    "SSRF_BLOCKED": T1ValidationError,
    "PAYMENT_TOKEN_INVALID": T1ValidationError,
    "PAYMENT_TOKEN_ALREADY_REDEEMED": T1ValidationError,
    "CONFIRMATION_REQUIRED": T1ValidationError,
    "PAYLOAD_TOO_LARGE": T1ValidationError,
    "CHECKSUM_MISMATCH": T1ValidationError,
    "RATE_LIMITED": T1QuotaError,
    "QUOTA_EXCEEDED": T1QuotaError,
    "MODEL_QUOTA_EXHAUSTED": T1QuotaError,
    "ROUTING_EXHAUSTED": T1QuotaError,
    "INSUFFICIENT_BALANCE": T1QuotaError,
    "NOT_SUPPORTED": T1NotSupportedError,
    "MODEL_UNAVAILABLE": T1ServerError,
    "TRANSPORT_FAILED": T1ServerError,
    "INTERNAL_ERROR": T1ServerError,
    "CONFIG_INVALID": T1ServerError,
}


def exception_for(
    message: str,
    *,
    code: str | None,
    status: int | None,
    request_id: str | None = None,
    details: dict[str, Any] | None = None,
    retry_after: float | None = None,
) -> T1Error:
    """Build the right exception for a server error response."""
    cls: type[T1Error] | None = _CODE_MAP.get(code or "")
    if cls is None:
        if status is None:
            cls = T1TransportError
        elif status in (401, 403):
            cls = T1AuthError
        elif status == 404:
            cls = T1NotFoundError
        elif status == 429:
            cls = T1QuotaError
        elif status == 501:
            cls = T1NotSupportedError
        elif status >= 500:
            cls = T1ServerError
        elif status >= 400:
            cls = T1ValidationError
        else:
            cls = T1Error
    if cls is T1QuotaError:
        return T1QuotaError(
            message, code=code, status=status, request_id=request_id, details=details,
            retry_after=retry_after,
        )
    return cls(message, code=code, status=status, request_id=request_id, details=details)


__all__ = [
    "T1AuthError",
    "T1Error",
    "T1NotFoundError",
    "T1NotSupportedError",
    "T1QuotaError",
    "T1ServerError",
    "T1TransportError",
    "T1ValidationError",
    "exception_for",
]
