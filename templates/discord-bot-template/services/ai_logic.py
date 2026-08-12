#!/usr/bin/env python3
"""
AI Logic - Core decision engine for /ask command responses.

This is the PRIMARY file where bot behavior is defined.
AI agents should primarily modify this file to add new /ask intents.

The process_user_input(text) function receives the user's free-text query
from the /ask slash command (plain text, NO command prefix).
"""
import logging
from services.api_client import get_crypto_price
from services.mock_data import get_mock_response

logger = logging.getLogger('services.ai_logic')


def process_user_input(text: str) -> str:
    """
    Process user input from /ask and return a response.

    Decision flow:
    1. Detect intent from text keywords
    2. Call API via api_client if needed
    3. Return response
    4. Fallback to mock_data if API unavailable

    Args:
        text: User's free-text query (plain text, no prefix).

    Returns:
        Response string
    """
    text_lower = text.lower().strip()

    # Intent: Greeting
    if text_lower in ["hello", "hi", "hey", "sup"]:
        logger.info(f"Intent: greeting | input: {text[:50]}")
        return "Hey there! How can I help you today?"

    # Intent: Bitcoin/price query
    if any(kw in text_lower for kw in ["btc", "bitcoin", "price"]):
        logger.info(f"Intent: bitcoin/price | input: {text[:50]}")
        try:
            result = get_crypto_price("bitcoin")
            if result.get("success"):
                price = result["price"]
                logger.info(f"Bitcoin price fetched: ${price:,.2f}")
                return f"Bitcoin Price: ${price:,.2f}"
            else:
                logger.warning(f"Bitcoin API returned error: {result.get('error')}")
                return get_mock_response("bitcoin")
        except Exception as e:
            logger.warning(f"Bitcoin API failed, using mock: {e}")
            return get_mock_response("bitcoin")

    # Default: Echo with mock fallback
    logger.info(f"Intent: default | input: {text[:50]}")
    return get_mock_response("default", text=text)
