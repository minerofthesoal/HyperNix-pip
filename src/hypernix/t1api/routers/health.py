from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from .. import __t1api_version__
from ..deps import get_config, get_registry, get_request_id
from ..schemas import HealthResponse, StatusResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(request_id: str = Depends(get_request_id)) -> HealthResponse:
    return HealthResponse(status="ok", request_id=request_id)


@router.get("/status", response_model=StatusResponse)
def status(
    request: Request,
    request_id: str = Depends(get_request_id),
    config=Depends(get_config),
    registry=Depends(get_registry),
) -> StatusResponse:
    import hypernix

    return StatusResponse(
        status="ok",
        environment=config.environment,
        t1_api_version=__t1api_version__,
        hypernix_version=getattr(hypernix, "__version__", "unknown"),
        beta="beta1",
        model_count=len(registry),
        storage_backend="sqlite",
        request_id=request_id,
    )


__all__ = ["router"]
