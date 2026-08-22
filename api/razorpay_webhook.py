#!/usr/bin/env python3
"""
Razorpay Webhook Router — Receives payment/subscription events from Razorpay.

Mounted at: /webhooks/razorpay (prefix added in app.py).
Auth: HMAC-SHA256 signature over the RAW body (X-Razorpay-Signature header).

ZERO-IMPACT ISOLATION: api/lemonsqueezy_webhook.py and
services/lemonsqueezy_service.py are NOT modified. This router dispatches to
services/razorpay_service.py only.

Verification fails closed: if RAZORPAY_WEBHOOK_SECRET is not set, every
request is rejected (401) unless WEBHOOK_DEV_BYPASS=1 (dev only). After a
valid signature we ALWAYS return 200 so Razorpay doesn't retry endlessly —
processing errors are logged + sent to the payment sentry instead.

Handled events:
  payment.captured        → fulfill credit pack (idempotent with /verify)
  payment.failed          → mark payments row failed + audit
  order.paid              → reconcile (fulfill if not already)
  subscription.charged    → activate/renew plan + ledger entry
  subscription.halted     → downgrade to free (retries exhausted)
  subscription.cancelled  → downgrade to free
  subscription.completed  → downgrade to free (cycle count reached)
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Request

from services.payment_sentry import capture_payment_failure
from services import razorpay_service

logger = logging.getLogger("api.webhook.razorpay")

router = APIRouter()


def _process_event(event: dict) -> dict:
    """Dispatch a verified Razorpay webhook event. Returns a result dict."""
    from database_adapter import get_db

    event_name = event.get("event", "")
    payload = event.get("payload") or {}

    payment = (payload.get("payment") or {}).get("entity") or {}
    order = (payload.get("order") or {}).get("entity") or {}
    subscription = (payload.get("subscription") or {}).get("entity") or {}

    # One-time-payment webhooks always expose order_id on the payment entity,
    # but not all include a nested order entity — prefer the entity, fall
    # back to payment.order_id.
    gateway_order_id = order.get("id") or payment.get("order_id") or ""

    if event_name == "payment.captured":
        if not gateway_order_id:
            return {"handled": False, "reason": "no order in payload"}
        return razorpay_service.fulfill_razorpay_payment(
            provider_order_id=gateway_order_id,
            provider_payment_id=payment.get("id", ""),
            raw_event={"payment": payment, "order": order},
        )

    if event_name == "payment.failed":
        order_id = gateway_order_id
        if order_id:
            with get_db() as conn:
                conn.execute(
                    """UPDATE payments SET status = 'failed', updated_at = NOW()
                       WHERE provider_order_id = %s AND provider = 'razorpay'
                         AND status = 'created'""",
                    (order_id,),
                )
                conn.commit()
        notes = payment.get("notes") or {}
        user_id = notes.get("user_id")
        capture_payment_failure(
            provider="razorpay", event="payment.failed",
            reason=payment.get("error_description") or "provider_payment_failed",
            user_id=int(user_id) if user_id else None,
            order_id=order_id,
        )
        return {"handled": True, "action": "payment_failed"}

    if event_name == "order.paid":
        # Reconcile path — payment.captured is the primary fulfiller; this
        # catches captures whose payment.captured webhook was missed.
        if not payment.get("id") or not gateway_order_id:
            return {"handled": False, "reason": "no payment/order in payload"}
        return razorpay_service.fulfill_razorpay_payment(
            provider_order_id=gateway_order_id,
            provider_payment_id=payment["id"],
            raw_event={"payment": payment, "order": order},
        )

    if event_name == "subscription.charged":
        return razorpay_service.fulfill_razorpay_subscription(
            subscription, payment_entity=payment or None
        )

    if event_name in ("subscription.halted", "subscription.cancelled",
                      "subscription.completed"):
        new_status = event_name.split(".", 1)[1]  # halted|cancelled|completed
        if not subscription.get("id"):
            return {"handled": False, "reason": "no subscription in payload"}
        return razorpay_service.cancel_razorpay_subscription_locally(
            subscription["id"], new_status
        )

    logger.info("[WEBHOOK-RP] Unhandled event: %s", event_name)
    return {"handled": False, "reason": f"unhandled event: {event_name}"}


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: Optional[str] = Header(None, alias="X-Razorpay-Signature"),
):
    raw_body = await request.body()

    if not razorpay_service.verify_webhook_signature(raw_body, x_razorpay_signature or ""):
        logger.warning("[WEBHOOK-RP] Invalid signature — rejecting")
        capture_payment_failure(event="webhook_signature", reason="invalid_signature",
                                provider="razorpay")
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        event = json.loads(raw_body)
    except Exception as e:
        logger.error("[WEBHOOK-RP] Failed to parse JSON: %s", e)
        capture_payment_failure(event="webhook_parse", reason="invalid_json",
                                provider="razorpay", exc=e)
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_name = event.get("event", "unknown")
    logger.info("[WEBHOOK-RP] Received event: %s", event_name)

    try:
        result = _process_event(event)
        logger.info("[WEBHOOK-RP] Event %s processed: %s", event_name, result)
        return {"status": "ok", "event": event_name, "result": result}
    except Exception as e:
        logger.error("[WEBHOOK-RP] Failed to process event %s: %s",
                     event_name, e, exc_info=True)
        capture_payment_failure(event=event_name, reason="processing_exception",
                                provider="razorpay", exc=e)
        # 200 anyway — we've audited; returning 5xx would cause endless retries.
        return {"status": "error", "event": event_name, "error": str(e)}
