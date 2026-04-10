#!/usr/bin/env python3
"""
Mock Data - Fallback responses when API is unavailable or intent is unclear.

This provides safe, predictable responses for the bot.
"""

# Fallback responses by category
MOCK_RESPONSES = {
    "bitcoin": "Bitcoin Price: $45,123.45 (mock data - API unavailable)",
    "ethereum": "Ethereum Price: $2,456.78 (mock data - API unavailable)",
    "default": "I received your message: \"{text}\". I'm not sure how to respond to that yet. Type `!help` for available commands.",
}


def get_mock_response(category: str, **kwargs) -> str:
    """
    Get a mock/fallback response.

    Args:
        category: Response category key
        **kwargs: Format variables for the response

    Returns:
        Formatted response string
    """
    template = MOCK_RESPONSES.get(category, MOCK_RESPONSES["default"])
    try:
        return template.format(**kwargs)
    except KeyError:
        return template
