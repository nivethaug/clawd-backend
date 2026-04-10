#!/usr/bin/env python3
"""
AI Logic - Core decision engine for bot responses.

This is the ONLY file where bot behavior is defined.
AI agents should primarily modify this file to change bot behavior.
"""

from services.api_client import fetch_data
from services.mock_data import get_mock_response


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
        return "Hey there! How can I help you today?"

    # Intent: Identity check
    if "whoami" in text_lower or "who am i" in text_lower:
        return "You can use `!start` to see your Discord user info!"

    # Intent: Bitcoin/price query
    if any(kw in text_lower for kw in ["btc", "bitcoin", "price"]):
        try:
            price = fetch_data("bitcoin")
            return f"Bitcoin Price: ${price:,.2f}"
        except Exception:
            return get_mock_response("bitcoin")

    # Intent: Help request
    if "help" in text_lower:
        return "Type `!help` to see all available commands."

    # Default: Echo with mock fallback
    return get_mock_response("default", text=text)
