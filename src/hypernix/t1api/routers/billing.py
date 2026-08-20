from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import AuthContext
from ..billing import BillingLedger
from ..deps import get_auth_context, get_billing_ledger, get_request_id, require_admin
from ..schemas import (
    AddBalanceRequest,
    BillingBalanceResponse,
    PaymentTokenMintRequest,
    PaymentTokenMintResponse,
    RedeemRequest,
    TransactionItem,
    TransactionListResponse,
)

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/balance", response_model=BillingBalanceResponse)
def get_balance(
    ctx: AuthContext = Depends(get_auth_context),
    ledger: BillingLedger = Depends(get_billing_ledger),
    request_id: str = Depends(get_request_id),
) -> BillingBalanceResponse:
    """Returns the caller's own ``user``-account balance. Checking another
    account's balance is an admin operation, not exposed here — add a
    ``account_type``/``account_id`` query pair gated by ``require_admin``
    if that's needed later."""
    balance = ledger.get_balance("user", ctx.key_id)
    return BillingBalanceResponse(account_type="user", account_id=ctx.key_id, balance=balance, request_id=request_id)


@router.get("/transactions", response_model=TransactionListResponse)
def get_transactions(
    ctx: AuthContext = Depends(get_auth_context),
    ledger: BillingLedger = Depends(get_billing_ledger),
    request_id: str = Depends(get_request_id),
) -> TransactionListResponse:
    txns = ledger.transactions("user", ctx.key_id)
    items = [TransactionItem(**t.to_dict()) for t in txns]
    return TransactionListResponse(transactions=items, count=len(items), request_id=request_id)


@router.post("/payment-token", response_model=PaymentTokenMintResponse)
def mint_payment_token(
    body: PaymentTokenMintRequest,
    ctx: AuthContext = Depends(get_auth_context),
    ledger: BillingLedger = Depends(get_billing_ledger),
    request_id: str = Depends(get_request_id),
) -> PaymentTokenMintResponse:
    """Admin-only — minting a redeemable balance credit is equivalent to
    printing money in this ledger, so it's gated the same way admin key
    rotation is."""
    require_admin(ctx)
    expires_at = None
    if body.ttl_seconds is not None:
        import time

        expires_at = time.time() + body.ttl_seconds
    raw_token, record = ledger.mint_payment_token(
        body.amount, created_by=ctx.key_id, currency=body.currency, expires_at=expires_at
    )
    return PaymentTokenMintResponse(
        token=raw_token,
        payment_token_id=record.payment_token_id,
        amount=record.amount,
        currency=record.currency,
        request_id=request_id,
    )


@router.post("/redeem", response_model=BillingBalanceResponse)
def redeem(
    body: RedeemRequest,
    ctx: AuthContext = Depends(get_auth_context),
    ledger: BillingLedger = Depends(get_billing_ledger),
    request_id: str = Depends(get_request_id),
) -> BillingBalanceResponse:
    account_id = body.account_id or ctx.key_id
    ledger.redeem(body.token, account_type=body.account_type, account_id=account_id, redeemed_by=ctx.key_id)
    balance = ledger.get_balance(body.account_type, account_id)
    return BillingBalanceResponse(
        account_type=body.account_type, account_id=account_id, balance=balance, request_id=request_id
    )


@router.post("/add-balance", response_model=BillingBalanceResponse)
def add_balance(
    body: AddBalanceRequest,
    ctx: AuthContext = Depends(get_auth_context),
    ledger: BillingLedger = Depends(get_billing_ledger),
    request_id: str = Depends(get_request_id),
) -> BillingBalanceResponse:
    """Admin-only — a direct credit with no payment-token trail is the
    most trusted billing operation there is."""
    require_admin(ctx)
    ledger.add_balance(body.account_type, body.account_id, body.amount, created_by=ctx.key_id, note=body.note)
    balance = ledger.get_balance(body.account_type, body.account_id)
    return BillingBalanceResponse(
        account_type=body.account_type, account_id=body.account_id, balance=balance, request_id=request_id
    )


__all__ = ["router"]
