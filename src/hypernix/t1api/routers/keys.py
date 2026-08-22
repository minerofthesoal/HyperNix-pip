"""Key directory endpoints: ``GET /keys``, ``POST /keys/import``,
``POST /keys/assign``.

Three rules govern this router and are worth stating where they're
enforced rather than only in the module they call into:

* **No endpoint here ever returns a raw key.** Listing returns masked
  ids and metadata; import returns counts and masked ids. The only
  endpoint in the whole API that hands back a key string is rotation,
  which mints a *new* one — see ``routers/auth.py``.
* **Import and assign are admin-only.** Importing keys grants access;
  assigning a plan grants quota. Both are credential-shaped operations
  even though neither returns a credential.
* **Every call is audited.** Import and assign are administrator actions
  in the spec's sense, so they are recorded with the actor, the target,
  and the outcome — including refusals, which are the interesting ones.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from ..audit import AuditCategory, AuditLog, AuditOutcome
from ..auth import AuthContext
from ..deps import (
    get_audit_log,
    get_auth_context,
    get_client_ip,
    get_key_directory,
    get_request_id,
    get_server_registry,
    require_admin,
)
from ..keys import KeyDirectory
from ..schemas import (
    KeyAssignmentItem,
    KeyAssignRequest,
    KeyAssignResponse,
    KeyImportRequest,
    KeyImportResponse,
    KeyItem,
    KeyListResponse,
)

router = APIRouter(prefix="/keys", tags=["keys"])


def _to_item(summary) -> KeyItem:
    data = summary.to_dict()
    assignment = data.pop("assignment", None)
    return KeyItem(
        **data,
        assignment=KeyAssignmentItem(**assignment) if assignment else None,
    )


@router.get("", response_model=KeyListResponse)
def list_keys(
    key_type: str | None = Query(default=None, description="Filter by 'user' | 'admin' | ..."),
    include_inactive: bool = Query(default=False),
    ctx: AuthContext = Depends(get_auth_context),
    directory: KeyDirectory = Depends(get_key_directory),
    request_id: str = Depends(get_request_id),
) -> KeyListResponse:
    """List keys. Admins see every key; everyone else sees only their own.

    Not admin-gated outright: a caller checking their own key's scopes,
    expiry, and assignment is an ordinary self-service operation, and
    refusing it would push clients toward caching that state locally
    where it goes stale.
    """
    summaries = directory.list_keys(
        requester_key_id=ctx.key_id,
        is_admin=ctx.is_admin,
        key_type=key_type,
        include_inactive=include_inactive,
    )
    return KeyListResponse(
        keys=[_to_item(s) for s in summaries],
        count=len(summaries),
        scope="all" if ctx.is_admin else "own",
        request_id=request_id,
    )


@router.post("/import", response_model=KeyImportResponse)
def import_keys(
    body: KeyImportRequest,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    directory: KeyDirectory = Depends(get_key_directory),
    audit: AuditLog = Depends(get_audit_log),
    request_id: str = Depends(get_request_id),
) -> KeyImportResponse:
    """Import a Keymaster export into this server's key store.

    The request body carries raw key material. It is never logged, never
    echoed, and never written to the audit record — the audit entry
    holds counts and masked ids, which is what an operator reviewing the
    action actually needs.
    """
    try:
        require_admin(ctx)
    except Exception:
        audit.record(
            "keys.import",
            category=AuditCategory.ADMIN,
            outcome=AuditOutcome.DENIED,
            actor_key_id=ctx.key_id,
            actor_is_admin=ctx.is_admin,
            resource_type="key",
            client_ip=get_client_ip(request),
            request_id=request_id,
        )
        raise

    result = directory.import_payload(body.payload, imported_by=ctx.key_id)
    audit.record(
        "keys.import",
        category=AuditCategory.ADMIN,
        outcome=AuditOutcome.SUCCESS,
        actor_key_id=ctx.key_id,
        actor_is_admin=True,
        resource_type="key",
        client_ip=get_client_ip(request),
        request_id=request_id,
        details={"imported": result["imported"], "skipped": result["skipped"]},
    )
    return KeyImportResponse(**result, request_id=request_id)


@router.post("/assign", response_model=KeyAssignResponse)
def assign_key(
    body: KeyAssignRequest,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    directory: KeyDirectory = Depends(get_key_directory),
    servers=Depends(get_server_registry),
    audit: AuditLog = Depends(get_audit_log),
    request_id: str = Depends(get_request_id),
) -> KeyAssignResponse:
    """Bind a key to a plan, account, user, servers, and model subset.

    This is where a key's plan comes from, and therefore where its quota
    and fallback chain come from — which is exactly why it is admin-only.
    A non-admin able to call this could assign itself a better plan,
    turning "the server decides which models the user can access" into
    "the user decides".
    """
    try:
        require_admin(ctx)
    except Exception:
        audit.record(
            "keys.assign",
            category=AuditCategory.ADMIN,
            outcome=AuditOutcome.DENIED,
            actor_key_id=ctx.key_id,
            actor_is_admin=ctx.is_admin,
            resource_type="key",
            resource_id=body.key_id,
            client_ip=get_client_ip(request),
            request_id=request_id,
        )
        raise

    assignment = directory.assign(
        body.key_id,
        assigned_by=ctx.key_id,
        plan=body.plan,
        account_id=body.account_id,
        user_id=body.user_id,
        server_ids=body.server_ids,
        allowed_models=body.allowed_models,
        note=body.note,
        server_validator=servers.require,
    )
    audit.record(
        "keys.assign",
        category=AuditCategory.ADMIN,
        outcome=AuditOutcome.SUCCESS,
        actor_key_id=ctx.key_id,
        actor_is_admin=True,
        resource_type="key",
        resource_id=body.key_id,
        client_ip=get_client_ip(request),
        request_id=request_id,
        details={
            "plan": assignment.plan,
            "allowed_models": assignment.allowed_models,
            "server_ids": assignment.server_ids,
        },
    )
    return KeyAssignResponse(
        assignment=KeyAssignmentItem(**assignment.to_dict()), request_id=request_id
    )


__all__ = ["router"]
