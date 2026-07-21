"""
AI Logic Layer — DreamAgent Telegram Bot Template.

This is the BASE template that runs before AI enhancement.
The AI enhancement step (Claude) rewrites this file to add project-specific
commands and integrations based on the user's description.

Until AI enhancement runs, the bot responds with generic placeholder messages
so the user can verify the bot is alive after webhook registration.
"""
from typing import Optional
from utils.logger import logger
from models.user import User


def process_user_input(text: str, user: Optional[User] = None) -> str:
    """Main entry point — routes user input to handlers.

    Args:
        text: The message text from Telegram (command or natural language).
        user: The Telegram user object (may be None in some flows).

    Returns:
        Response string to send back to the user.
    """
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
    """Welcome message — generic, no project-specific commands yet."""
    name = f" @{user.telegram_username}" if user and user.telegram_username else ""
    return (
        f"👋 Welcome{name}!\n\n"
        "🤖 Your bot is online and ready.\n\n"
        "Commands:\n"
        "• /help — Show available commands\n"
        "• /status — Check bot status\n"
    )


def _handle_help() -> str:
    """Help menu — generic until AI enhancement adds real commands."""
    return (
        "📚 Commands:\n\n"
        "• /start — Welcome message\n"
        "• /help — Show this help\n"
        "• /status — Bot status\n\n"
        "More commands will be available after AI setup completes."
    )


def _handle_status(user: Optional[User]) -> str:
    """Status check — confirms bot is alive after webhook registration."""
    import datetime
    return (
        "✅ Bot Online\n"
        f"🕐 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )


def _get_default_response() -> str:
    """Fallback for unrecognized input."""
    return (
        "🤖 I didn't understand that.\n\n"
        "Type /help to see available commands."
    )
