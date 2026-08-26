"""``/backup/list`` and ``/backup/restore``.

Both are admin-only, and restore additionally requires an explicit
confirmation — see :mod:`hypernix.t1api.backup` for why the default is a
dry run.

The section *collection* lives here rather than in ``backup.py`` because
it is the only part that has to know which stores this particular server
has wired onto ``app.state``. Keeping it out of the store is what lets
the store be tested with three dicts.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from ..audit import AuditCategory, AuditOutcome
from ..auth import AuthContext
from ..backup import BACKUP_SECTIONS, BackupStore
from ..deps import get_audit_log, get_auth_context, get_client_ip, get_request_id, require_admin
from ..schemas import (
    BackupCreateRequest,
    BackupListResponse,
    BackupRestoreRequest,
    BackupRestoreResponse,
    BackupSummary,
)
from ..version import T1_VERSION

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backup", tags=["backup"])


def get_backup_store(request: Request) -> BackupStore:
    return request.app.state.t1_backup_store


def _collect(request: Request, ctx: AuthContext) -> dict[str, Any]:
    """Gather the snapshot-able state off ``app.state``.

    Every section is optional: a deployment that has not wired a store
    simply has no section for it, which is better than failing a backup
    because an optional subsystem is absent.
    """
    state = request.app.state
    sections: dict[str, Any] = {}

    config = getattr(state, "t1_config", None)
    if config is not None:
        sections["config"] = config.public_dict()

    registry = getattr(state, "t1_registry", None)
    if registry is not None:
        sections["model_registry"] = [
            entry.to_dict() if hasattr(entry, "to_dict") else str(entry)
            for entry in registry.list()
        ]

    engine = getattr(state, "t1_routing_engine", None)
    table = getattr(engine, "table", None) if engine is not None else None
    if table is not None and hasattr(table, "to_dict"):
        sections["routing_policies"] = table.to_dict()

    servers = getattr(state, "t1_server_registry", None)
    if servers is not None and hasattr(servers, "list"):
        sections["servers"] = [s.to_dict() for s in servers.list()]

    modules = getattr(state, "t1_module_registry", None)
    if modules is not None and hasattr(modules, "list"):
        sections["modules"] = [m.to_dict() for m in modules.list()]

    directory = getattr(state, "t1_key_directory", None)
    if directory is not None and hasattr(directory, "list_keys"):
        # Metadata only — key material is never captured. See backup.EXCLUDED.
        # The directory scopes its own listing by requester, so the
        # backup sees exactly what this admin could already read: a
        # snapshot must not be a way around an access control.
        try:
            entries = directory.list_keys(requester_key_id=ctx.key_id, is_admin=ctx.is_admin)
        except TypeError:
            entries = directory.list_keys()
        sections["key_directory"] = [
            {k: v for k, v in entry.items() if "key" not in k or k.endswith("_id")}
            if isinstance(entry, dict)
            else (entry.to_dict() if hasattr(entry, "to_dict") else str(entry))
            for entry in entries
        ]

    devices = getattr(state, "t1_device_registry", None)
    if devices is not None and hasattr(devices, "list_devices"):
        sections["hyperlink_devices"] = [d.to_dict() for d in devices.list_devices()]

    return sections


@router.get("/list", response_model=BackupListResponse)
def list_backups(
    ctx: AuthContext = Depends(get_auth_context),
    store: BackupStore = Depends(get_backup_store),
    request_id: str = Depends(get_request_id),
) -> BackupListResponse:
    """Every snapshot on this server, newest first. Admin only.

    Admin because the manifest names which subsystems a deployment runs
    and how many records each holds, which is more of a map than an
    ordinary caller needs.
    """
    require_admin(ctx)
    records = store.list_backups()
    return BackupListResponse(
        backups=[BackupSummary(**r.to_dict()) for r in records],
        count=len(records),
        sections_captured=list(BACKUP_SECTIONS),
        request_id=request_id,
    )


@router.post("", response_model=BackupSummary)
def create_backup(
    payload: BackupCreateRequest,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    store: BackupStore = Depends(get_backup_store),
    request_id: str = Depends(get_request_id),
    audit=Depends(get_audit_log),
) -> BackupSummary:
    """Take a snapshot now."""
    require_admin(ctx)
    import hypernix

    record = store.create(
        _collect(request, ctx),
        label=payload.label,
        created_by=ctx.key_id,
        t1_version=T1_VERSION.short,
        hypernix_version=getattr(hypernix, "__version__", "unknown"),
    )
    audit.record(
        "backup.create",
        category=AuditCategory.ADMIN,
        actor_key_id=ctx.key_id,
        actor_is_admin=True,
        outcome=AuditOutcome.SUCCESS,
        resource_type="backup",
        resource_id=record.backup_id,
        client_ip=get_client_ip(request),
        request_id=request_id,
    )
    return BackupSummary(**record.to_dict())


@router.post("/restore", response_model=BackupRestoreResponse)
def restore_backup(
    payload: BackupRestoreRequest,
    request: Request,
    confirm: bool = Query(default=False, description="Required for a live restore"),
    ctx: AuthContext = Depends(get_auth_context),
    store: BackupStore = Depends(get_backup_store),
    request_id: str = Depends(get_request_id),
    audit=Depends(get_audit_log),
) -> BackupRestoreResponse:
    """Restore a snapshot. Dry run unless ``?confirm=true``.

    The confirmation is a query parameter rather than a body field so it
    shows up in the request line an operator reads back afterwards —
    same reasoning as the destructive-operation guard elsewhere in this
    API.
    """
    require_admin(ctx)
    dry_run = payload.dry_run if payload.dry_run is not None else not confirm

    result = store.restore(
        payload.backup_id,
        _make_applier(request) if not dry_run else None,
        dry_run=dry_run,
        confirm=confirm,
        sections=payload.sections or None,
    )
    audit.record(
        "backup.restore",
        category=AuditCategory.ADMIN,
        actor_key_id=ctx.key_id,
        actor_is_admin=True,
        outcome=AuditOutcome.SUCCESS,
        resource_type="backup",
        resource_id=payload.backup_id,
        client_ip=get_client_ip(request),
        request_id=request_id,
        details={"dry_run": dry_run, "sections": payload.sections or "all"},
    )
    return BackupRestoreResponse(**result, request_id=request_id)


def _make_applier(request: Request):
    """Return the function that actually writes a section back.

    Deliberately narrow. Only the sections that can be restored without
    touching credentials are wired; anything else reports
    ``"not restorable"`` rather than silently doing nothing, so a dry run
    and a live run agree about what will happen.
    """
    state = request.app.state

    def apply(name: str, payload: Any) -> str:
        if name == "model_registry":
            registry = getattr(state, "t1_registry", None)
            if registry is None or not hasattr(registry, "restore_from"):
                return "model registry present but has no restore_from(); skipped"
            count = registry.restore_from(payload)
            return f"restored {count} model entries"
        if name == "network_policy":
            policy = getattr(state, "t1_network_policy", None)
            if policy is None or not hasattr(policy, "restore_from"):
                return "network policy present but has no restore_from(); skipped"
            return f"restored {policy.restore_from(payload)} rules"
        if name == "config":
            # Config comes from the environment, by design. Restoring it
            # would mean a backup could change how a server authenticates
            # itself, which is a much larger blast radius than "put the
            # model list back".
            return "not restorable: configuration comes from the environment"
        if name == "key_directory":
            return (
                "not restorable: key records are metadata only and key material is never "
                "captured. Re-mint and re-distribute."
            )
        return f"not restorable: no applier for {name!r}"

    return apply


@router.delete("/{backup_id}")
def delete_backup(
    backup_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    store: BackupStore = Depends(get_backup_store),
    request_id: str = Depends(get_request_id),
) -> dict[str, Any]:
    require_admin(ctx)
    from ..deps import require_confirmation

    require_confirmation(request, action=f"Deleting backup {backup_id}")
    store.delete(backup_id)
    return {"ok": True, "detail": f"Deleted {backup_id}", "request_id": request_id}


__all__ = ["router", "get_backup_store"]
