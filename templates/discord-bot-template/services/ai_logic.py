#!/usr/bin/env python3
"""
AI Logic - Core decision engine for /ask command responses.

This is the PRIMARY file where bot behavior is defined.
AI agents should primarily modify this file to add new /ask intents.

The process_user_input(text, ctx) function receives the user's free-text query
from the /ask slash command (plain text, NO command prefix). ``ctx`` carries
the invocation context (guild_id/channel_id/user_id as strings) — handlers
that keep per-guild or per-channel state MUST scope lookups through it, never
assume a default guild, or /dev/invoke tests will search the wrong store.

Every return path sets a STAGE (set_stage) so /dev/invoke can report WHICH
stage produced the reply instead of an ambiguous fallback string. Keep this
convention when adding intents: a stage of "fallback:*" or "*_not_found"
tells the verifier the pipeline degraded, while "ok"/"intent:*" means the
primary path answered.
"""
import logging
from typing import Optional
from services.api_client import get_crypto_price
from services.mock_data import get_mock_response

logger = logging.getLogger('services.ai_logic')

# Machine-readable stage of the LAST process_user_input call — read by
# /dev/invoke so verification can tell "real answer" from "fallback path".
# A dict keeps updates rebinding-free (import-safe).
LAST_STAGE: dict = {"name": "ok", "detail": ""}


def set_stage(name: str, detail: str = "") -> None:
    """Record which pipeline stage produced the current reply."""
    LAST_STAGE["name"] = name
    LAST_STAGE["detail"] = detail


def process_user_input(text: str, ctx: Optional[dict] = None) -> str:
    """
    Process user input from /ask and return a response.

    Decision flow:
    1. Detect intent from text keywords
    2. Call API via api_client if needed
    3. Return response
    4. Fallback to mock_data if API unavailable

    Args:
        text: User's free-text query (plain text, no prefix).
        ctx: Invocation context — {"guild_id", "channel_id", "user_id"} from
             the slash command or /dev/invoke body. Use for any per-guild /
             per-channel state lookups.

    Returns:
        Response string
    """
    ctx = ctx or {}
    text_lower = text.lower().strip()
    # Default until a branch proves otherwise — an unmatched query is a
    # fallback, not a success.
    set_stage("fallback:default", f"no intent matched: {text[:60]}")

    # Intent: Greeting
    if text_lower in ["hello", "hi", "hey", "sup"]:
        logger.info(f"Intent: greeting | input: {text[:50]} | ctx: {ctx}")
        set_stage("intent:greeting")
        return "Hey there! How can I help you today?"

    # Intent: Bitcoin/price query
    if any(kw in text_lower for kw in ["btc", "bitcoin", "price"]):
        logger.info(f"Intent: bitcoin/price | input: {text[:50]} | ctx: {ctx}")
        try:
            result = get_crypto_price("bitcoin")
            if result.get("success"):
                price = result["price"]
                logger.info(f"Bitcoin price fetched: ${price:,.2f}")
                set_stage("intent:price:api")
                return f"Bitcoin Price: ${price:,.2f}"
            else:
                logger.warning(f"Bitcoin API returned error: {result.get('error')}")
                set_stage("fallback:price:api_error", str(result.get("error") or "")[:200])
                return get_mock_response("bitcoin")
        except Exception as e:
            logger.warning(f"Bitcoin API failed, using mock: {e}")
            set_stage("fallback:price:exception", str(e)[:200])
            return get_mock_response("bitcoin")

    # Default: Echo with mock fallback
    logger.info(f"Intent: default | input: {text[:50]} | ctx: {ctx}")
    return get_mock_response("default", text=text)
