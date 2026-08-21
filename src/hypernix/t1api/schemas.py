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


# ---------------------------------------------------------------------------
# Beta 2: routing
# ---------------------------------------------------------------------------


class RouteRequest(BaseModel):
    plan: str = Field(..., description="Caller's plan, used to resolve a routing policy.")
    model_id: str | None = Field(
        default=None, description="Manual model selection. Omit for automatic routing."
    )
    input_tokens: int = Field(default=0, ge=0)
    automatic_fallback: bool = Field(
        default=False,
        description="Only meaningful with model_id set: fall through the cascade if the "
        "requested model is exhausted, instead of raising MODEL_QUOTA_EXHAUSTED.",
    )


class RouteResponse(BaseModel):
    model_id: str
    reason: str
    cascade_position: int
    policy_name: str
    considered: list[dict[str, Any]]
    request_id: str


# ---------------------------------------------------------------------------
# Beta 2: servers
# ---------------------------------------------------------------------------


class ServerRegisterRequest(BaseModel):
    name: str
    address: str
    capabilities: list[str] = Field(default_factory=list)
    tags: dict[str, str] = Field(default_factory=dict)
    allow_private_address: bool = Field(
        default=False, description="Set True for local/Tailscale addresses."
    )


class ServerUpdateRequest(BaseModel):
    name: str | None = None
    status: str | None = None
    trust_level: str | None = None
    capabilities: list[str] | None = None
    tags: dict[str, str] | None = None


class ServerItem(BaseModel):
    server_id: str
    name: str
    address: str
    trust_level: str
    status: str
    capabilities: list[str]
    tags: dict[str, str]
    registered_by: str
    created_at: float
    updated_at: float
    last_seen: float | None


class ServerListResponse(BaseModel):
    servers: list[ServerItem]
    count: int
    request_id: str


class ServerDetailResponse(BaseModel):
    server: ServerItem
    request_id: str


# ---------------------------------------------------------------------------
# Beta 2: modules
# ---------------------------------------------------------------------------


class ModuleCreateRequest(BaseModel):
    name: str
    version: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModuleUpdateRequest(BaseModel):
    metadata: dict[str, Any] | None = None
    status: str | None = None


class ModuleUploadRemoteRequest(BaseModel):
    source_url: str
    allow_private: bool = False


class ModuleSyncRequest(BaseModel):
    server_id: str


class ModuleItem(BaseModel):
    module_id: str
    name: str
    version: str
    owner_key_id: str
    status: str
    source_type: str
    source_url: str | None
    checksum: str | None
    size_bytes: int | None
    deployed_servers: list[str]
    metadata: dict[str, Any]
    created_at: float
    updated_at: float


class ModuleListResponse(BaseModel):
    modules: list[ModuleItem]
    count: int
    request_id: str


class ModuleDetailResponse(BaseModel):
    module: ModuleItem
    request_id: str


class ModuleSyncResponse(BaseModel):
    job_id: str
    status: str
    request_id: str


# ---------------------------------------------------------------------------
# Beta 2: jobs
# ---------------------------------------------------------------------------


class JobCreateRequest(BaseModel):
    kind: str
    payload: dict[str, Any] = Field(default_factory=dict)


class JobItem(BaseModel):
    job_id: str
    kind: str
    payload: dict[str, Any]
    status: str
    result: dict[str, Any] | None
    error: str | None
    created_by: str
    created_at: float
    started_at: float | None
    finished_at: float | None


class JobListResponse(BaseModel):
    jobs: list[JobItem]
    count: int
    request_id: str


class JobDetailResponse(BaseModel):
    job: JobItem
    request_id: str


# ---------------------------------------------------------------------------
# Beta 2: events
# ---------------------------------------------------------------------------


class EventItem(BaseModel):
    event_id: str
    type: str
    data: dict[str, Any]
    source: str
    ts: float


class EventListResponse(BaseModel):
    events: list[EventItem]
    count: int
    request_id: str


# ---------------------------------------------------------------------------
# Beta 2: billing
# ---------------------------------------------------------------------------


class BillingBalanceResponse(BaseModel):
    account_type: str
    account_id: str
    balance: float
    request_id: str


class TransactionItem(BaseModel):
    transaction_id: str
    account_type: str
    account_id: str
    amount: float
    kind: str
    balance_after: float
    note: str
    created_by: str
    created_at: float


class TransactionListResponse(BaseModel):
    transactions: list[TransactionItem]
    count: int
    request_id: str


class PaymentTokenMintRequest(BaseModel):
    amount: float = Field(..., gt=0)
    currency: str = "USD"
    ttl_seconds: int | None = Field(default=None, ge=1)


class PaymentTokenMintResponse(BaseModel):
    token: str = Field(..., description="Raw token — shown exactly once, never retrievable again.")
    payment_token_id: str
    amount: float
    currency: str
    request_id: str


class RedeemRequest(BaseModel):
    token: str
    account_type: str = "user"
    account_id: str | None = Field(
        default=None, description="Defaults to the authenticated caller's key_id if omitted."
    )


class AddBalanceRequest(BaseModel):
    account_type: str
    account_id: str
    amount: float = Field(..., gt=0)
    note: str = ""


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
    "RouteRequest",
    "RouteResponse",
    "ServerRegisterRequest",
    "ServerUpdateRequest",
    "ServerItem",
    "ServerListResponse",
    "ServerDetailResponse",
    "ModuleCreateRequest",
    "ModuleUpdateRequest",
    "ModuleUploadRemoteRequest",
    "ModuleSyncRequest",
    "ModuleItem",
    "ModuleListResponse",
    "ModuleDetailResponse",
    "ModuleSyncResponse",
    "JobCreateRequest",
    "JobItem",
    "JobListResponse",
    "JobDetailResponse",
    "EventItem",
    "EventListResponse",
    "BillingBalanceResponse",
    "TransactionItem",
    "TransactionListResponse",
    "PaymentTokenMintRequest",
    "PaymentTokenMintResponse",
    "RedeemRequest",
    "AddBalanceRequest",
]
