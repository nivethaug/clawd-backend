"""
Telegram Bot API Client
Thin wrapper using httpx — only needs sendMessage + setWebhook.
No external Telegram library required.
"""

import os
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""
WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "dreamagent-tg-whhook-2026")


async def send_message(
    chat_id: int | str,
    text: str,
    parse_mode: str = "Markdown",
    reply_to_message_id: Optional[int] = None,
    reply_markup: Optional[dict] = None,
) -> bool:
    """
    Send a text message to a Telegram chat.

    Returns True on success, False on failure.
    Falls back to plain text (no Markdown) if parsing fails.
    """
    if not BOT_TOKEN:
        logger.error("[TELEGRAM] BOT_TOKEN not configured")
        return False

    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{API_BASE}/sendMessage", json=payload)
            data = resp.json()

            if not data.get("ok"):
                # Markdown parse failure? Retry as plain text
                if parse_mode and "parse" in str(data.get("description", "")).lower():
                    logger.warning(f"[TELEGRAM] Markdown failed, retrying plain text")
                    payload["parse_mode"] = ""
                    resp2 = await client.post(f"{API_BASE}/sendMessage", json=payload)
                    if resp2.json().get("ok"):
                        return True
                logger.error(f"[TELEGRAM] sendMessage failed: {data.get('description')}")
                return False
            return True

    except Exception as e:
        logger.error(f"[TELEGRAM] sendMessage error: {e}")
        return False


async def answer_callback_query(callback_query_id: str, text: Optional[str] = None) -> bool:
    """Answer a callback query — removes the loading spinner on the button."""
    if not BOT_TOKEN:
        return False
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(f"{API_BASE}/answerCallbackQuery", json=payload)
            return resp.json().get("ok", False)
    except Exception:
        return False


async def edit_message_text(
    chat_id: int | str,
    message_id: int,
    text: str,
    parse_mode: str = "Markdown",
) -> bool:
    """Edit an existing message's text (used to update button messages)."""
    if not BOT_TOKEN:
        return False
    payload: dict = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{API_BASE}/editMessageText", json=payload)
            if not resp.json().get("ok"):
                # Try plain text fallback
                payload["parse_mode"] = ""
                resp2 = await client.post(f"{API_BASE}/editMessageText", json=payload)
                return resp2.json().get("ok", False)
            return True
    except Exception:
        return False


async def send_chat_action(chat_id: int | str, action: str = "typing") -> bool:
    """
    Send a chat action indicator (e.g. "typing...").
    This is NOT a visible message — just a status indicator.
    """
    if not BOT_TOKEN:
        return False

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                f"{API_BASE}/sendChatAction",
                json={"chat_id": chat_id, "action": action},
            )
            return resp.json().get("ok", False)
    except Exception:
        return False


async def set_webhook(webhook_url: str) -> dict:
    """
    Register webhook URL with Telegram.
    Called once during setup.
    """
    if not BOT_TOKEN:
        return {"ok": False, "error": "BOT_TOKEN not configured"}

    payload = {
        "url": webhook_url,
        "secret_token": WEBHOOK_SECRET,
        "allowed_updates": json_updates(),
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{API_BASE}/setWebhook", json=payload)
            return resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def delete_webhook() -> dict:
    """Remove webhook (switch to polling mode or disable)."""
    if not BOT_TOKEN:
        return {"ok": False, "error": "BOT_TOKEN not configured"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{API_BASE}/deleteWebhook", json={})
            return resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def get_bot_info() -> dict:
    """Get bot username/id — useful for the linking instructions."""
    if not BOT_TOKEN:
        return {"ok": False, "error": "BOT_TOKEN not configured"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{API_BASE}/getMe", json={})
            return resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def json_updates() -> list:
    """Allowed update types — text messages, commands, and callback queries."""
    return ["message", "callback_query"]


def is_configured() -> bool:
    """Check if Telegram bot is configured."""
    return bool(BOT_TOKEN)


# ── Bot Commands ────────────────────────────────────────────
# Registered via setMyCommands — shows in Telegram's "/" menu.

BOT_COMMANDS = [
    {"command": "switch",   "description": "🔄 Switch / select project"},
    {"command": "sessions", "description": "Select a project session"},
    {"command": "newsession", "description": "Create a project session"},
    {"command": "clearsession", "description": "Clear selected session"},
    {"command": "complete", "description": "Release selected session"},
    {"command": "billing", "description": "Show plan and credits"},
    {"command": "current",  "description": "📌 Show active project"},
    {"command": "link",     "description": "🔗 Link your account"},
    {"command": "unlink",   "description": "🔓 Unlink account"},
    {"command": "help",     "description": "❓ Help"},
]


DEFAULT_BOT_COMMANDS = [
    {"command": "switch", "description": "Choose or change project"},
    {"command": "current", "description": "Show active project and session"},
    {"command": "sessions", "description": "Choose a project session"},
    {"command": "newsession", "description": "Create and select a session"},
    {"command": "complete", "description": "Complete and release session"},
    {"command": "clearsession", "description": "Leave selected session"},
    {"command": "billing", "description": "Show plan and credits"},
    {"command": "status", "description": "Check project status"},
    {"command": "logs", "description": "Show recent logs"},
    {"command": "restart", "description": "Restart active project"},
    {"command": "start", "description": "Start active project"},
    {"command": "stop", "description": "Stop active project"},
    {"command": "link", "description": "Link your account"},
    {"command": "unlink", "description": "Unlink this chat"},
    {"command": "help", "description": "How to use DreamAgent Bot"},
]


async def set_my_commands() -> dict:
    """Register the bot command menu (shows when user types /)."""
    if not BOT_TOKEN:
        return {"ok": False, "error": "BOT_TOKEN not configured"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{API_BASE}/setMyCommands",
                json={"commands": DEFAULT_BOT_COMMANDS},
            )
            return resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}
