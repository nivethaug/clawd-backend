#!/usr/bin/env python3
"""
AI Logic - Core decision engine for bot responses.

This is the ONLY file where bot behavior is defined.
AI agents should primarily modify this file to change bot behavior.
"""
import logging
from services.api_client import fetch_data
from services.mock_data import get_mock_response

logger = logging.getLogger('services.ai_logic')


def process_user_input(text: str) -> str:
    """
    Process user input and return a response.

    Decision flow:
    1. Detect intent from text
    2. Call API via api_client if needed
    3. Return response
    4. Fallback to mock_data if API unavailable

    Args:
        text: User's message text

    Returns:
        Response string
    """
    text_lower = text.lower().strip()

    # Intent: Greeting
    if text_lower in ["hello", "hi", "hey", "sup"]:
        logger.info(f"Intent: greeting | input: {text[:50]}")
        return "Hey there! How can I help you today?"

    # Intent: Identity check
    if "whoami" in text_lower or "who am i" in text_lower:
        logger.info(f"Intent: identity | input: {text[:50]}")
        return "You can use `!start` to see your Discord user info!"

    # Intent: Bitcoin/price query
    if any(kw in text_lower for kw in ["btc", "bitcoin", "price"]):
        logger.info(f"Intent: bitcoin/price | input: {text[:50]}")
        try:
            price = fetch_data("bitcoin")
            logger.info(f"Bitcoin price fetched: ${price:,.2f}")
            return f"Bitcoin Price: ${price:,.2f}"
        except Exception as e:
            logger.warning(f"Bitcoin API failed, using mock: {e}")
            return get_mock_response("bitcoin")

    # Intent: Help request
    if "help" in text_lower:
        logger.info(f"Intent: help | input: {text[:50]}")
        return "Type `!help` to see all available commands."

    # Default: Echo with mock fallback
    logger.info(f"Intent: default | input: {text[:50]}")
    return get_mock_response("default", text=text)
