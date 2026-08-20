from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile

from ..auth import AuthContext
from ..deps import (
    get_auth_context,
    get_event_bus,
    get_job_queue,
    get_module_registry,
    get_request_id,
    get_server_registry,
    require_admin,
)
from ..jobs import JobQueue
from ..modules import ModuleRegistry, ModuleStatus
from ..schemas import (
    ModuleCreateRequest,
    ModuleDetailResponse,
    ModuleItem,
    ModuleListResponse,
    ModuleSyncRequest,
    ModuleSyncResponse,
    ModuleUpdateRequest,
    ModuleUploadRemoteRequest,
)
from ..servers import ServerRegistry

router = APIRouter(prefix="/modules", tags=["modules"])


def _to_item(entry) -> ModuleItem:
    return ModuleItem(**entry.to_dict())


def _owns_or_admin(ctx: AuthContext, owner_key_id: str) -> None:
    if not ctx.is_admin and ctx.key_id != owner_key_id:
        require_admin(ctx)  # raises AUTH_ADMIN_REQUIRED with a consistent message


@router.get("", response_model=ModuleListResponse)
def list_modules(
    ctx: AuthContext = Depends(get_auth_context),
    registry: ModuleRegistry = Depends(get_module_registry),
    request_id: str = Depends(get_request_id),
) -> ModuleListResponse:
    entries = registry.list(owner_key_id=None if ctx.is_admin else ctx.key_id)
    return ModuleListResponse(modules=[_to_item(e) for e in entries], count=len(entries), request_id=request_id)


@router.post("/create", response_model=ModuleDetailResponse)
def create_module(
    body: ModuleCreateRequest,
    ctx: AuthContext = Depends(get_auth_context),
    registry: ModuleRegistry = Depends(get_module_registry),
    bus=Depends(get_event_bus),
    request_id: str = Depends(get_request_id),
) -> ModuleDetailResponse:
    entry = registry.create(name=body.name, version=body.version, owner_key_id=ctx.key_id, metadata=body.metadata)
    bus.publish("module.created", {"module_id": entry.module_id, "name": entry.name}, source="modules")
    return ModuleDetailResponse(module=_to_item(entry), request_id=request_id)


@router.post("/upload/local", response_model=ModuleDetailResponse)
async def upload_local(
    module_id: str,
    file: UploadFile = File(...),
    ctx: AuthContext = Depends(get_auth_context),
    registry: ModuleRegistry = Depends(get_module_registry),
    bus=Depends(get_event_bus),
    request_id: str = Depends(get_request_id),
) -> ModuleDetailResponse:
    existing = registry.require(module_id)
    _owns_or_admin(ctx, existing.owner_key_id)
    content = await file.read()
    entry = registry.upload_local(module_id, content, filename=file.filename or "module.bin")
    bus.publish(
        "module.uploaded", {"module_id": module_id, "size_bytes": entry.size_bytes}, source="modules"
    )
    return ModuleDetailResponse(module=_to_item(entry), request_id=request_id)


@router.post("/upload/remote", response_model=ModuleDetailResponse)
def upload_remote(
    module_id: str,
    body: ModuleUploadRemoteRequest,
    ctx: AuthContext = Depends(get_auth_context),
    registry: ModuleRegistry = Depends(get_module_registry),
    bus=Depends(get_event_bus),
    request_id: str = Depends(get_request_id),
) -> ModuleDetailResponse:
    """Validates and *registers* a remote source — does not fetch it (see
    t1api/modules.py's module docstring). The module is marked
    PENDING_FETCH; actually staging the content is a separate concern not
    wired to a job kind in this beta (no real remote fetch infrastructure
    exists to safely exercise yet — see wiki/T1-API.md#roadmap)."""
    existing = registry.require(module_id)
    _owns_or_admin(ctx, existing.owner_key_id)
    entry = registry.register_remote_source(module_id, body.source_url, allow_private=body.allow_private)
    bus.publish(
        "module.remote_source_registered",
        {"module_id": module_id, "source_url": body.source_url},
        source="modules",
    )
    return ModuleDetailResponse(module=_to_item(entry), request_id=request_id)


@router.get("/{module_id}", response_model=ModuleDetailResponse)
def get_module(
    module_id: str,
    registry: ModuleRegistry = Depends(get_module_registry),
    request_id: str = Depends(get_request_id),
) -> ModuleDetailResponse:
    entry = registry.require(module_id)
    return ModuleDetailResponse(module=_to_item(entry), request_id=request_id)


@router.patch("/{module_id}", response_model=ModuleDetailResponse)
def update_module(
    module_id: str,
    body: ModuleUpdateRequest,
    ctx: AuthContext = Depends(get_auth_context),
    registry: ModuleRegistry = Depends(get_module_registry),
    request_id: str = Depends(get_request_id),
) -> ModuleDetailResponse:
    existing = registry.require(module_id)
    _owns_or_admin(ctx, existing.owner_key_id)
    entry = registry.update(
        module_id, metadata=body.metadata, status=ModuleStatus(body.status) if body.status else None
    )
    return ModuleDetailResponse(module=_to_item(entry), request_id=request_id)


@router.delete("/{module_id}", response_model=ModuleDetailResponse)
def delete_module(
    module_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    registry: ModuleRegistry = Depends(get_module_registry),
    bus=Depends(get_event_bus),
    request_id: str = Depends(get_request_id),
) -> ModuleDetailResponse:
    existing = registry.require(module_id)
    _owns_or_admin(ctx, existing.owner_key_id)
    registry.delete(module_id)
    bus.publish("module.deleted", {"module_id": module_id}, source="modules")
    return ModuleDetailResponse(module=_to_item(existing), request_id=request_id)


@router.post("/{module_id}/sync", response_model=ModuleSyncResponse)
def sync_module(
    module_id: str,
    body: ModuleSyncRequest,
    ctx: AuthContext = Depends(get_auth_context),
    registry: ModuleRegistry = Depends(get_module_registry),
    servers: ServerRegistry = Depends(get_server_registry),
    job_queue: JobQueue = Depends(get_job_queue),
    request_id: str = Depends(get_request_id),
) -> ModuleSyncResponse:
    """Queues a ``module_sync`` job rather than syncing inline — matches
    the spec's async-job model for cross-system operations. The handler
    (wired in ``t1api.app``) checks server trust before recording the
    sync; see ``wiki/T1-API.md#modules`` for exactly what "sync" means in
    this beta (tracking/trust-gating, not real byte transport)."""
    existing = registry.require(module_id)
    _owns_or_admin(ctx, existing.owner_key_id)
    servers.require(body.server_id)  # SERVER_NOT_FOUND early, before queuing a doomed job
    job = job_queue.submit(
        "module_sync", {"module_id": module_id, "server_id": body.server_id}, created_by=ctx.key_id
    )
    return ModuleSyncResponse(job_id=job.job_id, status=job.status.value, request_id=request_id)


__all__ = ["router"]
