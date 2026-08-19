from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import T1APIConfig
from ..deps import get_config, get_request_id
from ..schemas import ConfigResponse

router = APIRouter(tags=["config"])


@router.get("/config", response_model=ConfigResponse)
def get_public_config(
    config: T1APIConfig = Depends(get_config),
    request_id: str = Depends(get_request_id),
) -> ConfigResponse:
    """Returns only the explicit allowlist in ``T1APIConfig.public_dict()``
    — never secrets. See ``t1api/config.py`` for why that's an allowlist
    and not a blocklist."""
    return ConfigResponse(config=config.public_dict(), request_id=request_id)


__all__ = ["router"]
