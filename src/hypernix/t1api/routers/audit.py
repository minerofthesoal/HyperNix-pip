"""``GET /audit`` — read the audit trail.

Not in the spec's numbered endpoint list, and added for the same reason
``GET /events`` is there: "complete audit logging" (Beta 3) is only
complete if the log can be read back. An audit trail that can only be
written is a compliance checkbox, not an investigative tool.

Admin-only, unconditionally. The log records who did what to which
resource from which address; that is a map of the deployment's
administrators and their activity, and it is not something a
read-scoped key should be able to enumerate.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from ..audit import AuditCategory, AuditLog, AuditOutcome
from ..auth import AuthContext
from ..deps import (
    get_audit_log,
    get_auth_context,
    get_client_ip,
    get_request_id,
    require_admin,
)
from ..schemas import AuditItem, AuditListResponse

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=AuditListResponse)
def list_audit_events(
    request: Request,
    category: str | None = Query(default=None, description="admin | security | write | billing"),
    action: str | None = Query(default=None, description="e.g. 'keys.assign'"),
    outcome: str | None = Query(default=None, description="success | denied | failure"),
    actor_key_id: str | None = Query(default=None, description="Full key_id; matched by its mask."),
    resource_type: str | None = Query(default=None),
    since: float | None = Query(default=None),
    until: float | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    ctx: AuthContext = Depends(get_auth_context),
    audit: AuditLog = Depends(get_audit_log),
    request_id: str = Depends(get_request_id),
) -> AuditListResponse:
    require_admin(ctx)
    # Reading the audit log is itself an administrator action, so it goes
    # in the log. Without this, "who has been reading the audit trail"
    # is the one question the audit trail can't answer.
    audit.record(
        "audit.read",
        category=AuditCategory.ADMIN,
        outcome=AuditOutcome.SUCCESS,
        actor_key_id=ctx.key_id,
        actor_is_admin=True,
        resource_type="audit",
        client_ip=get_client_ip(request),
        request_id=request_id,
        details={"category": category, "action": action, "limit": limit},
    )
    records = audit.query(
        category=category,
        action=action,
        outcome=outcome,
        actor_key_id=actor_key_id,
        resource_type=resource_type,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return AuditListResponse(
        events=[AuditItem(**r.to_dict()) for r in records],
        count=len(records),
        total=audit.count(),
        limit=limit,
        offset=offset,
        request_id=request_id,
    )


__all__ = ["router"]
