#!/usr/bin/env python3
"""Dedicated Worker add-on — user-facing endpoints.

Mounted at: /api/billing/dedicated.

The add-on is a Razorpay subscription to the 'dedicated-worker' pseudo-plan
(is_addon=true — never replaces the user's main plan). Purchase goes through
the EXISTING /api/billing/razorpay/subscription endpoint (plan_slug
'dedicated-worker', optional region); this router exposes status + cancel.

Isolation engine: services/worker_registry.py + the claim/stamp/proxy routing
shipped with the worker_nodes registry.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from utils.auth_helpers import get_user_id_from_token

logger = logging.getLogger("api.dedicated")

router = APIRouter()

ADDON_SLUG = "dedicated-worker"


@router.get("/status")
async def dedicated_status(authorization: Optional[str] = Header(None)):
    """Current dedication + region availability + price (for the upgrade card)."""
    user_id = get_user_id_from_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    from services import worker_registry
    from services.plan_cache import get_plan

    dedication = worker_registry.get_user_dedication(user_id)
    plan = get_plan(ADDON_SLUG) or {}
    return {
        "active": bool(dedication and dedication.get("dedicated_worker_id")),
        "worker": {
            "id": dedication.get("dedicated_worker_id"),
            "name": dedication.get("worker_name"),
            "region": dedication.get("region"),
        } if dedication else None,
        "dedicated_until": dedication.get("dedicated_until") if dedication else None,
        "regions_available": worker_registry.pool_summary(),
        "price_monthly_cents": plan.get("price_monthly_cents"),
    }


@router.post("/admin-activate")
async def dedicated_admin_activate(authorization: Optional[str] = Header(None)):
    """Admin bypass: claim a pool worker WITHOUT payment.

    Admin-grant semantics — no subscription, dedicated_until=NULL (never
    swept). Release via the admin bind endpoint (worker_id null) or the
    card's Cancel button (which falls back to release for admins).
    """
    user_id = get_user_id_from_token(authorization)
    from app import require_admin
    require_admin(user_id)

    from database_adapter import get_db
    from services import worker_registry

    if worker_registry.get_user_dedication(user_id):
        raise HTTPException(status_code=409, detail="Dedicated worker already active for this account")
    node_id = worker_registry.claim_pool_worker(user_id, None)
    if not node_id:
        # Pool empty → on-demand: mark pending (the claim sweep activates the
        # moment a worker enrolls) and wake the fleet manager to spawn one.
        from database_postgres import get_db as _gdb

        with _gdb() as conn:
            conn.execute(
                "UPDATE users SET dedicated_pending = TRUE WHERE id = %s",
                (user_id,),
            )
            conn.commit()
        try:
            from services.fleet_manager import fleet_tick
            import threading
            threading.Thread(target=fleet_tick, daemon=True).start()
        except Exception:
            pass
        return {
            "success": True,
            "spawning": True,
            "message": "No idle workers — spawning a dedicated worker now (~3-5 min). The card activates automatically when it's ready.",
        }
    return {"success": True, "worker_id": node_id, "message": f"Admin-activated dedicated worker '{node_id}' (no charge)"}


@router.post("/cancel")
async def dedicated_cancel(authorization: Optional[str] = Header(None)):
    """Cancel the dedicated-worker subscription at Razorpay.

    The worker stays bound until dedicated_until (paid term end); the billing
    cron then returns it to the pool. The user's main plan is untouched.
    """
    user_id = get_user_id_from_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    from database_adapter import get_db
    from services import razorpay_service

    with get_db() as conn:
        row = conn.execute(
            """SELECT s.external_subscription_id
               FROM subscriptions s
               JOIN billing_plans p ON p.id = s.plan_id
               WHERE s.user_id = %s AND s.provider = 'razorpay'
                 AND p.slug = %s AND s.status = 'active'
               ORDER BY s.updated_at DESC LIMIT 1""",
            (user_id, ADDON_SLUG),
        ).fetchone()

    # No Razorpay subscription: admin-granted (or already lapsed) dedication —
    # release the worker immediately for admins instead of a dead-end 404.
    if not row:
        from app import _is_admin_user
        if _is_admin_user(user_id):
            from services import worker_registry
            released = worker_registry.release_user_worker(user_id)
            if released:
                return {"success": True, "message": f"Dedicated worker '{released}' released (admin grant)."}
        raise HTTPException(status_code=404, detail="No active dedicated-worker subscription")
    sub_id = (dict(row) if not isinstance(row, dict) else row)["external_subscription_id"]

    try:
        razorpay_service.cancel_subscription(sub_id)
    except Exception as exc:
        # Provider cancel FAILED: do NOT flip local state — a locally
        # cancelled row would be resurrected by the next subscription.charged
        # webhook while Razorpay keeps billing. Surface the error instead.
        logger.error("[DEDICATED] Razorpay cancel failed for %s: %s", sub_id, exc)
        raise HTTPException(
            status_code=502,
            detail="Could not cancel at the payment provider — nothing changed. Please retry or contact support.",
        )
    razorpay_service.cancel_razorpay_subscription_locally(sub_id, "cancelled")
    return {"success": True, "message": "Dedicated worker cancelled — active until the end of the paid term."}
