from typing import Optional
from services.api_client import get_crypto_price
from utils.logger import logger
from models.user import User


def process_user_input(text: str, user: Optional[User] = None) -> str:
    text_lower = text.lower().strip()
    logger.info(f"Processing: {text_lower[:50]}")

    if not text_lower:
        return "⚠️ Please send a valid message."

    # =========================
    # DEFAULT COMMANDS
    # =========================

    if text_lower.startswith("/start") or text_lower == "start":
        return _handle_start(user)

    if text_lower.startswith("/help") or text_lower == "help":
        return _handle_help()

    if text_lower.startswith("/status") or text_lower == "status":
        return _handle_status(user)

    # ✅ FIXED /ask
    if text_lower.startswith("/ask"):
        parts = text.split(maxsplit=1)

        if len(parts) < 2:
            return (
                "💡 Usage: /ask <your question>\n\n"
                "Examples:\n"
                "• /ask what is bitcoin?\n"
                "• /ask how does blockchain work?"
            )

        return _handle_ask(parts[1])

    # =========================
    # CRYPTO COMMANDS
    # =========================

    # ✅ FIXED /price
    if text_lower.startswith("/price"):
        parts = text_lower.split()

        if len(parts) < 2:
            return "💡 Usage: /price <coin>\nExample: /price btc"

        coin = parts[1]
        return _handle_crypto_query(coin)

    # =========================
    # NATURAL CRYPTO QUERIES
    # =========================

    if any(k in text_lower for k in ["btc", "bitcoin"]):
        return _handle_crypto_query("bitcoin")

    if any(k in text_lower for k in ["eth", "ethereum"]):
        return _handle_crypto_query("ethereum")

    # =========================
    # GENERAL INTERACTIONS
    # =========================

    if any(word in text_lower for word in ["hello", "hi", "hey", "hola"]):
        if user and user.telegram_username:
            return f"👋 Hello @{user.telegram_username}! How can I help you today?"
        return "👋 Hello! How can I help you today?"

    if "whoami" in text_lower or "who am i" in text_lower:
        if user:
            return (
                f"🆔 Your Telegram ID: {user.telegram_user_id}\n"
                f"💬 Chat ID: {user.telegram_chat_id}\n"
                f"👤 Username: @{user.telegram_username or 'not set'}"
            )
        return "⚠️ User data not available"

    return _get_default_response()


# =========================
# HANDLERS
# =========================

def _handle_start(user: Optional[User]) -> str:
    if user and user.telegram_username:
        return (
            f"👋 Welcome @{user.telegram_username}!\n\n"
            "🪙 Crypto Bot Ready!\n\n"
            "Commands:\n"
            "• /price btc\n"
            "• /ask anything\n"
            "• /help\n"
        )
    return (
        "👋 Welcome!\n\n"
        "🪙 Crypto Bot Ready!\n\n"
        "Commands:\n"
        "• /price btc\n"
        "• /ask anything\n"
        "• /help\n"
    )


def _handle_help() -> str:
    return (
        "📚 Commands:\n\n"
        "• /price <coin>\n"
        "• /ask <question>\n"
        "• /status\n"
        "• /start\n\n"
        "Try:\n"
        "• BTC price\n"
        "• ETH price"
    )


def _handle_status(user: Optional[User]) -> str:
    import datetime
    return (
        "✅ Bot Online\n"
        f"🕐 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )


def _handle_ask(question: str) -> str:
    return (
        f"🤔 {question}\n\n"
        "⚠️ AI not enabled yet.\n"
        "Try crypto commands like /price btc"
    )


def _handle_crypto_query(coin: str) -> str:
    result = get_crypto_price(coin_id=coin)

    if result["success"]:
        return f"💰 {coin.capitalize()}: ${result['price']:,.2f}"
    else:
        return f"💰 {coin.capitalize()}: $1000 (mock)"


def _get_default_response() -> str:
    return (
        "🤖 I didn't understand.\n\n"
        "Try:\n"
        "• /price btc\n"
        "• BTC price\n"
        "• /ask something"
    )