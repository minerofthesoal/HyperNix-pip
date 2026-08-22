"""t1sdk.models — typed views over the API's JSON responses.

Every class here is a thin, forgiving wrapper: :meth:`from_dict` reads
the fields it knows and keeps the untouched payload in ``raw``. That
combination is deliberate. Typed attributes give an SDK user
autocompletion and a real signature; ``raw`` means a server running a
newer T1 version — one that added a field this SDK has never heard of —
degrades to "you can still reach it", not "the client crashes on parse".

The same reasoning is why nothing here is a Pydantic model: the SDK must
import on a machine that never installs the ``hypernix[t1api]`` extra,
so these are plain dataclasses with no validation dependency.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _f(data: dict[str, Any], key: str, default: Any = None) -> Any:
    return data.get(key, default)


@dataclass
class Model:
    """One entry from the server's model registry.

    Only models with an entry here exist as far as the T1 API is
    concerned — there is no way to reach a model by naming a path, which
    is the registry hard requirement seen from the client side.
    """

    model_id: str
    display_name: str
    version: str = ""
    architecture: str = ""
    status: str = ""
    availability: str = ""
    minimum_plan: str = ""
    free_tier_available: bool = False
    routing_priority: int = 0
    total_parameters: float | None = None
    active_parameters: float | None = None
    context_limit: int | None = None
    input_token_limit: int | None = None
    output_token_limit: int | None = None
    tool_call_limit: int | None = None
    fallback_model: str | None = None
    pricing: dict[str, Any] = field(default_factory=dict)
    supported_tasks: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_routable(self) -> bool:
        """Whether the *registry* considers this model selectable.

        Not the same question as "may I use it right now" — that also
        depends on your plan and remaining quota, and only the server can
        answer it (``POST /models/route``).
        """
        return self.status in ("available", "beta")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Model:
        return cls(
            model_id=_f(data, "model_id", ""),
            display_name=_f(data, "display_name", ""),
            version=_f(data, "version", ""),
            architecture=_f(data, "architecture", ""),
            status=_f(data, "status", ""),
            availability=_f(data, "availability", ""),
            minimum_plan=_f(data, "minimum_plan", ""),
            free_tier_available=bool(_f(data, "free_tier_available", False)),
            routing_priority=int(_f(data, "routing_priority", 0) or 0),
            total_parameters=_f(data, "total_parameters"),
            active_parameters=_f(data, "active_parameters"),
            context_limit=_f(data, "context_limit"),
            input_token_limit=_f(data, "input_token_limit"),
            output_token_limit=_f(data, "output_token_limit"),
            tool_call_limit=_f(data, "tool_call_limit"),
            fallback_model=_f(data, "fallback_model"),
            pricing=_f(data, "pricing", {}) or {},
            supported_tasks=list(_f(data, "supported_tasks", []) or []),
            raw=data,
        )


@dataclass
class ModelUsage:
    model_id: str
    input_tokens_used: int = 0
    output_tokens_used: int = 0
    requests: int = 0
    input_token_limit: int = 0
    output_token_limit: int = 0
    input_remaining: int = 0
    output_remaining: int = 0
    is_exhausted: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelUsage:
        return cls(
            model_id=_f(data, "model_id", ""),
            input_tokens_used=int(_f(data, "input_tokens_used", 0) or 0),
            output_tokens_used=int(_f(data, "output_tokens_used", 0) or 0),
            requests=int(_f(data, "requests", 0) or 0),
            input_token_limit=int(_f(data, "input_token_limit", 0) or 0),
            output_token_limit=int(_f(data, "output_token_limit", 0) or 0),
            input_remaining=int(_f(data, "input_remaining", 0) or 0),
            output_remaining=int(_f(data, "output_remaining", 0) or 0),
            is_exhausted=bool(_f(data, "is_exhausted", False)),
            raw=data,
        )


@dataclass
class RoutingDecision:
    """What the server decided, and what it rejected on the way.

    ``considered`` is the useful part for a UI: it lists each cascade
    step the router looked at and why it moved past it, which turns "you
    got model X" into "you got model X because Y and Z were exhausted".
    """

    model_id: str
    reason: str = ""
    cascade_position: int = -1
    policy_name: str = ""
    resolved_plan: str = ""
    considered: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RoutingDecision:
        return cls(
            model_id=_f(data, "model_id", ""),
            reason=_f(data, "reason", ""),
            cascade_position=int(_f(data, "cascade_position", -1) or -1),
            policy_name=_f(data, "policy_name", ""),
            resolved_plan=_f(data, "resolved_plan", ""),
            considered=list(_f(data, "considered", []) or []),
            raw=data,
        )


@dataclass
class Job:
    job_id: str
    kind: str = ""
    status: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = 0.0
    started_at: float | None = None
    finished_at: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    TERMINAL = ("succeeded", "failed", "cancelled")

    @property
    def is_terminal(self) -> bool:
        return self.status in self.TERMINAL

    @property
    def succeeded(self) -> bool:
        return self.status == "succeeded"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Job:
        return cls(
            job_id=_f(data, "job_id", ""),
            kind=_f(data, "kind", ""),
            status=_f(data, "status", ""),
            payload=_f(data, "payload", {}) or {},
            result=_f(data, "result"),
            error=_f(data, "error"),
            created_at=float(_f(data, "created_at", 0.0) or 0.0),
            started_at=_f(data, "started_at"),
            finished_at=_f(data, "finished_at"),
            raw=data,
        )


@dataclass
class Module:
    module_id: str
    name: str = ""
    version: str = ""
    status: str = ""
    source_type: str = ""
    source_url: str | None = None
    checksum: str | None = None
    size_bytes: int | None = None
    deployed_servers: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Module:
        return cls(
            module_id=_f(data, "module_id", ""),
            name=_f(data, "name", ""),
            version=_f(data, "version", ""),
            status=_f(data, "status", ""),
            source_type=_f(data, "source_type", ""),
            source_url=_f(data, "source_url"),
            checksum=_f(data, "checksum"),
            size_bytes=_f(data, "size_bytes"),
            deployed_servers=list(_f(data, "deployed_servers", []) or []),
            metadata=_f(data, "metadata", {}) or {},
            raw=data,
        )


@dataclass
class Server:
    server_id: str
    name: str = ""
    address: str = ""
    trust_level: str = ""
    status: str = ""
    capabilities: list[str] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_trusted(self) -> bool:
        """Only trusted (or local) servers can receive a module push."""
        return self.trust_level in ("trusted", "local")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Server:
        return cls(
            server_id=_f(data, "server_id", ""),
            name=_f(data, "name", ""),
            address=_f(data, "address", ""),
            trust_level=_f(data, "trust_level", ""),
            status=_f(data, "status", ""),
            capabilities=list(_f(data, "capabilities", []) or []),
            tags=_f(data, "tags", {}) or {},
            raw=data,
        )


@dataclass
class Event:
    event_id: str
    type: str = ""
    source: str = ""
    ts: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Event:
        return cls(
            event_id=_f(data, "event_id", ""),
            type=_f(data, "type", ""),
            source=_f(data, "source", ""),
            ts=float(_f(data, "ts", 0.0) or 0.0),
            data=_f(data, "data", {}) or {},
            raw=data,
        )


@dataclass
class KeyInfo:
    """A key as the directory reports it — masked id, never the key."""

    key_id: str
    key_type: str = ""
    scopes: list[str] = field(default_factory=list)
    active: bool = True
    expires_at: float | None = None
    usage_count: int = 0
    request_count: int = 0
    assignment: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def plan(self) -> str:
        return (self.assignment or {}).get("plan", "")

    @property
    def is_admin(self) -> bool:
        return self.key_type == "admin" and "admin" in self.scopes

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KeyInfo:
        return cls(
            key_id=_f(data, "key_id", ""),
            key_type=_f(data, "key_type", ""),
            scopes=list(_f(data, "scopes", []) or []),
            active=bool(_f(data, "active", True)),
            expires_at=_f(data, "expires_at"),
            usage_count=int(_f(data, "usage_count", 0) or 0),
            request_count=int(_f(data, "request_count", 0) or 0),
            assignment=_f(data, "assignment"),
            raw=data,
        )


@dataclass
class CostReport:
    total_cost: float = 0.0
    currency: str = "USD"
    lines: list[dict[str, Any]] = field(default_factory=list)
    unpriced_models: list[str] = field(default_factory=list)
    forecast: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CostReport:
        return cls(
            total_cost=float(_f(data, "total_cost", 0.0) or 0.0),
            currency=_f(data, "currency", "USD"),
            lines=list(_f(data, "lines", []) or []),
            unpriced_models=list(_f(data, "unpriced_models", []) or []),
            forecast=_f(data, "forecast"),
            raw=data,
        )


@dataclass
class ServerStatus:
    """``GET /status`` — version, backend, and which protections are on."""

    status: str = ""
    environment: str = ""
    t1_api_version: str = ""
    hypernix_version: str = ""
    beta: str = ""
    model_count: int = 0
    storage_backend: str = ""
    tls_enabled: bool = False
    mtls_mode: str = "off"
    rate_limit_enabled: bool = True
    audit_enabled: bool = True
    network_policy_enabled: bool = True
    allow_unlisted_clients: bool = True
    remote_deployment_enabled: bool = False
    secrets_configured: dict[str, bool] = field(default_factory=dict)
    production_ready: bool = True
    production_warnings: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServerStatus:
        return cls(
            status=_f(data, "status", ""),
            environment=_f(data, "environment", ""),
            t1_api_version=_f(data, "t1_api_version", ""),
            hypernix_version=_f(data, "hypernix_version", ""),
            beta=_f(data, "beta", ""),
            model_count=int(_f(data, "model_count", 0) or 0),
            storage_backend=_f(data, "storage_backend", ""),
            tls_enabled=bool(_f(data, "tls_enabled", False)),
            mtls_mode=_f(data, "mtls_mode", "off"),
            rate_limit_enabled=bool(_f(data, "rate_limit_enabled", True)),
            audit_enabled=bool(_f(data, "audit_enabled", True)),
            network_policy_enabled=bool(_f(data, "network_policy_enabled", True)),
            allow_unlisted_clients=bool(_f(data, "allow_unlisted_clients", True)),
            remote_deployment_enabled=bool(_f(data, "remote_deployment_enabled", False)),
            secrets_configured=_f(data, "secrets_configured", {}) or {},
            production_ready=bool(_f(data, "production_ready", True)),
            production_warnings=list(_f(data, "production_warnings", []) or []),
            raw=data,
        )


__all__ = [
    "CostReport",
    "Event",
    "Job",
    "KeyInfo",
    "Model",
    "ModelUsage",
    "Module",
    "RoutingDecision",
    "Server",
    "ServerStatus",
]
