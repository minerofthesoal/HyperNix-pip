from __future__ import annotations

from fastapi import APIRouter, Depends, File, Header, Request, UploadFile

from ..audit import AuditCategory, AuditLog, AuditOutcome
from ..auth import AuthContext
from ..deps import (
    get_audit_log,
    get_auth_context,
    get_client_ip,
    get_config,
    get_event_bus,
    get_job_queue,
    get_module_registry,
    get_request_id,
    get_server_registry,
    require_admin,
    require_confirmation,
)
from ..errors import T1APIError, T1ErrorCode
from ..jobs import JobQueue
from ..modules import ModuleRegistry, ModuleStatus
from ..schemas import (
    ModuleCreateRequest,
    ModuleDeployRequest,
    ModuleDeployResponse,
    ModuleDetailResponse,
    ModuleFetchResponse,
    ModuleItem,
    ModuleListResponse,
    ModuleReceiveResponse,
    ModuleSyncRequest,
    ModuleSyncResponse,
    ModuleUpdateRequest,
    ModuleUploadRemoteRequest,
)
from ..servers import ServerRegistry
from ..transport import (
    HEADER_CHECKSUM,
    HEADER_MODULE_ID,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    verify_signature,
)

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
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    registry: ModuleRegistry = Depends(get_module_registry),
    bus=Depends(get_event_bus),
    audit: AuditLog = Depends(get_audit_log),
    request_id: str = Depends(get_request_id),
) -> ModuleDetailResponse:
    """Delete a module and its stored bytes.

    Destructive and irreversible, so it needs ``?confirm=true`` (see
    ``deps.require_confirmation`` / ``T1_REQUIRE_DESTRUCTIVE_CONFIRMATION``)
    and is audited whether it succeeds or is refused.
    """
    existing = registry.require(module_id)
    _owns_or_admin(ctx, existing.owner_key_id)
    require_confirmation(request, action="Deleting a module")
    registry.delete(module_id)
    audit.record(
        "module.delete",
        category=AuditCategory.WRITE,
        outcome=AuditOutcome.SUCCESS,
        actor_key_id=ctx.key_id,
        actor_is_admin=ctx.is_admin,
        resource_type="module",
        resource_id=module_id,
        client_ip=get_client_ip(request),
        request_id=request_id,
        details={"name": existing.name, "version": existing.version},
    )
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


@router.post("/{module_id}/deploy", response_model=ModuleDeployResponse)
def deploy_module(
    module_id: str,
    body: ModuleDeployRequest,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    registry: ModuleRegistry = Depends(get_module_registry),
    servers: ServerRegistry = Depends(get_server_registry),
    job_queue: JobQueue = Depends(get_job_queue),
    audit: AuditLog = Depends(get_audit_log),
    request_id: str = Depends(get_request_id),
) -> ModuleDeployResponse:
    """Beta 3: push a module's bytes to one or more trusted servers.

    ``POST /modules/{id}/sync`` remains for the single-server case with
    its Beta 2 payload untouched; this is the multi-target form. Both
    queue the same ``module_sync`` job kind, so there is one code path
    doing the actual transfer.

    Every target is trust-checked *here*, before the job is queued, so a
    request naming an untrusted server fails immediately with
    ``SERVER_UNTRUSTED`` instead of succeeding into a job that fails
    later somewhere the caller isn't looking.
    """
    existing = registry.require(module_id)
    _owns_or_admin(ctx, existing.owner_key_id)
    for server_id in body.server_ids:
        servers.require_trusted(server_id)

    job = job_queue.submit(
        "module_sync",
        {"module_id": module_id, "server_ids": body.server_ids, "created_by": ctx.key_id},
        created_by=ctx.key_id,
    )
    audit.record(
        "module.deploy.requested",
        category=AuditCategory.WRITE,
        outcome=AuditOutcome.SUCCESS,
        actor_key_id=ctx.key_id,
        actor_is_admin=ctx.is_admin,
        resource_type="module",
        resource_id=module_id,
        client_ip=get_client_ip(request),
        request_id=request_id,
        details={"server_ids": body.server_ids, "job_id": job.job_id},
    )
    return ModuleDeployResponse(
        job_id=job.job_id, status=job.status.value, server_ids=body.server_ids, request_id=request_id
    )


@router.post("/{module_id}/fetch", response_model=ModuleFetchResponse)
def fetch_module_source(
    module_id: str,
    ctx: AuthContext = Depends(get_auth_context),
    registry: ModuleRegistry = Depends(get_module_registry),
    job_queue: JobQueue = Depends(get_job_queue),
    request_id: str = Depends(get_request_id),
) -> ModuleFetchResponse:
    """Beta 3: stage a module's registered remote source into local storage.

    The URL is not a parameter — it comes from the registry entry that
    ``POST /modules/upload/remote`` validated. Accepting a URL here would
    reopen the SSRF hole that registering it through the validated path
    closes.
    """
    existing = registry.require(module_id)
    _owns_or_admin(ctx, existing.owner_key_id)
    job = job_queue.submit(
        "module_fetch", {"module_id": module_id, "created_by": ctx.key_id}, created_by=ctx.key_id
    )
    return ModuleFetchResponse(job_id=job.job_id, status=job.status.value, request_id=request_id)


@router.post("/receive", response_model=ModuleReceiveResponse)
async def receive_module(
    request: Request,
    x_t1_signature: str = Header(default="", alias=HEADER_SIGNATURE),
    x_t1_timestamp: str = Header(default="", alias=HEADER_TIMESTAMP),
    x_t1_content_sha256: str = Header(default="", alias=HEADER_CHECKSUM),
    x_t1_module_id: str = Header(default="", alias=HEADER_MODULE_ID),
    registry: ModuleRegistry = Depends(get_module_registry),
    audit: AuditLog = Depends(get_audit_log),
    config=Depends(get_config),
    request_id: str = Depends(get_request_id),
) -> ModuleReceiveResponse:
    """Beta 3: accept a signed module push from another T1 server.

    Authenticated by the shared deployment secret rather than by a T1
    key — a peer server is not a user, holds no key of its own, and
    giving every deployment target an admin key just to receive bytes
    would be a much larger grant than this needs.

    Order matters and is enforced here: verify the signature (which
    covers the body digest, method, path, and a freshness window), then
    verify the declared checksum against the bytes actually received,
    and only then store. Nothing is written to disk before both checks
    pass, and nothing is ever executed.
    """
    body = await request.body()
    client_ip = get_client_ip(request)
    prefix = config.mount_prefix or ""
    try:
        verify_signature(
            config.deploy_secret,
            method="POST",
            # The signature covers the path the sender addressed. A
            # mounted app sees the prefix in request.url.path, so strip
            # it back to the sender's view rather than failing every
            # transfer into a mounted deployment.
            path=request.url.path[len(prefix):] if prefix and request.url.path.startswith(prefix) else request.url.path,
            timestamp=x_t1_timestamp,
            body=body,
            signature=x_t1_signature,
        )
    except Exception as exc:
        audit.record(
            "module.receive",
            category=AuditCategory.SECURITY,
            outcome=AuditOutcome.DENIED,
            resource_type="module",
            resource_id=x_t1_module_id,
            client_ip=client_ip,
            request_id=request_id,
            details={"reason": getattr(exc, "message", str(exc))},
        )
        raise

    import hashlib

    actual = hashlib.sha256(body).hexdigest()
    if x_t1_content_sha256 and actual != x_t1_content_sha256:
        audit.record(
            "module.receive",
            category=AuditCategory.SECURITY,
            outcome=AuditOutcome.FAILURE,
            resource_type="module",
            resource_id=x_t1_module_id,
            client_ip=client_ip,
            request_id=request_id,
            details={"reason": "checksum mismatch"},
        )
        raise T1APIError(
            T1ErrorCode.CHECKSUM_MISMATCH,
            "Received bytes do not match the declared X-T1-Content-SHA256.",
            http_status=400,
        )
    if len(body) > config.max_transfer_bytes:
        raise T1APIError(
            T1ErrorCode.PAYLOAD_TOO_LARGE,
            f"Transfer is {len(body)} bytes, over this server's {config.max_transfer_bytes}-byte cap.",
            http_status=413,
        )

    metadata = {}
    raw_metadata = request.headers.get("x-t1-module-metadata")
    if raw_metadata:
        import json as _json

        try:
            parsed = _json.loads(raw_metadata)
            if isinstance(parsed, dict):
                metadata = parsed
        except ValueError:
            metadata = {}

    entry = registry.receive_transfer(
        module_id=x_t1_module_id,
        content=body,
        name=metadata.get("name"),
        version=metadata.get("version"),
        metadata={"received_from_ip": client_ip},
    )
    audit.record(
        "module.receive",
        category=AuditCategory.WRITE,
        outcome=AuditOutcome.SUCCESS,
        resource_type="module",
        resource_id=entry.module_id,
        client_ip=client_ip,
        request_id=request_id,
        details={"size_bytes": entry.size_bytes, "checksum": (entry.checksum or "")[:16]},
    )
    return ModuleReceiveResponse(
        module_id=entry.module_id,
        checksum=entry.checksum or "",
        size_bytes=entry.size_bytes or 0,
        status=entry.status.value,
        request_id=request_id,
    )


__all__ = ["router"]
