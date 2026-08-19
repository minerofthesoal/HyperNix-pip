from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..auth import AuthContext
from ..deps import get_auth_context, get_request_id, get_usage_meter
from ..schemas import UsageCurrentResponse, UsageRemainingResponse
from ..usage import UsageMeter

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/current", response_model=UsageCurrentResponse)
def usage_current(
    ctx: AuthContext = Depends(get_auth_context),
    meter: UsageMeter = Depends(get_usage_meter),
    request_id: str = Depends(get_request_id),
) -> UsageCurrentResponse:
    data = meter.current(ctx.key_id)
    return UsageCurrentResponse(**data, request_id=request_id)


@router.get("/remaining", response_model=UsageRemainingResponse)
def usage_remaining(
    model_id: str = Query(..., description="Registered model_id to check remaining allowance for."),
    ctx: AuthContext = Depends(get_auth_context),
    meter: UsageMeter = Depends(get_usage_meter),
    request_id: str = Depends(get_request_id),
) -> UsageRemainingResponse:
    snap = meter.snapshot_for_model(ctx.key_id, model_id)
    return UsageRemainingResponse(
        model_id=model_id,
        input_remaining=snap.input_remaining,
        output_remaining=snap.output_remaining,
        is_exhausted=snap.is_exhausted,
        request_id=request_id,
    )


__all__ = ["router"]
