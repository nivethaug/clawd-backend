"""
AI Logic module.
ALL business logic goes here.
Easy to modify by AI agents without touching handlers.

# DreamAgent: This file is dynamically modified based on user prompt
# AI will analyze description and generate appropriate commands/fallbacks
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
    
    # ========================================================================
    # DEFAULT COMMANDS (Always available)
    # ========================================================================
    
    # /start command
    if text_lower.startswith("/start") or text_lower == "start":
        return _handle_start(user)
    
    # /help command
    if text_lower.startswith("/help") or text_lower == "help":
        return _handle_help()
    
    # /status command
    if text_lower.startswith("/status") or text_lower == "status":
        return _handle_status(user)
    
    # /ask command (general Q&A)
    if text_lower.startswith("/ask") or text_lower == "ask":
        question = text_lower.replace("/ask", "").replace("ask", "").strip()
        return _handle_ask(question)
    
    # ========================================================================
    # EXAMPLE FEATURE: Crypto Price (AI can add more features)
    # ========================================================================
    
    # Crypto price queries
    if any(keyword in text_lower for keyword in ["btc", "bitcoin", "btc price"]):
        return _handle_crypto_query("bitcoin")
    
    if any(keyword in text_lower for keyword in ["eth", "ethereum"]):
        return _handle_crypto_query("ethereum")
    
    # ========================================================================
    # GENERAL INTERACTIONS
    # ========================================================================
    
    # Greeting
    if any(word in text_lower for word in ["hello", "hi", "hey", "hola"]):
        if user and user.telegram_username:
            return f"👋 Hello @{user.telegram_username}! How can I help you today?"
        return "👋 Hello! How can I help you today?"
    
    # User info (example of using user context)
    if "whoami" in text_lower or "who am i" in text_lower:
        if user:
            return (
                f"🆔 Your Telegram ID: {user.telegram_user_id}\n"
                f"💬 Chat ID: {user.telegram_chat_id}\n"
                f"👤 Username: @{user.telegram_username or 'not set'}"
            )
        return "⚠️ User data not available"
    
    # ========================================================================
    # FALLBACK: Default response for unrecognized input
    # ========================================================================
    
    return _get_default_response()


# ============================================================================
# DEFAULT COMMAND HANDLERS (AI should not modify these)
# ============================================================================

def _handle_start(user: Optional[User]) -> str:
    """Handle /start command."""
    if user and user.telegram_username:
        return (
            f"👋 Welcome @{user.telegram_username}!\n\n"
            "I'm your AI-powered bot. Here's what I can do:\n\n"
            "🔹 /help - Show available commands\n"
            "🔹 /status - Check bot status\n"
            "🔹 /ask <question> - Ask me anything\n\n"
            "Just type a command or ask me something!"
        )
    return (
        "👋 Welcome!\n\n"
        "I'm your AI-powered bot. Here's what I can do:\n\n"
        "🔹 /help - Show available commands\n"
        "🔹 /status - Check bot status\n"
        "🔹 /ask <question> - Ask me anything\n\n"
        "Just type a command or ask me something!"
    )


def _handle_help() -> str:
    """Handle /help command."""
    return (
        "📚 **Available Commands**\n\n"
        "🔹 /start - Start the bot\n"
        "🔹 /help - Show this help message\n"
        "🔹 /status - Check bot status\n"
        "🔹 /ask <question> - Ask me anything\n\n"
        "**Examples:**\n"
        "• BTC price\n"
        "• ETH price\n"
        "• Hello\n\n"
        "💡 More features may be available based on bot configuration!"
    )


def _handle_status(user: Optional[User]) -> str:
    """Handle /status command."""
    import datetime
    status = (
        "✅ **Bot Status**\n\n"
        "🟢 Status: Online\n"
        f"🕐 Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    )
    if user:
        status += f"👤 User: @{user.telegram_username or 'Unknown'}\n"
    return status


def _handle_ask(question: str) -> str:
    """Handle /ask command (general Q&A)."""
    # question is already cleaned by caller
    
    if not question or not question.strip():
        return (
            "💡 **Usage:** /ask <your question>\n\n"
            "**Examples:**\n"
            "• /ask what is bitcoin?\n"
            "• /ask how does blockchain work?\n"
            "• /ask tell me about ethereum"
        )
    
    # Mock response for general questions
    # AI will enhance this with real logic
    return (
        f"🤔 You asked: \"{question}\"\n\n"
        "💡 I'm still learning! Try one of these:\n"
        "• BTC price\n"
        "• /price eth\n"
        "• /market\n"
        "• Or type /help for more options"
    )


# ============================================================================
# FEATURE HANDLERS (AI can add more below)
# ============================================================================

def _handle_crypto_query(coin: str) -> str:
    """Handle cryptocurrency price queries."""
    result = get_crypto_price(coin_id=coin)
    
    emoji = "💰" if coin == "bitcoin" else "💎"
    
    if result["success"]:
        return f"{emoji} {coin.capitalize()} Price: ${result['price']:,.2f}"
    else:
        # Fallback to mock response if API fails
        logger.warning(f"API failed for {coin}, using mock response")
        mock_prices = {
            "bitcoin": 65000,
            "ethereum": 3500
        }
        mock_price = mock_prices.get(coin, 1000)
        return f"{emoji} {coin.capitalize()} Price: ${mock_price:,} (mock)"


def _get_default_response() -> str:
    """Get default response for unrecognized input."""
    # Safe fallback - never show errors to user
    return (
        "🤖 I didn't understand that.\n\n"
        "Try asking something like:\n"
        "• BTC price\n"
        "• ETH price\n"
        "• /help for more options\n"
        "• /ask <question> to ask me anything"
    )
