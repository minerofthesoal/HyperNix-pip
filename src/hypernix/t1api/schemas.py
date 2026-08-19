"""t1api.schemas — Pydantic v2 request/response models for the T1 API.

Requires ``fastapi``/``pydantic`` (the ``hypernix[t1api]`` extra). Import
this module lazily from route handlers, not from ``t1api.registry`` /
``t1api.usage`` / ``t1api.storage``, which must stay importable without
these dependencies.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str


# ---------------------------------------------------------------------------
# Health / status
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str = "ok"
    request_id: str


class StatusResponse(BaseModel):
    status: str = "ok"
    environment: str
    t1_api_version: str
    hypernix_version: str
    beta: str
    model_count: int
    storage_backend: str
    request_id: str


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class ValidateKeyRequest(BaseModel):
    key: str = Field(..., min_length=4, description="Raw T1_ key string.")


class ValidateKeyResponse(BaseModel):
    key_id: str
    key_type: str
    scopes: list[str]
    active: bool
    is_admin: bool
    expires_at: float | None
    request_id: str


class TokenRequest(BaseModel):
    key: str = Field(..., min_length=4, description="Raw T1_ key string to exchange.")
    ttl_seconds: int | None = Field(default=None, ge=1, le=86400)
    scopes: list[str] | None = Field(
        default=None, description="Subset of the key's scopes to grant. Omit for all scopes."
    )


class TokenResponse(BaseModel):
    token: str
    key_id: str
    scopes: list[str]
    expires_at: float
    request_id: str


class RotateResponse(BaseModel):
    key_id: str
    key: str
    key_type: str
    scopes: list[str]
    rotated_from: str | None
    request_id: str


class AdminRotateRequest(BaseModel):
    target_key_id: str
    promote_to_admin: bool = False


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ModelSummary(BaseModel):
    model_id: str
    display_name: str
    version: str
    architecture: str
    status: str
    availability: str
    minimum_plan: str
    free_tier_available: bool
    routing_priority: int


class ModelDetail(ModelSummary):
    total_parameters: float
    active_parameters: float | None
    supported_tasks: list[str]
    api_available: bool
    local_available: bool
    remote_available: bool
    context_limit: int
    input_token_limit: int
    output_token_limit: int
    tool_call_limit: int | None
    pricing: dict[str, Any]
    fallback_model: str | None
    license: str
    is_example_entry: bool
    notes: str


class ModelListResponse(BaseModel):
    models: list[ModelSummary]
    count: int
    request_id: str


class ModelDetailResponse(BaseModel):
    model: ModelDetail
    request_id: str


class ModelAvailabilityResponse(BaseModel):
    model_id: str
    available: bool
    reason: str | None
    minimum_plan: str
    request_id: str


class ModelUsageResponse(BaseModel):
    model_id: str
    input_tokens_used: int
    output_tokens_used: int
    requests: int
    input_token_limit: int
    output_token_limit: int
    input_remaining: int
    output_remaining: int
    is_exhausted: bool
    request_id: str


# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------


class UsageCurrentResponse(BaseModel):
    key_id: str
    window_seconds: float
    current_window: dict[str, int]
    all_time: dict[str, int]
    by_model: list[dict[str, Any]]
    request_id: str


class UsageRemainingResponse(BaseModel):
    model_id: str
    input_remaining: int
    output_remaining: int
    is_exhausted: bool
    request_id: str


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class ConfigResponse(BaseModel):
    config: dict[str, Any]
    request_id: str


__all__ = [
    "ErrorDetail",
    "ErrorResponse",
    "HealthResponse",
    "StatusResponse",
    "ValidateKeyRequest",
    "ValidateKeyResponse",
    "TokenRequest",
    "TokenResponse",
    "RotateResponse",
    "AdminRotateRequest",
    "ModelSummary",
    "ModelDetail",
    "ModelListResponse",
    "ModelDetailResponse",
    "ModelAvailabilityResponse",
    "ModelUsageResponse",
    "UsageCurrentResponse",
    "UsageRemainingResponse",
    "ConfigResponse",
]
