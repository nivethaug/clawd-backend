#!/usr/bin/env python3
"""
LemonSqueezy Webhook Router — Receives payment events from LemonSqueezy.

Mounted at: /webhooks/lemonsqueezy
Auth: HMAC-SHA256 signature verification (X-Signature header).

If LEMONSQUEZY_WEBHOOK_SECRET is not set, signature verification is skipped
(DEV MODE ONLY — never use in production).
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Header, Request

logger = logging.getLogger("api.webhook.lemonsqueezy")

router = APIRouter()


@router.post("/lemonsqueezy")
async def lemonsqueezy_webhook(
    request: Request,
    x_signature: Optional[str] = Header(None, alias="X-Signature"),
):
    """
    Receive and process a LemonSqueezy webhook event.

    LemonSqueezy sends JSON with this structure:
        {
            "meta": {
                "event_name": "subscription_created|order_created|...",
                "custom_data": {"user_id": "123", ...}
            },
            "data": {
                "id": "...",
                "attributes": {
                    "variant_id": 123,
                    "renews_at": "...",
                    ...
                }
            }
        }
    """
    from services.lemonsqueezy_service import verify_webhook_signature, process_webhook_event

    # Read raw body for signature verification
    raw_body = await request.body()

    # Verify signature
    if not verify_webhook_signature(raw_body, x_signature or ""):
        logger.warning("[WEBHOOK-LM] Invalid signature — rejecting")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse JSON
    try:
        import json
        event_data = json.loads(raw_body)
    except Exception as e:
        logger.error(f"[WEBHOOK-LM] Failed to parse JSON: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_name = event_data.get("meta", {}).get("event_name", "unknown")
    logger.info(f"[WEBHOOK-LM] Received event: {event_name}")

    # Process event
    try:
        result = process_webhook_event(event_data)
        logger.info(f"[WEBHOOK-LM] Event {event_name} processed: {result}")
        return {"status": "ok", "event": event_name, "result": result}
    except Exception as e:
        logger.error(f"[WEBHOOK-LM] Failed to process event {event_name}: {e}", exc_info=True)
        # Return 200 anyway so LemonSqueezy doesn't retry endlessly
        # (we've logged the error; investigate manually)
        return {"status": "error", "event": event_name, "error": str(e)}
