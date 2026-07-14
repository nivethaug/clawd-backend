"""
Bot Account Linking API
Endpoints for generating shared link codes and checking bot connection status.
"""

import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Header
from pydantic import BaseModel

from database_postgres import get_db
from utils.auth_helpers import get_user_id_from_token
from services.telegram_client import is_configured as telegram_configured

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Response Models ─────────────────────────────────────────

class LinkCodeResponse(BaseModel):
    code: str
    bot_username: str
    expires_in: int  # seconds


class LinkStatusResponse(BaseModel):
    linked: bool
    telegram_chat_id: Optional[int] = None
    discord_user_id: Optional[str] = None
    slack_user_id: Optional[str] = None
    slack_team_id: Optional[str] = None


# ── Helpers ─────────────────────────────────────────────────

def _generate_code() -> str:
    """Generate a 6-char alphanumeric code (no ambiguous chars)."""
    import string
    alphabet = string.ascii_uppercase + string.digits
    # Remove ambiguous chars: 0/O, 1/I
    alphabet = alphabet.replace("O", "").replace("0", "").replace("I", "").replace("1", "")
    return "".join(secrets.choice(alphabet) for _ in range(6))


# ── Endpoints ───────────────────────────────────────────────

@router.post("/link/generate", response_model=LinkCodeResponse)
async def generate_link_code(authorization: Optional[str] = Header(None)):
    """
    Generate a one-time code to link the user's bot account.
    The user can send the code to Telegram, Discord, or Slack within 10 minutes.
    """
    user_id = get_user_id_from_token(authorization)

    if not telegram_configured():
        logger.warning("[BOT-LINK] Telegram bot not configured — code will still be generated")

    code = _generate_code()
    expires_at = datetime.utcnow() + timedelta(minutes=10)

    with get_db() as conn:
        conn.execute(
            """UPDATE users
               SET telegram_link_code = %s,
                   telegram_link_expires_at = %s,
                   discord_link_code = %s,
                   discord_link_expires_at = %s,
                   slack_link_code = %s,
                   slack_link_expires_at = %s
               WHERE id = %s""",
            (code, expires_at, code, expires_at, code, expires_at, user_id)
        )
        conn.commit()

    logger.info(f"[BOT-LINK] Generated code for user {user_id}")

    return LinkCodeResponse(
        code=code,
        bot_username="@DreamAgentBot",
        expires_in=600,
    )


@router.get("/link/status", response_model=LinkStatusResponse)
async def get_link_status(authorization: Optional[str] = Header(None)):
    """Check if the user's bot accounts are linked."""
    user_id = get_user_id_from_token(authorization)

    with get_db() as conn:
        row = conn.execute(
            "SELECT telegram_chat_id, discord_user_id, slack_user_id, slack_team_id FROM users WHERE id = %s",
            (user_id,)
        ).fetchone()

    if row and (row.get("telegram_chat_id") or row.get("discord_user_id") or row.get("slack_user_id")):
        return LinkStatusResponse(
            linked=True,
            telegram_chat_id=row.get("telegram_chat_id"),
            discord_user_id=row.get("discord_user_id"),
            slack_user_id=row.get("slack_user_id"),
            slack_team_id=row.get("slack_team_id"),
        )

    return LinkStatusResponse(
        linked=False,
        telegram_chat_id=row.get("telegram_chat_id") if row else None,
        discord_user_id=row.get("discord_user_id") if row else None,
        slack_user_id=row.get("slack_user_id") if row else None,
        slack_team_id=row.get("slack_team_id") if row else None,
    )


@router.delete("/link")
async def unlink_telegram(authorization: Optional[str] = Header(None)):
    """Unlink the user's Telegram account."""
    user_id = get_user_id_from_token(authorization)

    with get_db() as conn:
        conn.execute(
            """UPDATE users
               SET telegram_chat_id = NULL,
                   telegram_link_code = NULL,
                   telegram_link_expires_at = NULL
               WHERE id = %s""",
            (user_id,)
        )
        conn.commit()

    logger.info(f"[BOT-LINK] Unlinked Telegram for user {user_id}")
    return {"message": "Telegram account unlinked successfully"}


@router.delete("/discord-link")
async def unlink_discord(authorization: Optional[str] = Header(None)):
    """Unlink the user's Discord account."""
    user_id = get_user_id_from_token(authorization)

    with get_db() as conn:
        conn.execute(
            """UPDATE users
               SET discord_user_id = NULL,
                   discord_link_code = NULL,
                   discord_link_expires_at = NULL
               WHERE id = %s""",
            (user_id,),
        )
        conn.commit()

    logger.info(f"[BOT-LINK] Unlinked Discord for user {user_id}")
    return {"message": "Discord account unlinked successfully"}


@router.delete("/slack-link")
async def unlink_slack(authorization: Optional[str] = Header(None)):
    """Unlink the user's Slack account."""
    user_id = get_user_id_from_token(authorization)

    with get_db() as conn:
        conn.execute(
            """UPDATE users
               SET slack_user_id = NULL,
                   slack_team_id = NULL,
                   slack_link_code = NULL,
                   slack_link_expires_at = NULL
               WHERE id = %s""",
            (user_id,),
        )
        conn.commit()

    logger.info(f"[BOT-LINK] Unlinked Slack for user {user_id}")
    return {"message": "Slack account unlinked successfully"}
