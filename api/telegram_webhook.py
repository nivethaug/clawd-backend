"""
Telegram Webhook Handler
Receives Telegram updates via webhook, routes messages to the AI chat engine.
"""

import logging
from datetime import datetime
from typing import Optional, Any

from fastapi import APIRouter, Header, Request, HTTPException
from pydantic import BaseModel

from database_postgres import get_db
from services.telegram_client import (
    send_message,
    set_webhook as tg_set_webhook,
    delete_webhook as tg_delete_webhook,
    get_bot_info,
    WEBHOOK_SECRET,
    is_configured,
)
from api.ai_chat import process_message
from domain_config import CONTROL_API_HOST

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Webhook Secret verification ─────────────────────────────
# Telegram sends X-Telegram-Bot-Api-Secret-Token header on every request.
# We verify it matches our configured secret.


def _verify_secret(token: Optional[str]) -> bool:
    """Verify the Telegram webhook secret token."""
    if not WEBHOOK_SECRET:
        return True  # No secret configured — skip check
    return token == WEBHOOK_SECRET


# ── Database helpers ────────────────────────────────────────

def _lookup_user_by_chat_id(chat_id: int) -> Optional[int]:
    """Find user_id by telegram_chat_id. Returns None if not linked."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE telegram_chat_id = %s",
            (chat_id,)
        ).fetchone()
    return row["id"] if row else None


def _try_link_code(chat_id: int, code: str) -> tuple[bool, str]:
    """
    Attempt to link a Telegram chat_id to a user via a link code.
    Returns (success, message).
    """
    code = code.upper().strip()
    
    with get_db() as conn:
        row = conn.execute(
            """SELECT id, telegram_link_expires_at FROM users
               WHERE telegram_link_code = %s""",
            (code,)
        ).fetchone()
        
        if not row:
            return False, f"❌ Invalid code '{code}'. Please check and try again."
        
        # Check expiry
        expires_at = row.get("telegram_link_expires_at")
        if expires_at and datetime.utcnow() > expires_at:
            return False, "❌ This code has expired. Please generate a new one in your DreamAgent dashboard."
        
        # Check if already linked
        user_id = row["id"]
        existing = conn.execute(
            "SELECT telegram_chat_id FROM users WHERE id = %s",
            (user_id,)
        ).fetchone()
        if existing and existing.get("telegram_chat_id"):
            return False, "⚠️ Your account is already linked to a Telegram chat. Use /unlink first."
        
        # Link it
        conn.execute(
            """UPDATE users
               SET telegram_chat_id = %s,
                   telegram_link_code = NULL,
                   telegram_link_expires_at = NULL
               WHERE id = %s""",
            (chat_id, user_id)
        )
        conn.commit()
        
        logger.info(f"[TELEGRAM] Linked chat_id={chat_id} to user_id={user_id}")
        return True, "✅ *Account linked successfully!*\n\nYou can now send me commands to manage your projects. Try:\n• `status` — check project status\n• `stop` / `start` / `restart`\n• `logs` — view recent logs\n• `switch to {project}` — change project"


def _unlink_chat_id(chat_id: int) -> str:
    """Unlink a Telegram chat_id from its user."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE telegram_chat_id = %s",
            (chat_id,)
        ).fetchone()
        
        if not row:
            return "⚠️ This chat is not linked to any account."
        
        conn.execute(
            """UPDATE users
               SET telegram_chat_id = NULL,
                   telegram_link_code = NULL,
                   telegram_link_expires_at = NULL
               WHERE telegram_chat_id = %s""",
            (chat_id,)
        )
        conn.commit()
        
        logger.info(f"[TELEGRAM] Unlinked chat_id={chat_id}")
        return "✅ Account unlinked. Send /link {code} to link again."


# ── Extract text from Telegram update ───────────────────────

def _extract_message(update: dict) -> tuple[Optional[int], Optional[str], Optional[int]]:
    """
    Extract chat_id, text, and message_id from a Telegram update.
    Returns (chat_id, text, message_id) or (None, None, None).
    """
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return None, None, None
    
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    text = msg.get("text")
    message_id = msg.get("message_id")
    
    return chat_id, text, message_id


# ── Format AI response for Telegram ─────────────────────────

def _format_for_telegram(resp: dict) -> str:
    """
    Convert AI chat response dict to Telegram-friendly text.
    Strips complex JSON structures, keeps readable text.
    """
    resp_type = resp.get("type", "text")
    
    if resp_type == "text":
        return resp.get("text", resp.get("message", "Done."))
    
    elif resp_type == "execution":
        text = resp.get("text", "")
        # Include progress messages if present
        progress = resp.get("progress", [])
        if progress:
            parts = [text] if text else []
            for p in progress:
                msg = p.get("message", "")
                if msg:
                    parts.append(f"  • {msg}")
            return "\n".join(parts) if parts else "Done."
        return text or "Done."
    
    elif resp_type == "selection":
        # Convert selection to text list (Telegram has no native radio buttons)
        msg = resp.get("message", "Select a project:")
        options = resp.get("options", [])
        lines = [msg, ""]
        for i, opt in enumerate(options):
            lines.append(f"{i+1}. {opt['label']}  (send: `switch to {opt['value']}`)")
        return "\n".join(lines)
    
    elif resp_type == "confirmation":
        msg = resp.get("message", "Confirm?")
        return f"⚠️ {msg}\n\nReply *yes* to confirm or *no* to cancel."
    
    elif resp_type == "error":
        return f"❌ {resp.get('text', resp.get('message', 'An error occurred'))}"
    
    return resp.get("text", resp.get("message", "Done."))


# ── Webhook endpoint ────────────────────────────────────────

@router.post("/bot/telegram/webhook")
async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: Optional[str] = Header(None)):
    """
    Receive Telegram webhook updates.
    No auth header — verified by the secret token configured with setWebhook.
    """
    # Verify secret token
    if not _verify_secret(x_telegram_bot_api_secret_token):
        logger.warning("[TELEGRAM] Webhook rejected: invalid secret token")
        raise HTTPException(status_code=403, detail="Forbidden")
    
    update = await request.json()
    
    chat_id, text, message_id = _extract_message(update)
    if chat_id is None or text is None:
        return {"ok": True}  # Not a text message — ignore silently
    
    text = text.strip()
    logger.info(f"[TELEGRAM] Message from chat_id={chat_id}: {text[:100]}")
    
    # ── Handle commands ─────────────────────────────────────
    
    if text.startswith("/start"):
        await send_message(
            chat_id,
            "👋 *Welcome to DreamAgent Bot!*\n\n"
            "Control your projects from Telegram.\n\n"
            "To get started, link your account:\n"
            "1. Open your DreamAgent dashboard\n"
            "2. Go to Settings → Connect Telegram\n"
            "3. Copy the 6-character code\n"
            "4. Send it here: `/link YOURCODE`\n\n"
            "Once linked, try: `status`, `stop`, `start`, `restart`, `logs`",
            reply_to_message_id=message_id,
        )
        return {"ok": True}
    
    if text.startswith("/link"):
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            await send_message(chat_id, "Please send your link code: `/link YOURCODE`", reply_to_message_id=message_id)
            return {"ok": True}
        
        code = parts[1].strip()
        success, msg = _try_link_code(chat_id, code)
        await send_message(chat_id, msg, reply_to_message_id=message_id)
        return {"ok": True}
    
    if text.startswith("/unlink"):
        msg = _unlink_chat_id(chat_id)
        await send_message(chat_id, msg, reply_to_message_id=message_id)
        return {"ok": True}
    
    if text.startswith("/help"):
        await send_message(
            chat_id,
            "*DreamAgent Bot Commands*\n\n"
            "• `/link CODE` — Link your DreamAgent account\n"
            "• `/unlink` — Unlink this chat\n"
            "• `/help` — Show this help\n\n"
            "*Chat commands* (after linking):\n"
            "• `status` — Project status\n"
            "• `start` / `stop` / `restart`\n"
            "• `logs` — Recent logs\n"
            "• `switch to {project}` — Switch active project\n"
            "• Or just type naturally!",
            reply_to_message_id=message_id,
        )
        return {"ok": True}
    
    # ── Route to AI chat engine ─────────────────────────────
    
    user_id = _lookup_user_by_chat_id(chat_id)
    if not user_id:
        await send_message(
            chat_id,
            "🔒 Your Telegram is not linked yet.\n\n"
            "Send `/link YOURCODE` with the code from your DreamAgent dashboard.",
            reply_to_message_id=message_id,
        )
        return {"ok": True}
    
    # Use per-Telegram-user session
    session_id = f"tg_{chat_id}"
    
    try:
        # Send "typing..." indicator
        await send_message(chat_id, "⏳", reply_to_message_id=message_id)
    except:
        pass
    
    try:
        resp = await process_message(
            user_id=user_id,
            message=text,
            session_id=session_id,
            source="telegram",
        )
        
        reply_text = _format_for_telegram(resp)
        
        # Telegram has a 4096 char limit per message
        if len(reply_text) > 4000:
            reply_text = reply_text[:4000] + "\n\n... (truncated)"
        
        await send_message(chat_id, reply_text, reply_to_message_id=message_id)
        
    except Exception as e:
        logger.error(f"[TELEGRAM] Error processing message: {e}", exc_info=True)
        await send_message(
            chat_id,
            "❌ Sorry, something went wrong processing your request. Please try again.",
            reply_to_message_id=message_id,
        )
    
    return {"ok": True}


# ── Setup endpoints (admin/internal) ────────────────────────

@router.post("/bot/telegram/setwebhook")
async def setup_webhook():
    """
    Register the webhook URL with Telegram.
    Call this once after deploying.
    """
    if not is_configured():
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN not configured"}
    
    webhook_url = f"https://{CONTROL_API_HOST}/bot/telegram/webhook"
    result = await tg_set_webhook(webhook_url)
    
    bot_info = await get_bot_info()
    bot_username = bot_info.get("result", {}).get("username", "unknown") if bot_info.get("ok") else "unknown"
    
    return {
        "webhook_result": result,
        "webhook_url": webhook_url,
        "bot_username": f"@{bot_username}",
    }


@router.delete("/bot/telegram/webhook")
async def remove_webhook():
    """Remove webhook (disable Telegram bot)."""
    result = await tg_delete_webhook()
    return {"result": result}
