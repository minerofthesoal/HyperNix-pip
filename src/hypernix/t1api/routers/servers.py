from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import AuthContext
from ..deps import (
    get_auth_context,
    get_event_bus,
    get_request_id,
    get_server_registry,
    require_admin,
)
from ..schemas import (
    ServerDetailResponse,
    ServerItem,
    ServerListResponse,
    ServerRegisterRequest,
    ServerUpdateRequest,
)
from ..servers import ServerRegistry, ServerStatus, TrustLevel

router = APIRouter(prefix="/servers", tags=["servers"])


def _to_item(entry) -> ServerItem:
    return ServerItem(**entry.to_dict())


@router.get("", response_model=ServerListResponse)
def list_servers(
    registry: ServerRegistry = Depends(get_server_registry),
    ctx: AuthContext = Depends(get_auth_context),
    request_id: str = Depends(get_request_id),
) -> ServerListResponse:
    entries = registry.list()
    return ServerListResponse(servers=[_to_item(e) for e in entries], count=len(entries), request_id=request_id)


@router.post("/register", response_model=ServerDetailResponse)
def register_server(
    body: ServerRegisterRequest,
    ctx: AuthContext = Depends(get_auth_context),
    registry: ServerRegistry = Depends(get_server_registry),
    bus=Depends(get_event_bus),
    request_id: str = Depends(get_request_id),
) -> ServerDetailResponse:
    entry = registry.register(
        name=body.name,
        address=body.address,
        registered_by=ctx.key_id,
        capabilities=body.capabilities,
        tags=body.tags,
        allow_private_address=body.allow_private_address,
    )
    bus.publish("server.registered", {"server_id": entry.server_id, "name": entry.name}, source="servers")
    return ServerDetailResponse(server=_to_item(entry), request_id=request_id)


@router.patch("/{server_id}", response_model=ServerDetailResponse)
def update_server(
    server_id: str,
    body: ServerUpdateRequest,
    ctx: AuthContext = Depends(get_auth_context),
    registry: ServerRegistry = Depends(get_server_registry),
    bus=Depends(get_event_bus),
    request_id: str = Depends(get_request_id),
) -> ServerDetailResponse:
    """Admin-only: trust-level changes are a security-relevant escalation
    ("Verify remote server trust before remote uploads" only means
    anything if promoting a server to trusted is itself gated)."""
    require_admin(ctx)
    entry = registry.update(
        server_id,
        name=body.name,
        status=ServerStatus(body.status) if body.status else None,
        trust_level=TrustLevel(body.trust_level) if body.trust_level else None,
        capabilities=body.capabilities,
        tags=body.tags,
    )
    bus.publish(
        "server.updated",
        {"server_id": entry.server_id, "trust_level": entry.trust_level.value, "status": entry.status.value},
        source="servers",
    )
    return ServerDetailResponse(server=_to_item(entry), request_id=request_id)


@router.delete("/{server_id}", response_model=ServerDetailResponse)
def delete_server(
    server_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    registry: ServerRegistry = Depends(get_server_registry),
    bus=Depends(get_event_bus),
    request_id: str = Depends(get_request_id),
) -> ServerDetailResponse:
    require_admin(ctx)
    entry = registry.require(server_id)
    registry.delete(server_id)
    bus.publish("server.deleted", {"server_id": server_id}, source="servers")
    return ServerDetailResponse(server=_to_item(entry), request_id=request_id)


__all__ = ["router"]
