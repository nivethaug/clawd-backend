#!/usr/bin/env python3
"""
Billing API Router — Endpoints for plans, credit balances, transactions,
credit pack purchases, and admin billing management.

Prefix: /api/billing
Auth: Bearer token (Authorization header) for all endpoints.
"""

import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from database_postgres import get_db

logger = logging.getLogger("api.billing")

router = APIRouter()


# ============================================================================
# Auth helper (lazy import to avoid circular dependency with app.py)
# ============================================================================

def _get_user_id(authorization: Optional[str] = None) -> int:
    from app import get_user_id_from_token
    return get_user_id_from_token(authorization)


def _audit(event: str, action: str, *, user_id: int, reason: Optional[str] = None, **ctx: Any) -> None:
    """Emit a PAYMENT_AUDIT line for the buy/checkout side of the flow.

    Imported lazily so a broken payment_sentry import never blocks checkout.
    Failure-class actions route to capture_payment_failure (which requires a
    reason); success-class actions route to capture_payment_success.
    """
    try:
        from services.payment_sentry import capture_payment_success, capture_payment_failure
    except Exception:
        return
    is_failure = action in {"checkout_failed", "provider_not_configured"}
    if is_failure:
        capture_payment_failure(
            event="checkout_" + action,
            reason=reason or action,
            user_id=user_id,
            **ctx,
        )
    else:
        capture_payment_success(
            event="checkout_" + action,
            action=action,
            user_id=user_id,
            **ctx,
        )


def _require_admin(user_id: int):
    from app import require_admin
    require_admin(user_id)


# ============================================================================
# Pydantic Models
# ============================================================================

class BuyCreditsRequest(BaseModel):
    pack_id: int


class AssignPlanRequest(BaseModel):
    user_id: int
    plan_slug: str


class AddCreditsRequest(BaseModel):
    user_id: int
    credit_type: str = "project_ai"
    amount: int
    source: str = "admin_grant"


class UpdateConfigRequest(BaseModel):
    key: str
    value: Any


# ============================================================================
# Public Endpoints (authenticated)
# ============================================================================

@router.get("/plans")
async def get_plans():
    """Get all active plans (public — for pricing page)."""
    from services.plan_cache import get_all_plans
    plans = get_all_plans()
    return {
        "plans": [
            {
                "slug": slug,
                "name": p.get("name"),
                "price_monthly_cents": p.get("price_monthly_cents"),
                "price_monthly_display": f"${p.get('price_monthly_cents', 0) / 100:.2f}",
                "max_active_projects": p.get("max_active_projects"),
                "features": p.get("features", []),
                "lemonsqueezy_variant_id": p.get("lemonsqueezy_variant_id"),
                "sort_order": p.get("sort_order", 0),
            }
            for slug, p in sorted(plans.items(), key=lambda x: x[1].get("sort_order", 0))
        ]
    }


@router.get("/summary")
async def get_billing_summary(authorization: Optional[str] = Header(None)):
    """Get the current user's complete billing summary (plan, balances, transactions)."""
    user_id = _get_user_id(authorization)
    from services.billing_service import get_user_billing_summary
    with get_db() as conn:
        return get_user_billing_summary(conn, user_id)


@router.get("/balances")
async def get_balances(authorization: Optional[str] = Header(None)):
    """Get the current user's credit balances."""
    user_id = _get_user_id(authorization)
    from services.billing_service import get_all_balances, get_monthly_remaining
    with get_db() as conn:
        balances = get_all_balances(conn, user_id)
    return {
        "balances": [
            {
                "credit_type": b["credit_type"],
                "monthly_limit": int(b["monthly_limit"]),
                "used": int(b["used"]),
                "monthly_remaining": get_monthly_remaining(b),
                "purchased": int(b.get("purchased", 0)),
                "total_available": max(0, get_monthly_remaining(b)) + int(b.get("purchased", 0)),
                "reset_date": b.get("reset_date"),
            }
            for b in balances
        ]
    }


@router.get("/transactions")
async def get_transactions(
    authorization: Optional[str] = Header(None),
    limit: int = 50,
    offset: int = 0,
):
    """Get the current user's credit transaction history."""
    user_id = _get_user_id(authorization)
    limit = min(limit, 200)
    with get_db() as conn:
        rows = conn.execute(
            """SELECT ct.*, o.code as operation_code, o.name as operation_name,
                      p.name as project_name, s.label as session_name
               FROM credit_transactions ct
               LEFT JOIN ai_operations o ON ct.operation_id = o.id
               LEFT JOIN projects p ON ct.project_id = p.id
               LEFT JOIN sessions s ON ct.session_id = s.id
               WHERE ct.user_id = %s
               ORDER BY ct.created_at DESC
               LIMIT %s OFFSET %s""",
            (user_id, limit, offset),
        ).fetchall()

    transactions = []
    for r in rows:
        t = dict(r) if not isinstance(r, dict) else r
        amount = int(t.get("amount", 0))
        status = t.get("status", "charged")
        op_name = t.get("operation_name", "")
        credit_type = t.get("credit_type", "")
        source = t.get("source", "")
        model_name = t.get("model", "")

        # Build a human-readable description
        if amount > 0:
            desc = f"Credit purchase (+{amount} {credit_type})"
        else:
            verb = {"reserved": "reserved", "refunded": "refunded", "charged": "deducted"}.get(status, "deducted")
            extra = f" from {source}" if source else ""
            extra += f" via {model_name}" if model_name else ""
            desc = f"{op_name or 'AI operation'} — {verb} {abs(amount)} {credit_type}{extra}"

        t["description"] = desc
        transactions.append(t)

    return {"transactions": transactions, "limit": limit, "offset": offset}


@router.get("/credit-packs")
async def get_credit_packs():
    """Get available credit packs for purchase (public)."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM credit_packs WHERE active = true ORDER BY sort_order"
        ).fetchall()
    packs = [dict(r) if not isinstance(r, dict) else r for r in rows]
    return {"credit_packs": packs}


# ============================================================================
# Checkout Endpoints
# ============================================================================

@router.post("/checkout/plan/{plan_slug}")
async def create_plan_checkout(
    plan_slug: str,
    authorization: Optional[str] = Header(None),
):
    """Create a LemonSqueezy checkout URL for a plan subscription."""
    user_id = _get_user_id(authorization)

    from services.plan_cache import get_plan
    plan = get_plan(plan_slug)
    if not plan:
        raise HTTPException(status_code=404, detail=f"Unknown plan: {plan_slug}")

    variant_id = plan.get("lemonsqueezy_variant_id")
    if not variant_id:
        raise HTTPException(status_code=400, detail="Plan has no LemonSqueezy variant configured")

    # Get user email
    with get_db() as conn:
        row = conn.execute("SELECT email FROM users WHERE id = %s", (user_id,)).fetchone()
        email = (dict(row) if row and not isinstance(row, dict) else row or {}).get("email", "")

    from services.lemonsqueezy_service import create_checkout_url
    import os as _os
    # Inline check — don't trust service module (import-time caching issues on server)
    _api_key = _os.getenv('LEMONSQUEEZY_API_KEY', '')
    _store_id = _os.getenv('LEMONSQUEEZY_STORE_ID', '')
    _configured = bool(_api_key and _store_id)
    logger.info(f"[LEMONSQUEZY] Plan checkout requested: plan={plan_slug}, variant_id={variant_id}, "
                f"API_KEY={'set (' + str(len(_api_key)) + ' chars)' if _api_key else 'MISSING'}, "
                f"STORE_ID={_store_id or 'MISSING'}, "
                f"is_configured={_configured}")
    if not _configured:
        _audit("checkout", "provider_not_configured", user_id=user_id, plan=plan_slug, variant_id=variant_id)
        raise HTTPException(status_code=503, detail="Payment provider not configured")

    result = create_checkout_url(
        variant_id=variant_id,
        user_id=user_id,
        user_email=email,
        custom_data={"purchase_type": "subscription", "plan_slug": plan_slug},
    )

    if result.get("error"):
        _audit("checkout", "checkout_failed", user_id=user_id, plan=plan_slug,
               variant_id=variant_id, reason=str(result.get("error"))[:120])
        raise HTTPException(status_code=502, detail=result["error"])

    _audit("checkout", "plan_checkout_created", user_id=user_id, plan=plan_slug,
           variant_id=variant_id, checkout_id=str(result.get("checkout_id", ""))[:40])
    return {"url": result.get("url"), "plan": plan_slug}


@router.post("/checkout/credits")
async def create_credits_checkout(
    request: BuyCreditsRequest,
    authorization: Optional[str] = Header(None),
):
    """Create a LemonSqueezy checkout URL for a credit pack purchase."""
    user_id = _get_user_id(authorization)

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM credit_packs WHERE id = %s AND active = true",
            (request.pack_id,),
        ).fetchone()
        email_row = conn.execute("SELECT email FROM users WHERE id = %s", (user_id,)).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Credit pack not found")

    pack = dict(row) if not isinstance(row, dict) else row
    variant_id = pack.get("lemonsqueezy_variant_id")
    if not variant_id:
        raise HTTPException(status_code=400, detail="Credit pack has no LemonSqueezy variant configured")

    email = (dict(email_row) if email_row and not isinstance(email_row, dict) else email_row or {}).get("email", "")

    from services.lemonsqueezy_service import create_checkout_url
    import os as _os
    # Inline check — don't trust service module (import-time caching issues on server)
    _api_key = _os.getenv('LEMONSQUEEZY_API_KEY', '')
    _store_id = _os.getenv('LEMONSQUEEZY_STORE_ID', '')
    _configured = bool(_api_key and _store_id)
    logger.info(f"[LEMONSQUEZY] Credit checkout requested: pack={pack.get('name')}, variant_id={variant_id}, "
                f"API_KEY={'set (' + str(len(_api_key)) + ' chars)' if _api_key else 'MISSING'}, "
                f"STORE_ID={_store_id or 'MISSING'}, "
                f"is_configured={_configured}")
    if not _configured:
        _audit("checkout", "provider_not_configured", user_id=user_id, pack_id=request.pack_id, variant_id=variant_id)
        raise HTTPException(status_code=503, detail="Payment provider not configured")

    result = create_checkout_url(
        variant_id=variant_id,
        user_id=user_id,
        user_email=email,
        custom_data={"purchase_type": "credit_pack", "pack_id": str(request.pack_id)},
    )

    if result.get("error"):
        _audit("checkout", "checkout_failed", user_id=user_id, pack_id=request.pack_id,
               variant_id=variant_id, reason=str(result.get("error"))[:120])
        raise HTTPException(status_code=502, detail=result["error"])

    _audit("checkout", "credit_checkout_created", user_id=user_id, pack_id=request.pack_id,
           variant_id=variant_id, checkout_id=str(result.get("checkout_id", ""))[:40])
    return {"url": result.get("url"), "pack": pack.get("name")}


# ============================================================================
# Admin Endpoints
# ============================================================================

@router.get("/admin/users")
async def admin_list_user_billing(
    authorization: Optional[str] = Header(None),
    limit: int = 100,
    offset: int = 0,
):
    """Admin: List all users with their billing summary (paginated)."""
    admin_id = _get_user_id(authorization)
    _require_admin(admin_id)

    with get_db() as conn:
        rows = conn.execute(
            """SELECT u.id, u.email, u.name, u.subscription_tier, p.slug as plan_slug,
                      p.name as plan_name
               FROM users u
               LEFT JOIN billing_plans p ON u.plan_id = p.id
               ORDER BY u.id
               LIMIT %s OFFSET %s""",
            (limit, offset),
        ).fetchall()
        users = [dict(r) if not isinstance(r, dict) else r for r in rows]

    return {"users": users, "limit": limit, "offset": offset}


@router.get("/admin/users/{user_id}")
async def admin_get_user_billing(user_id: int, authorization: Optional[str] = Header(None)):
    """Admin: Get a specific user's billing summary."""
    admin_id = _get_user_id(authorization)
    _require_admin(admin_id)

    from services.billing_service import get_user_billing_summary
    with get_db() as conn:
        return get_user_billing_summary(conn, user_id)


@router.post("/admin/assign-plan")
async def admin_assign_plan(request: AssignPlanRequest, authorization: Optional[str] = Header(None)):
    """Admin: Assign a plan to a user and sync their balances."""
    admin_id = _get_user_id(authorization)
    _require_admin(admin_id)

    from services.billing_service import assign_plan
    try:
        with get_db() as conn:
            plan = assign_plan(conn, request.user_id, request.plan_slug)
            conn.execute(
                "UPDATE users SET subscription_tier = %s WHERE id = %s",
                (request.plan_slug, request.user_id),
            )
            conn.commit()
        return {"success": True, "plan": plan.get("slug")}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/admin/add-credits")
async def admin_add_credits(request: AddCreditsRequest, authorization: Optional[str] = Header(None)):
    """Admin: Add credits to a user's balance (grant)."""
    admin_id = _get_user_id(authorization)
    _require_admin(admin_id)

    from services.billing_service import add_purchased_credits
    with get_db() as conn:
        add_purchased_credits(conn, request.user_id, request.credit_type, request.amount)
        conn.commit()
    return {"success": True, "user_id": request.user_id, "credit_type": request.credit_type, "amount": request.amount}


@router.get("/admin/operations")
async def admin_get_operations(authorization: Optional[str] = Header(None)):
    """Admin: Get all AI operations and their credit costs."""
    admin_id = _get_user_id(authorization)
    _require_admin(admin_id)

    from services.plan_cache import get_all_operations
    ops = get_all_operations()
    return {"operations": list(ops.values())}


@router.put("/admin/operations/{op_code}")
async def admin_update_operation(
    op_code: str,
    updates: Dict[str, Any],
    authorization: Optional[str] = Header(None),
):
    """Admin: Update an AI operation's credit cost or enabled status."""
    admin_id = _get_user_id(authorization)
    _require_admin(admin_id)

    allowed_fields = {"credit_cost", "enabled", "category", "credit_type", "name", "description"}
    set_clauses = []
    values = []
    for field, val in updates.items():
        if field in allowed_fields:
            set_clauses.append(f"{field} = %s")
            values.append(val)

    if not set_clauses:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    values.append(op_code)
    with get_db() as conn:
        conn.execute(
            f"UPDATE ai_operations SET {', '.join(set_clauses)} WHERE code = %s",
            values,
        )
        conn.commit()

    from services.plan_cache import invalidate
    invalidate("operations")
    return {"success": True, "operation": op_code}


@router.get("/admin/config")
async def admin_get_config(authorization: Optional[str] = Header(None)):
    """Admin: Get all billing config."""
    admin_id = _get_user_id(authorization)
    _require_admin(admin_id)

    with get_db() as conn:
        rows = conn.execute("SELECT key, value FROM billing_config ORDER BY key").fetchall()
    config = {r["key"]: r["value"] for r in rows}
    return {"config": config}


@router.put("/admin/config")
async def admin_update_config(request: UpdateConfigRequest, authorization: Optional[str] = Header(None)):
    """Admin: Update a billing config value (e.g., EARLY_ACCESS_MODE)."""
    admin_id = _get_user_id(authorization)
    _require_admin(admin_id)

    import json
    with get_db() as conn:
        conn.execute(
            """INSERT INTO billing_config (key, value, updated_by, updated_at)
               VALUES (%s, %s::jsonb, %s, NOW())
               ON CONFLICT (key) DO UPDATE SET
                 value = EXCLUDED.value,
                 updated_by = EXCLUDED.updated_by,
                 updated_at = NOW()""",
            (request.key, json.dumps(request.value), admin_id),
        )
        conn.commit()

    from services.plan_cache import invalidate
    invalidate("config")
    return {"success": True, "key": request.key, "value": request.value}


@router.post("/admin/reset-monthly")
async def admin_reset_monthly(authorization: Optional[str] = Header(None)):
    """Admin: Manually trigger monthly credit reset for all users."""
    admin_id = _get_user_id(authorization)
    _require_admin(admin_id)

    from services.billing_service import reset_monthly_credits
    with get_db() as conn:
        count = reset_monthly_credits(conn)
        conn.commit()
    return {"success": True, "reset_count": count}


@router.get("/admin/stats")
async def admin_billing_stats(authorization: Optional[str] = Header(None)):
    """Admin: Get aggregate billing statistics."""
    admin_id = _get_user_id(authorization)
    _require_admin(admin_id)

    with get_db() as conn:
        # Users by plan
        plan_rows = conn.execute(
            """SELECT p.slug, p.name, COUNT(u.id) as user_count
               FROM billing_plans p
               LEFT JOIN users u ON u.plan_id = p.id
               GROUP BY p.slug, p.name
               ORDER BY p.sort_order"""
        ).fetchall()

        # Total credits consumed this month
        consumed_row = conn.execute(
            """SELECT COALESCE(SUM(used), 0) as total_used
               FROM user_credit_balances
               WHERE credit_type = 'project_ai'"""
        ).fetchone()

        # Revenue this month (from subscriptions + packs)
        # Note: actual revenue tracked by LemonSqueezy, this is internal estimate
        tx_row = conn.execute(
            """SELECT COUNT(*) as count,
                      COALESCE(SUM(ABS(credits)), 0) as credits_movement
               FROM credit_transactions
               WHERE created_at >= DATE_TRUNC('month', NOW())"""
        ).fetchone()

    def _d(r):
        return dict(r) if r and not isinstance(r, dict) else (r or {})

    return {
        "plans": [_d(r) for r in plan_rows],
        "total_credits_used": int(_d(consumed_row).get("total_used", 0)),
        "transactions_this_month": int(_d(tx_row).get("count", 0)),
        "credits_movement_this_month": int(_d(tx_row).get("credits_movement", 0)),
    }
