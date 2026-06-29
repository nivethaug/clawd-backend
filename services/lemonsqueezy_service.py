"""
LemonSqueezy Service — Payment integration for plan subscriptions and
credit pack purchases.

If LEMONSQUEZY_API_KEY is not set, all methods degrade gracefully:
checkout URL generation returns a placeholder, webhook signature
verification is skipped (dev mode only).

Production: set LEMONSQUEZY_API_KEY + LEMONSQUEZY_WEBHOOK_SECRET +
LEMONSQUEZY_STORE_ID in environment.
"""

import os
import hmac
import hashlib
import logging
import json
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# --- Configuration (read dynamically so load_dotenv / PM2 restart picks up) ---
LEMONSQUEZY_API_BASE = "https://api.lemonsqueezy.com/v1"


def _get_api_key():
    return os.getenv("LEMONSQUEZY_API_KEY", "")


def _get_store_id():
    return os.getenv("LEMONSQUEZY_STORE_ID", "")


def _get_webhook_secret():
    return os.getenv("LEMONSQUEZY_WEBHOOK_SECRET", "")


def is_configured() -> bool:
    """Check if LemonSqueezy is fully configured (reads env dynamically)."""
    return bool(_get_api_key() and _get_store_id())


# ======================================================================
# Checkout URL Generation
# ======================================================================

def create_checkout_url(
    variant_id: str,
    user_id: int,
    user_email: str,
    custom_data: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Create a LemonSqueezy checkout URL for a product variant.

    Args:
        variant_id: LemonSqueezy variant ID (from plans/credit_packs table)
        user_id: User making the purchase
        user_email: User's email (for LemonSqueezy customer record)
        custom_data: Extra metadata to pass through webhook

    Returns:
        {"url": str, "checkout_id": str} or {"error": str}
    """
    # Read env vars fresh at call time (don't trust module-level caching)
    api_key = os.getenv("LEMONSQUEEZY_API_KEY", "")
    store_id = os.getenv("LEMONSQUEEZY_STORE_ID", "")

    if not api_key or not store_id:
        logger.warning(f"[LEMONSQUEEZY] Not configured — api_key={len(api_key)} chars, store_id={store_id or 'EMPTY'}")
        return {
            "error": "Payment provider not configured",
            "url": None,
            "dev_mode": True,
        }

    logger.info(f"[LEMONSQUEEZY] Creating checkout: api_key={len(api_key)} chars, store_id={store_id}")

    try:
        import httpx
    except ImportError:
        logger.error("[LEMONSQUEZY] httpx not installed")
        return {"error": "httpx not installed"}

    payload = {
        "data": {
            "type": "checkouts",
            "attributes": {
                "checkout_options": {
                    "embed": False,
                },
                "checkout_data": {
                    "email": user_email,
                    "custom": {
                        "user_id": str(user_id),
                        **(custom_data or {}),
                    },
                },
            },
            "relationships": {
                "store": {
                    "data": {
                        "type": "stores",
                        "id": store_id,
                    }
                },
                "variant": {
                    "data": {
                        "type": "variants",
                        "id": str(variant_id),
                    }
                },
            },
        }
    }

    try:
        resp = httpx.post(
            f"https://api.lemonsqueezy.com/v1/checkouts",
            headers={
                "Accept": "application/vnd.api+json",
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/vnd.api+json",
            },
            json=payload,
            timeout=15.0,
        )
        if resp.status_code >= 400:
            error_body = resp.text
            logger.error(f"[LEMONSQUEEZY] API error {resp.status_code}: {error_body}")
            return {"error": f"LemonSqueezy API error {resp.status_code}: {error_body[:200]}"}
        data = resp.json()
        attrs = data.get("data", {}).get("attributes", {})
        return {
            "url": attrs.get("url"),
            "checkout_id": data.get("data", {}).get("id"),
        }
    except Exception as e:
        logger.error(f"[LEMONSQUEZY] Checkout creation failed: {e}")
        return {"error": str(e)}


# ======================================================================
# Webhook Signature Verification
# ======================================================================

def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    """Verify the X-Signature header from a LemonSqueezy webhook.

    Uses HMAC-SHA256 with the webhook secret.
    In dev mode (no secret), returns True (INSECURE — never use in production).
    """
    webhook_secret = os.getenv("LEMONSQUEEZY_WEBHOOK_SECRET", "")
    if not webhook_secret:
        logger.warning("[LEMONSQUEZY] No webhook secret set — skipping verification (DEV ONLY)")
        return True

    expected = hmac.new(
        webhook_secret.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


# ======================================================================
# Webhook Event Processing
# ======================================================================

def process_webhook_event(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """Process a LemonSqueezy webhook event.

    Handles:
      - subscription_created / subscription_updated → assign plan
      - subscription_cancelled → downgrade to free
      - order_created (credit pack) → add purchased credits

    Returns:
        {"handled": bool, "action": str, ...}
    """
    from database_adapter import get_db
    from services.billing_service import assign_plan, add_purchased_credits
    from services.plan_cache import get_all_plans, invalidate

    event_name = event_data.get("meta", {}).get("event_name", "")
    custom_data = event_data.get("meta", {}).get("custom_data", {})
    user_id_str = custom_data.get("user_id")
    user_id = int(user_id_str) if user_id_str else None

    if not user_id:
        logger.warning(f"[LEMONSQUEZY] Webhook has no user_id in custom_data: {event_name}")
        return {"handled": False, "reason": "no user_id"}

    attrs = event_data.get("data", {}).get("attributes", {})

    # --- Subscription events ---
    if event_name in ("subscription_created", "subscription_updated"):
        variant_id = str(attrs.get("variant_id", ""))
        plans = get_all_plans()
        plan = None
        for slug, p in plans.items():
            if str(p.get("lemonsqueezy_variant_id", "")) == variant_id:
                plan = p
                break

        if not plan:
            logger.warning(f"[LEMONSQUEZY] No plan matches variant_id={variant_id}")
            return {"handled": False, "reason": "no matching plan"}

        # Record subscription + assign plan
        with get_db() as conn:
            conn.execute(
                """INSERT INTO subscriptions
                   (user_id, plan_id, lemonsqueezy_subscription_id, lemonsqueezy_order_id,
                    status, current_period_end, cancel_at_period_end)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (lemonsqueezy_subscription_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    current_period_end = EXCLUDED.current_period_end,
                    updated_at = NOW()""",
                (
                    user_id,
                    plan["id"],
                    attrs.get("id", ""),  # subscription ID
                    "",
                    "active",
                    attrs.get("renews_at"),
                    attrs.get("cancelled", False),
                ),
            )
            # Update users.subscription_tier to match plan slug
            conn.execute(
                "UPDATE users SET subscription_tier = %s WHERE id = %s",
                (plan["slug"], user_id),
            )
            conn.commit()

            assign_plan(conn, user_id, plan["slug"])
            conn.commit()

        invalidate("all")
        logger.info(f"[LEMONSQUEZY] Assigned plan {plan['slug']} to user {user_id}")
        return {"handled": True, "action": "plan_assigned", "plan": plan["slug"]}

    # --- Subscription cancelled ---
    if event_name == "subscription_cancelled":
        with get_db() as conn:
            conn.execute(
                """UPDATE subscriptions SET status = 'cancelled', updated_at = NOW()
                   WHERE user_id = %s AND status = 'active'""",
                (user_id,),
            )
            conn.execute(
                "UPDATE users SET subscription_tier = 'free' WHERE id = %s",
                (user_id,),
            )
            conn.commit()
            assign_plan(conn, user_id, "free")
            conn.commit()

        invalidate("all")
        logger.info(f"[LEMONSQUEZY] Downgraded user {user_id} to free (cancelled)")
        return {"handled": True, "action": "downgraded_to_free"}

    # --- Order created (one-time purchase: credit pack) ---
    if event_name == "order_created":
        # Variant ID may be in first_order_item, or at top-level attributes
        variant_id = ""
        first_item = attrs.get("first_order_item", {})
        if isinstance(first_item, dict):
            variant_id = str(first_item.get("variant_id", ""))
        if not variant_id:
            variant_id = str(attrs.get("variant_id", ""))

        # Fallback: custom_data may contain pack_id from the checkout request
        pack_id = custom_data.get("pack_id")

        with get_db() as conn:
            row = None
            if variant_id:
                row = conn.execute(
                    "SELECT credits, credit_type FROM credit_packs WHERE lemonsqueezy_variant_id = %s AND active = true",
                    (variant_id,),
                ).fetchone()
            if not row and pack_id:
                # Match by pack_id from checkout custom_data
                row = conn.execute(
                    "SELECT credits, credit_type FROM credit_packs WHERE id = %s AND active = true",
                    (int(pack_id),),
                ).fetchone()
            if not row:
                logger.warning(
                    f"[LEMONSQUEEZY] No credit pack for variant_id={variant_id}, "
                    f"pack_id={pack_id} (user {user_id})"
                )
                return {"handled": False, "reason": "no matching credit pack",
                        "variant_id": variant_id, "pack_id": pack_id}

            d = dict(row) if not isinstance(row, dict) else row
            add_purchased_credits(conn, user_id, d["credit_type"], int(d["credits"]))
            conn.commit()

        invalidate("all")
        logger.info(f"[LEMONSQUEEZY] Added {d['credits']} {d['credit_type']} credits to user {user_id}")
        return {"handled": True, "action": "credits_added", "credits": int(d["credits"])}

    logger.info(f"[LEMONSQUEZY] Unhandled event: {event_name}")
    return {"handled": False, "reason": f"unhandled event: {event_name}"}


# ======================================================================
# Customer Portal URL
# ======================================================================

def get_customer_portal_url(user_email: str) -> Optional[str]:
    """Get the LemonSqueezy customer portal URL for managing subscriptions."""
    if not is_configured():
        return None
    # LemonSqueezy customer portal is a configured URL per store
    return os.getenv("LEMONSQUEZY_CUSTOMER_PORTAL_URL")
