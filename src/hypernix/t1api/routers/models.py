from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import AuthContext
from ..deps import (
    get_auth_context,
    get_key_directory,
    get_registry,
    get_request_id,
    get_routing_engine,
    get_usage_meter,
)
from ..registry import ModelRegistry
from ..schemas import (
    ModelAvailabilityResponse,
    ModelDetail,
    ModelDetailResponse,
    ModelListResponse,
    ModelSummary,
    ModelUsageResponse,
    RouteRequest,
    RouteResponse,
)
from ..usage import UsageMeter

router = APIRouter(prefix="/models", tags=["models"])


def _to_summary(entry) -> ModelSummary:
    return ModelSummary(
        model_id=entry.model_id,
        display_name=entry.display_name,
        version=entry.version,
        architecture=entry.architecture,
        status=entry.status.value,
        availability=entry.availability.value,
        minimum_plan=entry.minimum_plan,
        free_tier_available=entry.free_tier_available,
        routing_priority=entry.routing_priority,
    )


def _to_detail(entry) -> ModelDetail:
    return ModelDetail(
        **_to_summary(entry).model_dump(),
        total_parameters=entry.total_parameters,
        active_parameters=entry.active_parameters,
        supported_tasks=entry.supported_tasks,
        api_available=entry.api_available,
        local_available=entry.local_available,
        remote_available=entry.remote_available,
        context_limit=entry.context_limit,
        input_token_limit=entry.input_token_limit,
        output_token_limit=entry.output_token_limit,
        tool_call_limit=entry.tool_call_limit,
        pricing=entry.pricing.to_dict(),
        fallback_model=entry.fallback_model,
        license=entry.license,
        is_example_entry=entry.is_example_entry,
        notes=entry.notes,
    )


@router.get("", response_model=ModelListResponse)
def list_models(
    registry: ModelRegistry = Depends(get_registry),
    request_id: str = Depends(get_request_id),
) -> ModelListResponse:
    """Public, unauthenticated model listing — matches the spec's
    endpoint contract (no auth requirement listed for GET /models)."""
    entries = registry.list()
    return ModelListResponse(
        models=[_to_summary(e) for e in entries], count=len(entries), request_id=request_id
    )


@router.get("/{model_id}", response_model=ModelDetailResponse)
def get_model(
    model_id: str,
    registry: ModelRegistry = Depends(get_registry),
    request_id: str = Depends(get_request_id),
) -> ModelDetailResponse:
    entry = registry.require(model_id)
    return ModelDetailResponse(model=_to_detail(entry), request_id=request_id)


@router.get("/{model_id}/availability", response_model=ModelAvailabilityResponse)
def model_availability(
    model_id: str,
    registry: ModelRegistry = Depends(get_registry),
    request_id: str = Depends(get_request_id),
) -> ModelAvailabilityResponse:
    """Registry-level availability: is this model routable at all?

    Deliberately unauthenticated and therefore *not* caller-aware — it
    answers "does this server offer this model", not "may you use it
    right now". The caller-specific answer needs a key, and lives in
    ``GET /models/{id}/usage`` (quota) and ``POST /models/route``
    (plan + quota + cascade). Splitting them keeps this endpoint usable
    as a public capability listing without it becoming a way to probe
    another account's quota state.
    """
    entry = registry.require(model_id)
    available = entry.is_routable and entry.api_available
    reason = None if available else "Model is not currently routable (status/api_available)."
    return ModelAvailabilityResponse(
        model_id=model_id,
        available=available,
        reason=reason,
        minimum_plan=entry.minimum_plan,
        request_id=request_id,
    )


@router.get("/{model_id}/usage", response_model=ModelUsageResponse)
def model_usage(
    model_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    meter: UsageMeter = Depends(get_usage_meter),
    request_id: str = Depends(get_request_id),
) -> ModelUsageResponse:
    snap = meter.snapshot_for_model(ctx.key_id, model_id)
    return ModelUsageResponse(**snap.to_dict(), request_id=request_id)


@router.post("/route", response_model=RouteResponse)
def route_model(
    body: RouteRequest,
    ctx: AuthContext = Depends(get_auth_context),
    engine=Depends(get_routing_engine),
    keys=Depends(get_key_directory),
    request_id: str = Depends(get_request_id),
) -> RouteResponse:
    """Not in the original endpoint list — added to give the routing/
    quota-cascade engine (``t1api.routing``) an HTTP surface, since the
    spec describes the engine's behavior in detail but doesn't enumerate
    an endpoint for it. See wiki/T1-API.md#routing.

    Automatic routing (no ``model_id``) walks the caller's plan cascade.
    Manual routing (``model_id`` set) enforces the exhausted-model rule
    exactly as the spec describes: ``MODEL_QUOTA_EXHAUSTED`` unless
    ``automatic_fallback=True``.

    **Beta 3 change, deliberately breaking Beta 2's shape:** the plan is
    no longer read from the request body. It is resolved from the key's
    server-side assignment (:meth:`t1api.keys.KeyDirectory.resolve_plan`),
    and a ``plan`` in the body is treated as an assertion — matching is
    fine, mismatching is refused. Beta 2 let a client name its own plan,
    which is the exact thing the design principle forbids: "the server
    determines... which models the user can access, which limits apply,
    which fallback models are allowed."

    A key narrowed to a model subset (``allowed_models`` on its
    assignment) is also checked here, so manual selection can't reach a
    model the assignment excludes even when the registry and quota would
    both allow it.
    """
    plan = keys.resolve_plan(ctx.key_id, requested_plan=body.plan)
    if body.model_id is None:
        decision = engine.route_automatic(
            key_id=ctx.key_id, plan=plan, input_tokens=body.input_tokens
        )
    else:
        keys.assert_model_allowed(ctx.key_id, body.model_id)
        decision = engine.route_manual(
            key_id=ctx.key_id,
            plan=plan,
            model_id=body.model_id,
            input_tokens=body.input_tokens,
            automatic_fallback=body.automatic_fallback,
        )
    # An automatic decision can still land on a model the key's
    # assignment excludes, since the cascade is plan-shaped and the
    # narrowing is key-shaped. Check the outcome too, rather than
    # assuming the two always agree.
    keys.assert_model_allowed(ctx.key_id, decision.model_id)
    return RouteResponse(**decision.to_dict(), resolved_plan=plan, request_id=request_id)


__all__ = ["router"]
