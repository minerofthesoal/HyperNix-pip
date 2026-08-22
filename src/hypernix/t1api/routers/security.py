"""Network policy and forced limits — the server side of ``waiter``'s
``-B`` / ``-W`` / ``-a`` / ``-r`` flags.

Beta 1/2 parsed those flags, stored them in the local waiter config, and
printed "the T1 API doesn't expose blacklist/whitelist/rate-limit-override
endpoints yet". These are those endpoints. Not in the spec's numbered
list, but required by it twice over: the SECURITY section asks for IP
allowlists and optional blocklists, and the design principle makes the
server responsible for deciding "if the non whitelisted user/person
trying to get access is both, not black listed and that the server allows
non whitelisted users to connect" — a decision that needs somewhere to
store its inputs.

Everything here is admin-only and audited. Editing who may reach the
server, or how hard they may hit it, is as privileged as rotating a key.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Query, Request

from ..audit import AuditCategory, AuditLog, AuditOutcome
from ..auth import AuthContext
from ..deps import (
    get_audit_log,
    get_auth_context,
    get_client_ip,
    get_config,
    get_network_policy,
    get_rate_limiter,
    get_request_id,
    require_admin,
)
from ..errors import T1APIError, T1ErrorCode
from ..netpolicy import EntryKind, NetworkPolicy
from ..ratelimit import RateLimiter, Subject
from ..schemas import (
    ForcedLimitItem,
    ForcedLimitListResponse,
    ForcedLimitRequest,
    ForcedLimitResponse,
    GenericOkResponse,
    NetworkPolicyEntryItem,
    NetworkPolicyEntryRequest,
    NetworkPolicyResponse,
    RateLimitStatusResponse,
)

router = APIRouter(prefix="/security", tags=["security"])


def _audit(
    audit: AuditLog,
    request: Request,
    ctx: AuthContext,
    request_id: str,
    action: str,
    *,
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
    resource_id: str = "",
    details: dict | None = None,
) -> None:
    audit.record(
        action,
        category=AuditCategory.SECURITY,
        outcome=outcome,
        actor_key_id=ctx.key_id,
        actor_is_admin=ctx.is_admin,
        resource_type="network_policy",
        resource_id=resource_id,
        client_ip=get_client_ip(request),
        request_id=request_id,
        details=details or {},
    )


def _policy_response(policy: NetworkPolicy, config, request_id: str, kind: EntryKind | None = None):
    entries = policy.list_entries(kind=kind)
    return NetworkPolicyResponse(
        entries=[NetworkPolicyEntryItem(**e.to_dict()) for e in entries],
        count=len(entries),
        allow_unlisted_clients=policy.allow_unlisted,
        enabled=config.network_policy_enabled,
        request_id=request_id,
    )


# ---------------------------------------------------------------------------
# Network policy
# ---------------------------------------------------------------------------


@router.get("/network", response_model=NetworkPolicyResponse)
def get_network_policy_entries(
    kind: str | None = Query(default=None, description="'allow' or 'block'; omit for both."),
    ctx: AuthContext = Depends(get_auth_context),
    policy: NetworkPolicy = Depends(get_network_policy),
    config=Depends(get_config),
    request_id: str = Depends(get_request_id),
) -> NetworkPolicyResponse:
    require_admin(ctx)
    return _policy_response(policy, config, request_id, EntryKind(kind) if kind else None)


@router.post("/network/blacklist", response_model=NetworkPolicyResponse)
def add_to_blacklist(
    body: NetworkPolicyEntryRequest,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    policy: NetworkPolicy = Depends(get_network_policy),
    config=Depends(get_config),
    audit: AuditLog = Depends(get_audit_log),
    request_id: str = Depends(get_request_id),
) -> NetworkPolicyResponse:
    """``waiter -B`` — block an address or CIDR range.

    Refuses to block the caller's own address. Locking yourself out of
    the server you administer is a mistake with no undo through this API
    (you'd have to reach the database directly), so it's worth one
    guard rather than one incident.
    """
    require_admin(ctx)
    caller_ip = get_client_ip(request)
    entry_targets_caller = False
    if caller_ip:
        import ipaddress

        try:
            network = ipaddress.ip_network(body.cidr.strip(), strict=False)
            addr = ipaddress.ip_address(caller_ip)
            entry_targets_caller = addr.version == network.version and addr in network
        except ValueError:
            entry_targets_caller = False
    if entry_targets_caller:
        _audit(
            audit, request, ctx, request_id, "network.blacklist.add",
            outcome=AuditOutcome.DENIED, resource_id=body.cidr,
            details={"reason": "would block the requesting address"},
        )
        raise T1APIError(
            T1ErrorCode.VALIDATION_ERROR,
            f"'{body.cidr}' covers your own address ({caller_ip}). Blocking it would lock you "
            "out of this API with no way back in through it.",
            details={"cidr": body.cidr},
            http_status=422,
        )

    expires_at = time.time() + body.ttl_seconds if body.ttl_seconds else None
    policy.block(body.cidr, reason=body.reason, created_by=ctx.key_id, expires_at=expires_at)
    _audit(
        audit, request, ctx, request_id, "network.blacklist.add",
        resource_id=body.cidr, details={"reason": body.reason, "expires_at": expires_at},
    )
    return _policy_response(policy, config, request_id)


@router.post("/network/whitelist", response_model=NetworkPolicyResponse)
def add_to_whitelist(
    body: NetworkPolicyEntryRequest,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    policy: NetworkPolicy = Depends(get_network_policy),
    config=Depends(get_config),
    audit: AuditLog = Depends(get_audit_log),
    request_id: str = Depends(get_request_id),
) -> NetworkPolicyResponse:
    """``waiter -W`` — allowlist an address or CIDR range.

    Note this does not un-block a blocked address: the blocklist wins by
    design (see ``t1api.netpolicy``). To restore access to a blocked
    address, appeal it with ``DELETE /security/network/{cidr}``.
    """
    require_admin(ctx)
    expires_at = time.time() + body.ttl_seconds if body.ttl_seconds else None
    policy.allow(body.cidr, reason=body.reason, created_by=ctx.key_id, expires_at=expires_at)
    _audit(
        audit, request, ctx, request_id, "network.whitelist.add",
        resource_id=body.cidr, details={"reason": body.reason, "expires_at": expires_at},
    )
    return _policy_response(policy, config, request_id)


@router.delete("/network/{cidr:path}", response_model=NetworkPolicyResponse)
def appeal_network_entry(
    cidr: str,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    policy: NetworkPolicy = Depends(get_network_policy),
    config=Depends(get_config),
    audit: AuditLog = Depends(get_audit_log),
    request_id: str = Depends(get_request_id),
) -> NetworkPolicyResponse:
    """``waiter -a`` — appeal: remove an allow or block entry.

    The ``{cidr:path}`` converter is deliberate: a CIDR contains a
    slash, and without it ``10.0.0.0/8`` would be parsed as two path
    segments and never match.
    """
    require_admin(ctx)
    removed = policy.remove(cidr)
    _audit(
        audit, request, ctx, request_id, "network.appeal",
        outcome=AuditOutcome.SUCCESS if removed else AuditOutcome.FAILURE,
        resource_id=cidr, details={"removed": removed},
    )
    if not removed:
        raise T1APIError(
            T1ErrorCode.NOT_FOUND,
            f"No network-policy entry for '{cidr}'.",
            details={"cidr": cidr},
            http_status=404,
        )
    return _policy_response(policy, config, request_id)


@router.post("/network/allow-unlisted", response_model=NetworkPolicyResponse)
def set_allow_unlisted(
    request: Request,
    enabled: bool = Query(..., description="May clients that are on neither list connect?"),
    ctx: AuthContext = Depends(get_auth_context),
    policy: NetworkPolicy = Depends(get_network_policy),
    config=Depends(get_config),
    audit: AuditLog = Depends(get_audit_log),
    request_id: str = Depends(get_request_id),
) -> NetworkPolicyResponse:
    """Flip the server between "open unless blocked" and "allowlist only".

    Held in memory, so a restart returns to whatever
    ``T1_ALLOW_UNLISTED_CLIENTS`` says. That's intentional: the
    deployment's environment is the source of truth for its posture, and
    an API call shouldn't silently outlive the configuration that
    documents it.
    """
    require_admin(ctx)
    policy.set_allow_unlisted(enabled)
    _audit(
        audit, request, ctx, request_id, "network.allow_unlisted",
        details={"enabled": enabled, "persists_across_restart": False},
    )
    return _policy_response(policy, config, request_id)


# ---------------------------------------------------------------------------
# Forced limits (waiter -r)
# ---------------------------------------------------------------------------


@router.get("/limits", response_model=ForcedLimitListResponse)
def list_forced_limits(
    ctx: AuthContext = Depends(get_auth_context),
    policy: NetworkPolicy = Depends(get_network_policy),
    request_id: str = Depends(get_request_id),
) -> ForcedLimitListResponse:
    require_admin(ctx)
    limits = policy.list_limits()
    return ForcedLimitListResponse(
        limits=[ForcedLimitItem(**limit.to_dict()) for limit in limits],
        count=len(limits),
        request_id=request_id,
    )


@router.post("/limits", response_model=ForcedLimitResponse)
def set_forced_limit(
    body: ForcedLimitRequest,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    policy: NetworkPolicy = Depends(get_network_policy),
    audit: AuditLog = Depends(get_audit_log),
    request_id: str = Depends(get_request_id),
) -> ForcedLimitResponse:
    """``waiter -r`` — force a limit on one T1 key or one server.

    A forced limit only ever tightens: it is applied *in addition to* the
    configured rate-limit rules, so it cannot be used to hand a subject
    more throughput than the defaults allow.
    """
    require_admin(ctx)
    limit = policy.set_limit(
        body.subject_type,
        body.subject_id,
        requests_per_window=body.requests_per_window,
        tokens_per_window=body.tokens_per_window,
        window_seconds=body.window_seconds,
        reason=body.reason,
        created_by=ctx.key_id,
    )
    audit.record(
        "limits.force",
        category=AuditCategory.ADMIN,
        outcome=AuditOutcome.SUCCESS,
        actor_key_id=ctx.key_id,
        actor_is_admin=True,
        resource_type=body.subject_type,
        resource_id=body.subject_id,
        client_ip=get_client_ip(request),
        request_id=request_id,
        details={
            "requests_per_window": body.requests_per_window,
            "tokens_per_window": body.tokens_per_window,
            "window_seconds": body.window_seconds,
            "reason": body.reason,
        },
    )
    return ForcedLimitResponse(limit=ForcedLimitItem(**limit.to_dict()), request_id=request_id)


@router.delete("/limits/{subject_type}/{subject_id}", response_model=GenericOkResponse)
def clear_forced_limit(
    subject_type: str,
    subject_id: str,
    request: Request,
    ctx: AuthContext = Depends(get_auth_context),
    policy: NetworkPolicy = Depends(get_network_policy),
    audit: AuditLog = Depends(get_audit_log),
    request_id: str = Depends(get_request_id),
) -> GenericOkResponse:
    require_admin(ctx)
    cleared = policy.clear_limit(subject_type, subject_id)
    audit.record(
        "limits.clear",
        category=AuditCategory.ADMIN,
        outcome=AuditOutcome.SUCCESS if cleared else AuditOutcome.FAILURE,
        actor_key_id=ctx.key_id,
        actor_is_admin=True,
        resource_type=subject_type,
        resource_id=subject_id,
        client_ip=get_client_ip(request),
        request_id=request_id,
    )
    if not cleared:
        raise T1APIError(
            T1ErrorCode.NOT_FOUND,
            f"No forced limit set for {subject_type} {subject_id[:12]}.",
            http_status=404,
        )
    return GenericOkResponse(ok=True, detail="Forced limit cleared.", request_id=request_id)


@router.get("/rate-limits", response_model=RateLimitStatusResponse)
def rate_limit_status(
    ctx: AuthContext = Depends(get_auth_context),
    limiter: RateLimiter = Depends(get_rate_limiter),
    request_id: str = Depends(get_request_id),
) -> RateLimitStatusResponse:
    """The caller's own remaining rate-limit budget.

    Not admin-gated: a client that can see how much budget it has left
    can back off before it gets a 429, which is better for both sides
    than discovering the limit by hitting it.
    """
    return RateLimitStatusResponse(
        rules=limiter.snapshot(Subject("key", ctx.key_id)),
        enabled=limiter.enabled,
        request_id=request_id,
    )


__all__ = ["router"]
