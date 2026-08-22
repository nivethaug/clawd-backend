"""
Razorpay Service — INR payments for Indian customers (payment gateway +
subscriptions).

Strictly isolated from the LemonSqueezy USD flow:
- No existing billing function is modified here. Fulfillment REUSES
  billing_service.add_purchased_credits / assign_plan (read-only reuse).
- If RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET / RAZORPAY_WEBHOOK_SECRET are
  not set, is_configured() is False and every Razorpay endpoint returns
  503 — the feature effectively does not exist and the USD flow is
  untouched. Rollback = unset the env vars.

Env (read dynamically, same as lemonsqueezy_service):
  RAZORPAY_KEY_ID        — API key id (rzp_test_… / rzp_live_…)
  RAZORPAY_KEY_SECRET    — API key secret
  RAZORPAY_WEBHOOK_SECRET — webhook signing secret

Pricing: INR amounts are DERIVED from the USD prices already stored in
billing_plans / credit_packs, using the admin-editable billing_config key
INR_PER_USD (seeded at 88). The reference rate is deliberately a single
knob the admin can raise to absorb FX drift and 18% GST — displayed INR
prices are GST-inclusive. Rounding produces psychological ₹X99 endings.

Signatures (all HMAC-SHA256, compared with hmac.compare_digest):
  checkout handler : HMAC(KEY_SECRET, "order_id|payment_id")
  subscription auth: HMAC(KEY_SECRET, "payment_id|subscription_id")
  webhook          : HMAC(WEBHOOK_SECRET, raw_body)   (fail-closed)
"""

import hashlib
import hmac
import json
import logging
import os
from typing import Any, Dict, Optional, Tuple

from services.payment_sentry import capture_payment_failure, capture_payment_success

logger = logging.getLogger(__name__)

RAZORPAY_API_BASE = "https://api.razorpay.com/v1"

# Razorpay requires total_count on subscriptions (1..999) — there is no
# literal "until cancelled". 60 monthly cycles (~5 years) approximates
# until-cancelled without surprising users with a mid-year downgrade.
SUBSCRIPTION_TOTAL_COUNT = 60


# ======================================================================
# Configuration (dynamic env reads — PM2 restart / load_dotenv safe)
# ======================================================================

def _get_key_id() -> str:
    return os.getenv("RAZORPAY_KEY_ID", "")


def _get_key_secret() -> str:
    return os.getenv("RAZORPAY_KEY_SECRET", "")


def _get_webhook_secret() -> str:
    return os.getenv("RAZORPAY_WEBHOOK_SECRET", "")


def is_configured() -> bool:
    """True only when both API credentials are present."""
    return bool(_get_key_id() and _get_key_secret())


# ======================================================================
# INR pricing (derived from USD, admin-tunable rate)
# ======================================================================

DEFAULT_INR_PER_USD = 88


def get_inr_per_usd() -> int:
    """Read INR_PER_USD from billing_config (60s plan-cache TTL)."""
    from services.plan_cache import get_billing_config
    val = get_billing_config("INR_PER_USD", DEFAULT_INR_PER_USD)
    try:
        rate = int(val)
    except (TypeError, ValueError):
        return DEFAULT_INR_PER_USD
    return rate if rate >= 1 else DEFAULT_INR_PER_USD


def usd_cents_to_inr_paise(usd_cents: int) -> int:
    """Derive an INR paise amount from a USD-cents price.

    Rounding for psychological endings: >= ₹200 rounds to the nearest
    hundred minus one (₹1,699); below that to the nearest ten minus one.
    Zero/negative prices return 0 (free/custom plans are not purchasable
    via Razorpay).
    """
    if not usd_cents or usd_cents <= 0:
        return 0
    rate = get_inr_per_usd()
    rupees = (usd_cents / 100) * rate
    if rupees >= 200:
        return (int(round(rupees / 100)) * 100 - 1) * 100
    return (int(round(rupees / 10)) * 10 - 1) * 100


def inr_display(paise: Optional[int]) -> str:
    """Format paise as ₹ display string (Indian digit grouping)."""
    if paise is None:
        return "Custom"
    rupees = paise // 100
    return f"₹{rupees:,}"


# ======================================================================
# HTTP (Basic auth; sync httpx — same style as lemonsqueezy_service)
# ======================================================================

def _api(method: str, path: str, *, json_body: Optional[Dict[str, Any]] = None,
         params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Call the Razorpay REST API. Raises RuntimeError on HTTP >= 400."""
    import httpx

    key_id, key_secret = _get_key_id(), _get_key_secret()
    if not key_id or not key_secret:
        raise RuntimeError("Razorpay not configured")

    resp = httpx.request(
        method,
        f"{RAZORPAY_API_BASE}{path}",
        auth=(key_id, key_secret),
        json=json_body,
        params=params,
        timeout=15.0,
    )
    if resp.status_code >= 400:
        # Log status + short body only — never echo credentials.
        logger.error(
            "[RAZORPAY] API %s %s → HTTP %s: %s",
            method, path, resp.status_code, resp.text[:200],
        )
        raise RuntimeError(f"Razorpay API error {resp.status_code}: {resp.text[:200]}")
    return resp.json() if resp.content else {}


# ======================================================================
# Orders (one-time payments — credit packs)
# ======================================================================

def create_order(amount_paise: int, receipt: str, notes: Dict[str, str]) -> Dict[str, Any]:
    """Create a Razorpay order (amount in paise, auto-capture).

    receipt must be <= 40 chars. notes ride through to the webhook and are
    the ONLY trusted linkage between a payment and our user/item — set them
    at order creation, never trust client-supplied values at verify time.
    """
    body = {
        "amount": int(amount_paise),
        "currency": "INR",
        "receipt": str(receipt)[:40],
        "payment_capture": 1,
        "notes": {str(k): str(v) for k, v in (notes or {}).items()},
    }
    data = _api("POST", "/orders", json_body=body)
    return {
        "order_id": data.get("id"),
        "amount": data.get("amount"),
        "currency": data.get("currency", "INR"),
        "status": data.get("status"),
    }


# ======================================================================
# Signature verification (checkout handler + webhook)
# ======================================================================

def _hmac_hex(secret: str, message: str) -> str:
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """Verify checkout.js handler success: HMAC(KEY_SECRET, order|payment)."""
    secret = _get_key_secret()
    if not secret or not all([order_id, payment_id, signature]):
        logger.warning(
            "[RAZORPAY] payment signature rejected: missing inputs "
            "(has_secret=%s)", bool(secret)
        )
        return False
    expected = _hmac_hex(secret, f"{order_id}|{payment_id}")
    ok = hmac.compare_digest(expected, str(signature).strip().lower())
    if not ok:
        logger.warning("[RAZORPAY] payment signature mismatch (order=%s)", order_id)
    return ok


def verify_subscription_signature(payment_id: str, subscription_id: str, signature: str) -> bool:
    """Verify subscription auth handler: HMAC(KEY_SECRET, payment|subscription)."""
    secret = _get_key_secret()
    if not secret or not all([payment_id, subscription_id, signature]):
        logger.warning(
            "[RAZORPAY] subscription signature rejected: missing inputs "
            "(has_secret=%s)", bool(secret)
        )
        return False
    expected = _hmac_hex(secret, f"{payment_id}|{subscription_id}")
    ok = hmac.compare_digest(expected, str(signature).strip().lower())
    if not ok:
        logger.warning(
            "[RAZORPAY] subscription signature mismatch (sub=%s)", subscription_id
        )
    return ok


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    """Verify the X-Razorpay-Signature header over the RAW body.

    Fails closed: no secret configured → rejected unless the explicit
    WEBHOOK_DEV_BYPASS=1 dev override is set (never in production).
    """
    webhook_secret = _get_webhook_secret()
    if not webhook_secret:
        if os.getenv("WEBHOOK_DEV_BYPASS", "").lower() in ("1", "true", "yes"):
            logger.warning(
                "[RAZORPAY] RAZORPAY_WEBHOOK_SECRET not set and "
                "WEBHOOK_DEV_BYPASS=1 — accepting unverified webhook "
                "(DEV ONLY, never in production)"
            )
            return True
        logger.error("[RAZORPAY] RAZORPAY_WEBHOOK_SECRET not configured — rejecting webhook")
        return False

    if not signature:
        logger.warning("[RAZORPAY] webhook rejected: missing X-Razorpay-Signature")
        return False

    expected = hmac.new(
        webhook_secret.encode(), raw_body or b"", hashlib.sha256
    ).hexdigest()
    try:
        sig_norm = str(signature).strip().lower()
    except Exception:
        return False
    if not hmac.compare_digest(expected, sig_norm):
        logger.warning(
            "[RAZORPAY] webhook signature mismatch "
            "(expected_prefix=%s got_prefix=%s)",
            expected[:8], sig_norm[:8],
        )
        return False
    return True


# ======================================================================
# Plans + Subscriptions (Razorpay-side recurring objects)
# ======================================================================

def _load_plan_map() -> Dict[str, Dict[str, Any]]:
    from services.plan_cache import get_billing_config
    val = get_billing_config("RAZORPAY_PLAN_MAP", None)
    return val if isinstance(val, dict) else {}


def _save_plan_map(conn, plan_map: Dict[str, Dict[str, Any]]) -> None:
    """Persist the slug→plan_id cache in billing_config (RAZORPAY_PLAN_MAP)."""
    conn.execute(
        """INSERT INTO billing_config (key, value)
           VALUES ('RAZORPAY_PLAN_MAP', %s::jsonb)
           ON CONFLICT (key) DO UPDATE SET
             value = EXCLUDED.value, updated_at = NOW()""",
        (json.dumps(plan_map),),
    )
    conn.commit()


def ensure_razorpay_plan(slug: str, name: str, amount_paise: int) -> str:
    """Find or create the Razorpay plan for a billing_plans slug.

    Order of lookup: billing_config cache (exact amount match) → Razorpay
    plan list (match by notes.slug) → create. Returns the Razorpay plan_id.
    """
    from database_adapter import get_db

    cached = _load_plan_map().get(slug)
    if cached and int(cached.get("amount", 0)) == int(amount_paise):
        return str(cached["plan_id"])

    # Remote lookup — matches plans created before the cache existed.
    found = None
    try:
        remote = _api("GET", "/plans", params={"count": 100})
        for item in remote.get("items", []):
            notes = item.get("notes") or {}
            if notes.get("slug") == slug:
                found = item
                break
    except Exception as e:
        logger.warning("[RAZORPAY] plan list lookup failed, will create: %s", e)

    if found and int(found.get("item", {}).get("amount", 0)) == int(amount_paise):
        plan_id = str(found["id"])
    else:
        data = _api("POST", "/plans", json_body={
            "period": "monthly",
            "interval": 1,
            "item": {
                "name": str(name)[:100],
                "amount": int(amount_paise),
                "currency": "INR",
                "description": f"{name} monthly (INR)",
            },
            "notes": {"slug": slug},
        })
        plan_id = str(data["id"])

    try:
        with get_db() as conn:
            plan_map = _load_plan_map()
            plan_map[slug] = {"plan_id": plan_id, "amount": int(amount_paise)}
            _save_plan_map(conn, plan_map)
    except Exception as e:
        # Cache failure is non-fatal — the remote lookup above still works.
        logger.warning("[RAZORPAY] failed to cache plan map: %s", e)

    from services.plan_cache import invalidate
    invalidate("config")
    return plan_id


def create_subscription(plan_id: str, notes: Dict[str, str]) -> Dict[str, Any]:
    """Create a Razorpay subscription (monthly, 60 cycles ≈ until-cancelled).

    notes MUST carry user_id + plan_slug — they are the trusted linkage
    used by the subscription.charged webhook to fulfill.
    """
    body = {
        "plan_id": plan_id,
        "total_count": SUBSCRIPTION_TOTAL_COUNT,
        "notes": {str(k): str(v) for k, v in (notes or {}).items()},
    }
    data = _api("POST", "/subscriptions", json_body=body)
    return {
        "subscription_id": data.get("id"),
        "status": data.get("status"),
        "short_url": data.get("short_url"),
    }


def fetch_subscription(subscription_id: str) -> Dict[str, Any]:
    return _api("GET", f"/subscriptions/{subscription_id}")


def cancel_subscription(subscription_id: str) -> Dict[str, Any]:
    return _api("POST", f"/subscriptions/{subscription_id}/cancel",
                json_body={"cancel_at_cycle_end": 0})


# ======================================================================
# Fulfillment (idempotent — shared by /verify handler and webhooks)
# ======================================================================

def fulfill_razorpay_payment(
    *,
    provider_order_id: str,
    provider_payment_id: str,
    raw_event: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Idempotently fulfill a captured one-time payment (credit pack).

    Called from BOTH the client-side verify endpoint and the
    payment.captured webhook — whichever runs first wins; the loser gets
    {"already_fulfilled": True} via the payments.status guard.
    Never trusts client-supplied user ids: the payments row created at
    order time is the source of truth.
    """
    from database_adapter import get_db
    from services.billing_service import add_purchased_credits
    from services.plan_cache import invalidate

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM payments WHERE provider_order_id = %s AND provider = 'razorpay'",
            (provider_order_id,),
        ).fetchone()
        if not row:
            logger.warning("[RAZORPAY] fulfill: no payments row for order=%s", provider_order_id)
            return {"fulfilled": False, "reason": "unknown_order"}

        p = dict(row) if not isinstance(row, dict) else row
        user_id = int(p["user_id"])

        if p.get("kind") != "credit_pack":
            logger.error(
                "[RAZORPAY] fulfill: order=%s has unexpected kind=%s",
                provider_order_id, p.get("kind"),
            )
            return {"fulfilled": False, "reason": "unexpected_kind"}

        # Validate the pack BEFORE claiming the paid transition — if the pack
        # vanished, we leave the row retryable ('created'), not stuck 'paid'.
        pack = conn.execute(
            "SELECT credits, credit_type FROM credit_packs WHERE id = %s",
            (int(p["item_id"]),),
        ).fetchone()
        if not pack:
            capture_payment_failure(
                provider="razorpay", event="payment_captured",
                reason="no_matching_credit_pack", user_id=user_id,
                order_id=provider_order_id,
            )
            return {"fulfilled": False, "reason": "no_matching_credit_pack"}
        d = dict(pack) if not isinstance(pack, dict) else pack
        credits = int(d["credits"])

        # Bind payment id + claim the paid transition atomically. If this
        # returns no row, a concurrent webhook/handler already fulfilled.
        claimed = conn.execute(
            """UPDATE payments
               SET status = 'paid', provider_payment_id = %s,
                   raw_event = COALESCE(%s::jsonb, raw_event), updated_at = NOW()
               WHERE id = %s AND status <> 'paid'
               RETURNING id""",
            (provider_payment_id,
             json.dumps(raw_event) if raw_event else None,
             p["id"]),
        ).fetchone()
        if not claimed:
            return {"already_fulfilled": True, "payments_id": p["id"]}

        add_purchased_credits(conn, user_id, d["credit_type"], credits)
        conn.execute(
            "UPDATE payments SET credits_granted = %s WHERE id = %s",
            (credits, p["id"]),
        )
        conn.commit()

    invalidate("all")
    logger.info(
        "[RAZORPAY] Granted %s %s credits to user %s (order=%s)",
        credits, d["credit_type"], user_id, provider_order_id,
    )
    capture_payment_success(
        provider="razorpay", event="payment_captured", action="credits_added",
        user_id=user_id, credits=credits, credit_type=d["credit_type"],
        order_id=provider_order_id,
    )
    return {"fulfilled": True, "credits": credits, "user_id": user_id}


def fulfill_razorpay_subscription(
    subscription_entity: Dict[str, Any],
    *,
    payment_entity: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Idempotently activate/renew a Razorpay subscription.

    Called from subscription.charged webhooks and the client-side
    subscription verify reconcile. Assigns the plan (same billing_service
    call LemonSqueezy uses) and upserts the subscriptions row with
    provider='razorpay'.
    """
    from database_adapter import get_db
    from services.billing_service import assign_plan
    from services.plan_cache import invalidate

    sub_id = str(subscription_entity.get("id", "") or "")
    notes = subscription_entity.get("notes") or {}
    user_id_str = notes.get("user_id")
    plan_slug = notes.get("plan_slug")
    if not user_id_str or not plan_slug:
        logger.error(
            "[RAZORPAY] subscription %s missing notes (user_id/plan_slug)", sub_id
        )
        capture_payment_failure(
            provider="razorpay", event="subscription_charged",
            reason="missing_notes", subscription_id=sub_id,
        )
        return {"fulfilled": False, "reason": "missing_notes"}

    user_id = int(user_id_str)
    # Razorpay returns current_end/current_start as UNIX epoch seconds (int),
    # not ISO strings — convert before writing to the TIMESTAMP column.
    current_end = subscription_entity.get("current_end")
    period_end = None
    if isinstance(current_end, (int, float)) and current_end > 0:
        from datetime import datetime
        period_end = datetime.fromtimestamp(int(current_end))
    elif isinstance(current_end, str) and current_end:
        period_end = current_end  # ISO string passthrough

    with get_db() as conn:
        conn.execute(
            """INSERT INTO subscriptions
               (user_id, plan_id, status, current_period_end,
                provider, external_subscription_id)
               VALUES (%s, (SELECT id FROM billing_plans WHERE slug = %s),
                       'active', %s, 'razorpay', %s)
               ON CONFLICT (external_subscription_id)
                 WHERE external_subscription_id IS NOT NULL DO UPDATE SET
                   status = 'active',
                   current_period_end = EXCLUDED.current_period_end,
                   updated_at = NOW()""",
            (user_id, plan_slug,
             period_end, sub_id),
        )
        conn.execute(
            "UPDATE users SET subscription_tier = %s WHERE id = %s",
            (plan_slug, user_id),
        )
        # Complete the payments intent row created at /subscription time.
        conn.execute(
            """UPDATE payments SET status = 'completed', updated_at = NOW()
               WHERE provider_subscription_id = %s AND provider = 'razorpay'
                 AND status = 'created'""",
            (sub_id,),
        )
        conn.commit()
        assign_plan(conn, user_id, plan_slug)
        conn.commit()

    # Record the charge in the payments ledger (idempotent on payment id).
    if payment_entity and payment_entity.get("id"):
        try:
            with get_db() as conn:
                conn.execute(
                    """INSERT INTO payments
                       (user_id, provider, kind, item_ref, currency, amount_minor,
                        provider_payment_id, provider_subscription_id, status,
                        credits_granted, raw_event)
                       VALUES (%s, 'razorpay', 'plan', %s, %s, %s, %s, %s,
                               'paid', NULL, %s::jsonb)
                       ON CONFLICT (provider, provider_payment_id) DO NOTHING""",
                    (user_id, plan_slug,
                     payment_entity.get("currency", "INR"),
                     int(payment_entity.get("amount", 0) or 0),
                     payment_entity["id"], sub_id,
                     json.dumps({"subscription": subscription_entity,
                                 "payment": payment_entity})),
                )
                conn.commit()
        except Exception as e:
            logger.warning("[RAZORPAY] ledger insert failed (non-fatal): %s", e)

    invalidate("all")
    logger.info("[RAZORPAY] Assigned plan %s to user %s (sub=%s)", plan_slug, user_id, sub_id)
    capture_payment_success(
        provider="razorpay", event="subscription_charged", action="plan_assigned",
        user_id=user_id, plan=plan_slug, subscription_id=sub_id,
    )
    return {"fulfilled": True, "plan": plan_slug, "user_id": user_id}


def cancel_razorpay_subscription_locally(sub_id: str, new_status: str = "cancelled") -> Dict[str, Any]:
    """Downgrade a Razorpay subscriber to free (halted/cancelled/completed).

    Mirrors the LemonSqueezy cancel handling — same assign_plan('free')
    call, scoped to provider='razorpay' rows only.
    """
    from database_adapter import get_db
    from services.billing_service import assign_plan
    from services.plan_cache import invalidate

    with get_db() as conn:
        row = conn.execute(
            """SELECT user_id FROM subscriptions
               WHERE external_subscription_id = %s AND provider = 'razorpay'""",
            (sub_id,),
        ).fetchone()
        if not row:
            return {"fulfilled": False, "reason": "unknown_subscription"}
        user_id = int((dict(row) if not isinstance(row, dict) else row)["user_id"])

        conn.execute(
            """UPDATE subscriptions SET status = %s, updated_at = NOW()
               WHERE external_subscription_id = %s AND provider = 'razorpay'""",
            (new_status, sub_id),
        )
        conn.execute(
            "UPDATE users SET subscription_tier = 'free' WHERE id = %s", (user_id,)
        )
        conn.commit()
        assign_plan(conn, user_id, "free")
        conn.commit()

    invalidate("all")
    logger.info("[RAZORPAY] Downgraded user %s to free (sub=%s, %s)", user_id, sub_id, new_status)
    capture_payment_success(
        provider="razorpay", event=f"subscription_{new_status}",
        action="downgraded_to_free", user_id=user_id, subscription_id=sub_id,
    )
    return {"fulfilled": True, "user_id": user_id}
