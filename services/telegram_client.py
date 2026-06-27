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
    """Allowed update types — only text messages + commands."""
    return ["message"]


def is_configured() -> bool:
    """Check if Telegram bot is configured."""
    return bool(BOT_TOKEN)
