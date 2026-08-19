"""t1api.errors — stable, machine-readable error codes for the T1 API.

Every failure mode the T1 API can produce is represented by a
:class:`T1ErrorCode` member and raised as a :class:`T1APIError`. The HTTP
layer (``t1api.app``) converts these into a stable JSON envelope::

    {
      "error": {"code": "MODEL_NOT_SUPPORTED", "message": "...", "details": {}},
      "request_id": "..."
    }

The codes and envelope shape are a contract used by the waiter TUI and any
other T1 client — do not rename existing members. Add new ones instead of
repurposing old ones, and add new members to the end of the enum so any code
that persists the ordinal (none should) stays stable.

This module has zero third-party dependencies on purpose: both the pure
``t1api.registry`` / ``t1api.usage`` core and the FastAPI HTTP layer import
it, and the core must stay importable in environments where FastAPI/Pydantic
aren't installed (e.g. this is exactly what ``hypernix.keymaster`` /
``hypernix.gatekeeper`` already do — no framework dependency baked into the
enforcement logic).
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any


class T1ErrorCode(StrEnum):
    """Stable error codes returned by the T1 API.

    See ``wiki/T1-API.md`` for the full contract, including HTTP status
    mapping (``t1api.app._STATUS_FOR_CODE``).
    """

    # --- Model registry / routing -----------------------------------
    MODEL_NOT_SUPPORTED = "MODEL_NOT_SUPPORTED"
    MODEL_QUOTA_EXHAUSTED = "MODEL_QUOTA_EXHAUSTED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"

    # --- Auth ----------------------------------------------------------
    AUTH_MISSING_CREDENTIALS = "AUTH_MISSING_CREDENTIALS"
    AUTH_INVALID_KEY = "AUTH_INVALID_KEY"
    AUTH_EXPIRED_KEY = "AUTH_EXPIRED_KEY"
    AUTH_REVOKED_KEY = "AUTH_REVOKED_KEY"
    AUTH_INVALID_TOKEN = "AUTH_INVALID_TOKEN"
    AUTH_EXPIRED_TOKEN = "AUTH_EXPIRED_TOKEN"
    AUTH_INSUFFICIENT_SCOPE = "AUTH_INSUFFICIENT_SCOPE"
    AUTH_ADMIN_REQUIRED = "AUTH_ADMIN_REQUIRED"

    # --- Quota / rate limiting -----------------------------------------
    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"

    # --- Generic ---------------------------------------------------------
    NOT_SUPPORTED = "NOT_SUPPORTED"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    CONFLICT = "CONFLICT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class T1APIError(Exception):
    """Raised anywhere in the T1 API stack; carries a stable error code.

    Args:
        code: One of :class:`T1ErrorCode`.
        message: Human-readable detail. Never include secrets (raw keys,
            tokens, payment tokens) — see ``wiki/T1-API.md#security``.
        details: Optional structured extra context (e.g. ``{"model_id": ...}``).
        http_status: Overrides the default status mapping for this code
            when set.
    """

    def __init__(
        self,
        code: T1ErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        http_status: int | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.details = details or {}
        self.http_status = http_status
        super().__init__(f"[{code.value}] {message}")


__all__ = ["T1ErrorCode", "T1APIError"]
