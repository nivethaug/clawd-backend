#!/usr/bin/env python3
"""
Razorpay Billing API Router — INR checkout for Indian customers.

Mounted at: /api/billing/razorpay (prefix added in app.py).

ZERO-IMPACT ISOLATION:
- api/billing_router.py (LemonSqueezy USD checkout) is NOT modified — this
  is a completely separate router with its own paths.
- Every Razorpay endpoint except currency-preference returns 503 when the
  RAZORPAY_* env vars are unset, exactly like the LS provider checks.
- Existing /api/billing/plans and /api/billing/credit-packs responses are
  unchanged; the INR view lives here at /razorpay/pricing.
- Fulfillment reuses billing_service (add_purchased_credits / assign_plan)
  — read-only reuse, no edits to the USD flow.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from database_postgres import get_db
from services import razorpay_service
from services.payment_sentry import capture_payment_failure, capture_payment_success

logger = logging.getLogger("api.billing.razorpay")

router = APIRouter()


def _get_user_id(authorization: Optional[str] = None) -> int:
    from app import get_user_id_from_token
    return get_user_id_from_token(authorization)


def _require_configured() -> None:
    if not razorpay_service.is_configured():
        raise HTTPException(status_code=503, detail="Razorpay is not configured")


# ============================================================================
# Pydantic Models
# ============================================================================

class CurrencyPreferenceRequest(BaseModel):
    currency: str  # "INR" | "USD"


class RazorpayOrderRequest(BaseModel):
    kind: str = "credit_pack"
    item_id: int


class RazorpayVerifyRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class RazorpaySubscriptionRequest(BaseModel):
    plan_slug: str


class RazorpaySubscriptionVerifyRequest(BaseModel):
    razorpay_payment_id: str
    razorpay_subscription_id: str
    razorpay_signature: str


# ============================================================================
# Currency preference (works regardless of Razorpay config — it is only a
# users column; nothing in the USD flow reads it)
# ============================================================================

@router.get("/currency-preference")
async def get_currency_preference(authorization: Optional[str] = Header(None)):
    user_id = _get_user_id(authorization)
    with get_db() as conn:
        row = conn.execute(
            "SELECT currency_preference FROM users WHERE id = %s", (user_id,)
        ).fetchone()
    pref = (dict(row) if row and not isinstance(row, dict) else row or {}).get(
        "currency_preference"
    )
    return {"currency_preference": pref, "inr_supported": razorpay_service.is_configured()}


@router.put("/currency-preference")
async def put_currency_preference(
    request: CurrencyPreferenceRequest,
    authorization: Optional[str] = Header(None),
):
    user_id = _get_user_id(authorization)
    currency = str(request.currency).strip().upper()
    if currency not in ("INR", "USD"):
        raise HTTPException(status_code=400, detail="currency must be INR or USD")
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET currency_preference = %s WHERE id = %s",
            (currency, user_id),
        )
        conn.commit()
    return {"success": True, "currency_preference": currency}


# ============================================================================
# INR pricing view (plans + packs, derived from USD via INR_PER_USD)
# ============================================================================

@router.get("/pricing")
async def get_inr_pricing():
    """Public INR pricing view (landing + /pricing pages use this pre-login).

    Same sensitivity as the already-public GET /api/billing/plans and
    /credit-packs: plan names/prices/features only. Still 503 when Razorpay
    env keys are unset, so nothing leaks when the feature is off.
    """
    _require_configured()

    from services.plan_cache import get_all_plans

    plans = get_all_plans()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM credit_packs WHERE active = true ORDER BY sort_order"
        ).fetchall()
    packs = [dict(r) if not isinstance(r, dict) else r for r in rows]

    def _inr(usd_cents):
        # Charged/displayed price (launch offer applied) + pre-offer
        # original for the strikethrough. 0 cents = Free plan → ₹0;
        # missing price (Enterprise) → "Custom".
        paise = razorpay_service.usd_cents_to_inr_paise(usd_cents or 0)
        orig = razorpay_service.usd_cents_to_inr_paise(usd_cents or 0, discounted=False)
        return (
            paise,
            razorpay_service.inr_display(paise if usd_cents is not None else None),
            razorpay_service.inr_display(orig if usd_cents is not None else None),
        )

    plan_out = []
    for slug, p in sorted(plans.items(), key=lambda x: x[1].get("sort_order", 0)):
        paise, display, display_original = _inr(p.get("price_monthly_cents"))
        plan_out.append({
            "slug": slug,
            "name": p.get("name"),
            "price_monthly_cents": p.get("price_monthly_cents"),
            "price_monthly_display": f"${p.get('price_monthly_cents', 0) / 100:.2f}",
            "inr_price_minor": paise,
            "inr_price_display": display,
            "inr_price_display_original": display_original,
            "max_active_projects": p.get("max_active_projects"),
            "features": p.get("features", []),
            "sort_order": p.get("sort_order", 0),
        })

    pack_out = []
    for pack in packs:
        paise, display, display_original = _inr(pack.get("price_cents"))
        pack_out.append({
            "id": pack["id"],
            "name": pack["name"],
            "credits": pack["credits"],
            "credit_type": pack.get("credit_type", "project_ai"),
            "price_cents": pack["price_cents"],
            "inr_price_minor": paise,
            "inr_price_display": display,
            "inr_price_display_original": display_original,
            "sort_order": pack.get("sort_order", 0),
        })

    return {
        "currency": "INR",
        "inr_per_usd": razorpay_service.get_inr_per_usd(),
        "plans": plan_out,
        "credit_packs": pack_out,
    }


# ============================================================================
# One-time payments (credit packs)
# ============================================================================

@router.post("/order")
async def create_razorpay_order(
    request: RazorpayOrderRequest,
    authorization: Optional[str] = Header(None),
):
    user_id = _get_user_id(authorization)
    _require_configured()

    if request.kind != "credit_pack":
        raise HTTPException(status_code=400, detail="kind must be credit_pack")

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM credit_packs WHERE id = %s AND active = true",
            (request.item_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Credit pack not found")
    pack = dict(row) if not isinstance(row, dict) else row

    amount_paise = razorpay_service.usd_cents_to_inr_paise(int(pack["price_cents"]))
    notes = {
        "user_id": str(user_id),
        "kind": "credit_pack",
        "item_id": str(pack["id"]),
    }

    try:
        order = razorpay_service.create_order(
            amount_paise=amount_paise,
            receipt=f"pack-{pack['id']}-u{user_id}"[:40],
            notes=notes,
        )
    except Exception as e:
        capture_payment_failure(
            provider="razorpay", event="checkout_create",
            reason="provider_api_error", user_id=user_id,
            pack_id=pack["id"],
        )
        raise HTTPException(status_code=502, detail=str(e)[:200])

    with get_db() as conn:
        conn.execute(
            """INSERT INTO payments
               (user_id, provider, kind, item_id, item_ref, currency,
                amount_minor, provider_order_id, status)
               VALUES (%s, 'razorpay', 'credit_pack', %s, %s, 'INR', %s, %s,
                       'created')""",
            (user_id, pack["id"], str(pack["name"]), amount_paise,
             order["order_id"]),
        )
        conn.commit()

    capture_payment_success(
        provider="razorpay", event="checkout_create",
        action="order_created", user_id=user_id, pack_id=pack["id"],
        order_id=order["order_id"],
    )
    return {
        "order_id": order["order_id"],
        "amount": order["amount"],
        "currency": "INR",
        "key_id": razorpay_service._get_key_id(),  # public — embedded in checkout.js
    }


@router.post("/verify")
async def verify_razorpay_payment(
    request: RazorpayVerifyRequest,
    authorization: Optional[str] = Header(None),
):
    """Verify the checkout.js handler signature and fulfill (idempotent)."""
    user_id = _get_user_id(authorization)
    _require_configured()

    if not razorpay_service.verify_payment_signature(
        request.razorpay_order_id,
        request.razorpay_payment_id,
        request.razorpay_signature,
    ):
        capture_payment_failure(
            provider="razorpay", event="verify",
            reason="invalid_signature", user_id=user_id,
            order_id=request.razorpay_order_id,
        )
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    # Ownership: the payments row was created server-side at order time;
    # reject if it belongs to someone else. Never trust client input.
    with get_db() as conn:
        row = conn.execute(
            "SELECT user_id FROM payments WHERE provider_order_id = %s AND provider = 'razorpay'",
            (request.razorpay_order_id,),
        ).fetchone()
    if row:
        owner = int((dict(row) if not isinstance(row, dict) else row)["user_id"])
        if owner != user_id:
            capture_payment_failure(
                provider="razorpay", event="verify",
                reason="ownership_mismatch", user_id=user_id,
                order_id=request.razorpay_order_id,
            )
            raise HTTPException(status_code=403, detail="Order does not belong to user")

    result = razorpay_service.fulfill_razorpay_payment(
        provider_order_id=request.razorpay_order_id,
        provider_payment_id=request.razorpay_payment_id,
    )
    if result.get("fulfilled") or result.get("already_fulfilled"):
        return {"success": True, **result}
    raise HTTPException(status_code=400, detail=result.get("reason", "verification failed"))


# ============================================================================
# Subscriptions (plans)
# ============================================================================

@router.post("/subscription")
async def create_razorpay_subscription(
    request: RazorpaySubscriptionRequest,
    authorization: Optional[str] = Header(None),
):
    user_id = _get_user_id(authorization)
    _require_configured()

    from services.plan_cache import get_plan
    plan = get_plan(request.plan_slug)
    if not plan:
        raise HTTPException(status_code=404, detail=f"Unknown plan: {request.plan_slug}")
    if not plan.get("price_monthly_cents"):
        raise HTTPException(status_code=400, detail="Plan is not purchasable")

    amount_paise = razorpay_service.usd_cents_to_inr_paise(
        int(plan["price_monthly_cents"])
    )
    try:
        rzp_plan_id = razorpay_service.ensure_razorpay_plan(
            request.plan_slug, plan.get("name", request.plan_slug), amount_paise
        )
        sub = razorpay_service.create_subscription(
            rzp_plan_id,
            notes={"user_id": str(user_id), "plan_slug": request.plan_slug},
        )
    except Exception as e:
        capture_payment_failure(
            provider="razorpay", event="subscription_create",
            reason="provider_api_error", user_id=user_id,
            plan=request.plan_slug,
        )
        raise HTTPException(status_code=502, detail=str(e)[:200])

    with get_db() as conn:
        conn.execute(
            """INSERT INTO payments
               (user_id, provider, kind, item_ref, currency, amount_minor,
                provider_subscription_id, status)
               VALUES (%s, 'razorpay', 'plan', %s, 'INR', %s, %s, 'created')""",
            (user_id, request.plan_slug, amount_paise, sub["subscription_id"]),
        )
        conn.commit()

    return {
        "subscription_id": sub["subscription_id"],
        "status": sub.get("status"),
        "key_id": razorpay_service._get_key_id(),
    }


@router.post("/subscription/verify")
async def verify_razorpay_subscription(
    request: RazorpaySubscriptionVerifyRequest,
    authorization: Optional[str] = Header(None),
):
    """Verify the subscription auth handler; reconcile status via API.

    eMandate/UPI AutoPay can leave the subscription 'authenticated' but not
    yet 'active' — the subscription.charged webhook completes fulfillment
    in that case; this endpoint fulfills immediately when already active.
    """
    user_id = _get_user_id(authorization)
    _require_configured()

    if not razorpay_service.verify_subscription_signature(
        request.razorpay_payment_id,
        request.razorpay_subscription_id,
        request.razorpay_signature,
    ):
        capture_payment_failure(
            provider="razorpay", event="subscription_verify",
            reason="invalid_signature", user_id=user_id,
            subscription_id=request.razorpay_subscription_id,
        )
        raise HTTPException(status_code=400, detail="Invalid subscription signature")

    try:
        entity = razorpay_service.fetch_subscription(request.razorpay_subscription_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)[:200])

    status = entity.get("status")
    notes = entity.get("notes") or {}
    notes_user = notes.get("user_id")
    try:
        notes_user_id = int(notes_user) if notes_user else None
    except (TypeError, ValueError):
        notes_user_id = None
    if notes_user_id is not None and notes_user_id != user_id:
        raise HTTPException(status_code=403, detail="Subscription does not belong to user")

    if status in ("active", "authenticated"):
        result = razorpay_service.fulfill_razorpay_subscription(entity)
        return {"success": True, "status": status, **result}

    return {"success": True, "status": status, "pending": True,
            "message": "Subscription pending activation; it will activate shortly."}
