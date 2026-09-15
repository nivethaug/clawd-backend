"""
Promo Service — percent-off codes for subscription plans (first charge only).

Scope (deliberate):
- Subscription plans only (Pro/Dream). Credit packs are untouched.
- Percent-only discounts.
- FIRST CHARGE ONLY: renewals bill the full plan price.
  - Razorpay (INR): a native Razorpay coupon (percent, duration 1 month) is
    created lazily per promo code and passed to subscription creation —
    Razorpay's billing engine discounts only the first invoice.
  - LemonSqueezy (USD): the checkout is created with a custom first-order
    price (product_options.price); renewals bill the variant's normal price.

Advertised = charged: preview prices returned by validate_promo() use the
SAME conversion choke point (razorpay_service.usd_cents_to_inr_paise) that
produces the real Razorpay amounts, and the USD preview cents are exactly
what is sent to LemonSqueezy as the custom price.

Redemption lifecycle:
  pending row at checkout creation → status 'redeemed' + redeemed_count++
  on confirmed fulfillment (verify handler or webhook). UNIQUE(promo_id,
  user_id) makes both fulfillment paths idempotent.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# billing_config key for the promo code → Razorpay coupon id map
PROMO_COUPON_MAP_KEY = "PROMO_RAZORPAY_COUPON_MAP"


class PromoValidationError(Exception):
    """Typed validation failure — `reason` is machine-readable, `message`
    is a clear user-facing string."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


def normalize_code(code: str) -> str:
    """Promo codes are case-insensitive; stored uppercase."""
    return (code or "").strip().upper()


# ======================================================================
# Lookup + validation
# ======================================================================

def find_promo(conn, code: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM promo_codes WHERE code = %s",
        (normalize_code(code),),
    ).fetchone()
    if not row:
        return None
    return dict(row) if not isinstance(row, dict) else row


def validate_promo(conn, code: str, user_id: int, plan_slug: str) -> Dict[str, Any]:
    """Validate a promo code for a user + plan and compute the preview prices.

    Returns {promo, original_cents, discounted_cents, original_inr_paise,
    discounted_inr_paise, ...display strings}.
    Raises PromoValidationError with a clear message on any failure.
    """
    promo = find_promo(conn, code)
    if not promo:
        raise PromoValidationError("not_found", "Invalid promo code.")

    now = datetime.utcnow()
    if not promo.get("active"):
        raise PromoValidationError("inactive", "This promo code is no longer active.")
    starts_at = promo.get("starts_at")
    if starts_at and now < starts_at:
        raise PromoValidationError("not_yet_valid", "This promo code is not active yet.")
    expires_at = promo.get("expires_at")
    if expires_at and now > expires_at:
        raise PromoValidationError("expired", "This code has expired.")

    max_redemptions = promo.get("max_redemptions")
    if max_redemptions is not None and int(promo.get("redeemed_count") or 0) >= int(max_redemptions):
        raise PromoValidationError("fully_redeemed", "This code has reached its redemption limit.")

    per_user_limit = int(promo.get("per_user_limit") or 1)
    used = conn.execute(
        "SELECT COUNT(*) AS n FROM promo_redemptions WHERE promo_id = %s AND user_id = %s",
        (promo["id"], user_id),
    ).fetchone()
    used_n = int((used.get("n") if isinstance(used, dict) else used[0]) or 0)
    if used_n >= per_user_limit:
        raise PromoValidationError("already_used", "You've already used this promo code.")

    # Plan price (USD cents) — plans only, free/enterprise are not purchasable.
    plan_row = conn.execute(
        "SELECT slug, name, price_monthly_cents FROM billing_plans WHERE slug = %s",
        (plan_slug,),
    ).fetchone()
    if not plan_row or not plan_row.get("price_monthly_cents"):
        raise PromoValidationError(
            "plan_not_purchasable", "Promo codes apply to paid subscription plans only."
        )
    original_cents = int(plan_row["price_monthly_cents"])

    percent = float(promo["discount_percent"])
    discounted_cents = int(round(original_cents * (1 - percent / 100.0)))
    if discounted_cents < 50:
        # Guard against near-free first charges (LS min price / abuse).
        discounted_cents = 50

    # INR previews reuse the exact conversion that produces real Razorpay
    # amounts — the launch discount stacks multiplicatively with the promo.
    from services.razorpay_service import inr_display, usd_cents_to_inr_paise

    original_inr_paise = usd_cents_to_inr_paise(original_cents)
    discounted_inr_paise = usd_cents_to_inr_paise(discounted_cents)

    return {
        "promo": promo,
        "plan_slug": plan_slug,
        "discount_percent": percent,
        "original_cents": original_cents,
        "discounted_cents": discounted_cents,
        "original_usd_display": f"${original_cents / 100:.2f}",
        "discounted_usd_display": f"${discounted_cents / 100:.2f}",
        "original_inr_paise": original_inr_paise,
        "discounted_inr_paise": discounted_inr_paise,
        "original_inr_display": inr_display(original_inr_paise),
        "discounted_inr_display": inr_display(discounted_inr_paise),
    }


# ======================================================================
# Razorpay native coupon mirror (first charge only)
# ======================================================================

def _load_coupon_map() -> Dict[str, str]:
    from services.plan_cache import get_billing_config

    val = get_billing_config(PROMO_COUPON_MAP_KEY, {})
    return val if isinstance(val, dict) else {}


def ensure_razorpay_coupon(promo: Dict[str, Any]) -> str:
    """Find or create the Razorpay coupon mirroring a promo code.

    The coupon is percent-off with duration 1 month — Razorpay discounts
    only the first invoice of the subscription, renewals bill full price.
    Returns the Razorpay coupon_id.
    """
    from database_adapter import get_db

    code = normalize_code(promo["code"])
    cached = _load_coupon_map().get(code)
    if cached:
        return str(cached)

    max_redemptions = promo.get("max_redemptions")
    remaining = (
        int(max_redemptions) - int(promo.get("redeemed_count") or 0)
        if max_redemptions is not None
        else None
    )
    # Razorpay requires 1 <= max_count. Unlimited promos use a high cap —
    # our DB (promo_redemptions) remains the authoritative limiter.
    max_count = remaining if remaining and remaining >= 1 else 1000

    from services.razorpay_service import _api

    data = _api("POST", "/coupons", json_body={
        "name": f"DREAMAGENT-{code}"[:40],
        "description": (promo.get("description") or f"{float(promo['discount_percent']):g}% off first payment")[:250],
        "discount_type": "percent",
        "percent": float(promo["discount_percent"]),
        "duration_type": "months",
        "duration": 1,
        "max_count": max_count,
    })
    coupon_id = str(data["id"])

    try:
        with get_db() as conn:
            mapping = _load_coupon_map()
            mapping[code] = coupon_id
            conn.execute(
                """INSERT INTO billing_config (key, value)
                   VALUES (%s, %s::jsonb)
                   ON CONFLICT (key) DO UPDATE SET
                     value = EXCLUDED.value, updated_at = NOW()""",
                (PROMO_COUPON_MAP_KEY, json.dumps(mapping)),
            )
            conn.commit()
    except Exception as e:
        logger.warning("[PROMO] failed to cache coupon map: %s", e)

    from services.plan_cache import invalidate
    invalidate("config")
    return coupon_id


# ======================================================================
# Redemptions (idempotent)
# ======================================================================

def mark_pending_redemption(conn, promo_id: int, user_id: int, provider: str,
                             external_subscription_id: Optional[str]) -> bool:
    """Insert a pending redemption row. Returns True if newly inserted."""
    cur = conn.execute(
        """INSERT INTO promo_redemptions
             (promo_id, user_id, provider, external_subscription_id, status)
           VALUES (%s, %s, %s, %s, 'pending')
           ON CONFLICT (promo_id, user_id) DO NOTHING
           RETURNING id""",
        (promo_id, user_id, provider, external_subscription_id),
    )
    row = cur.fetchone() if cur else None
    inserted = row is not None
    if inserted:
        conn.commit()
    return inserted


def mark_redeemed(conn, promo_id: int, user_id: int,
                  external_subscription_id: Optional[str]) -> bool:
    """Transition pending → redeemed and bump redeemed_count exactly once.

    Safe to call from BOTH the verify handler and the webhook — the
    conditional UPDATE makes it idempotent.
    """
    cur = conn.execute(
        """UPDATE promo_redemptions
           SET status = 'redeemed',
               external_subscription_id = COALESCE(%s, external_subscription_id)
           WHERE promo_id = %s AND user_id = %s AND status <> 'redeemed'
           RETURNING id""",
        (external_subscription_id, promo_id, user_id),
    )
    row = cur.fetchone() if cur else None
    if row is None:
        return False
    conn.execute(
        "UPDATE promo_codes SET redeemed_count = redeemed_count + 1 WHERE id = %s",
        (promo_id,),
    )
    conn.commit()
    return True


def find_redemption_by_subscription(conn, external_subscription_id: str) -> Optional[Dict[str, Any]]:
    """Webhook-side lookup: find a redemption by provider subscription id."""
    row = conn.execute(
        "SELECT * FROM promo_redemptions WHERE external_subscription_id = %s LIMIT 1",
        (external_subscription_id,),
    ).fetchone()
    if not row:
        return None
    return dict(row) if not isinstance(row, dict) else row
