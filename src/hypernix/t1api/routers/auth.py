from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import AuthContext, T1AuthService
from ..deps import get_auth_context, get_auth_service, get_request_id, require_admin
from ..schemas import (
    AdminRotateRequest,
    RotateResponse,
    TokenRequest,
    TokenResponse,
    ValidateKeyRequest,
    ValidateKeyResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/t1/validate", response_model=ValidateKeyResponse)
def validate(
    body: ValidateKeyRequest,
    svc: T1AuthService = Depends(get_auth_service),
    request_id: str = Depends(get_request_id),
) -> ValidateKeyResponse:
    ctx = svc.validate_key(body.key)
    return ValidateKeyResponse(
        key_id=ctx.key_id,
        key_type=ctx.key_meta.key_type.value,
        scopes=sorted(s.value for s in ctx.scopes),
        active=ctx.key_meta.active,
        is_admin=ctx.is_admin,
        expires_at=ctx.key_meta.expires_at,
        request_id=request_id,
    )


@router.post("/token", response_model=TokenResponse)
def issue_token(
    body: TokenRequest,
    svc: T1AuthService = Depends(get_auth_service),
    request_id: str = Depends(get_request_id),
) -> TokenResponse:
    tok = svc.issue_scoped_token(body.key, ttl_seconds=body.ttl_seconds, scopes=body.scopes)
    return TokenResponse(
        token=tok.token,
        key_id=tok.key_id,
        scopes=tok.scopes,
        expires_at=tok.expires_at,
        request_id=request_id,
    )


@router.post("/t1/rotate", response_model=RotateResponse)
def rotate_own_key(
    ctx: AuthContext = Depends(get_auth_context),
    svc: T1AuthService = Depends(get_auth_service),
    request_id: str = Depends(get_request_id),
) -> RotateResponse:
    """A caller may always rotate the key/token they authenticated with."""
    new_meta = svc.rotate_own_key(ctx.key_id)
    return RotateResponse(
        key_id=new_meta.key_id,
        key=new_meta.key,
        key_type=new_meta.key_type.value,
        scopes=sorted(s.value for s in new_meta.scopes),
        rotated_from=new_meta.rotated_from,
        request_id=request_id,
    )


@router.post("/t1/admin/rotate", response_model=RotateResponse)
def admin_rotate(
    body: AdminRotateRequest,
    ctx: AuthContext = Depends(get_auth_context),
    svc: T1AuthService = Depends(get_auth_service),
    request_id: str = Depends(get_request_id),
) -> RotateResponse:
    require_admin(ctx)
    new_meta = svc.admin_rotate(
        requester=ctx, target_key_id=body.target_key_id, promote_to_admin=body.promote_to_admin
    )
    return RotateResponse(
        key_id=new_meta.key_id,
        key=new_meta.key,
        key_type=new_meta.key_type.value,
        scopes=sorted(s.value for s in new_meta.scopes),
        rotated_from=new_meta.rotated_from,
        request_id=request_id,
    )


__all__ = ["router"]
