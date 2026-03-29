"""
AI Logic module.
ALL business logic goes here.
Easy to modify by AI agents without touching handlers.

# DreamAgent: This file is dynamically modified based on user prompt
"""

from typing import Optional
from services.api_client import get_crypto_price
from utils.logger import logger
from models.user import User


def process_user_input(text: str, user: Optional[User] = None) -> str:
    """
    Process user input and return response.
    
    Args:
        text: User's message text
        user: Optional User object (from database)
    
    Returns:
        Response string to send back to user
    """
    text_lower = text.lower().strip()
    logger.info(f"Processing: {text_lower[:50]}")
    
    # Crypto price queries
    if any(keyword in text_lower for keyword in ["btc", "bitcoin", "btc price"]):
        return _handle_crypto_query("bitcoin")
    
    if any(keyword in text_lower for keyword in ["eth", "ethereum"]):
        return _handle_crypto_query("ethereum")
    
    # Greeting
    if any(word in text_lower for word in ["hello", "hi", "hey", "hola"]):
        if user and user.telegram_username:
            return f"👋 Hello @{user.telegram_username}! How can I help you today?"
        return "👋 Hello! How can I help you today?"
    
    # Help request
    if "help" in text_lower:
        return "💡 Type /help to see what I can do!"
    
    # User info (example of using user context)
    if "whoami" in text_lower or "who am i" in text_lower:
        if user:
            return (
                f"🆔 Your Telegram ID: {user.telegram_user_id}\n"
                f"💬 Chat ID: {user.telegram_chat_id}\n"
                f"👤 Username: @{user.telegram_username or 'not set'}"
            )
        return "⚠️ User data not available"
    
    # Default response
    return _get_default_response()


def _handle_crypto_query(coin: str) -> str:
    """Handle cryptocurrency price queries."""
    result = get_crypto_price(coin_id=coin)
    
    if result["success"]:
        emoji = "💰" if coin == "bitcoin" else "💎"
        return f"{emoji} {coin.capitalize()} Price: ${result['price']:,.2f}"
    else:
        return f"⚠️ Error fetching price: {result['error']}"


def _get_default_response() -> str:
    """Get default response for unrecognized input."""
    # Safe fallback - never show errors to user
    return (
        "🤖 I didn't understand that.\n\n"
        "Try asking something like:\n"
        "• BTC price\n"
        "• ETH price\n"
        "• Or type /help for more options"
    )
