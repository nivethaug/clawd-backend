#!/usr/bin/env python3
"""
Validate Router - Pre-validation endpoint for project credentials.

Verifies Telegram bot tokens, Discord bot tokens, and scheduler
sender channels (Telegram, Discord, Email, API) before project creation.

Usage:
    POST /api/validate/credentials
    {
        "type_id": 2,
        "bot_token": "123456:ABC..."
    }

    POST /api/validate/credentials
    {
        "type_id": 5,
        "telegram_bot_token": "123456:ABC...",
        "email_to": "user@email.com"
    }
"""

from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter

from utils.logger import logger

router = APIRouter()


class ValidateCredentialsRequest(BaseModel):
    type_id: int
    # Telegram bot (type_id=2) or Discord bot (type_id=3)
    bot_token: Optional[str] = None
    # Scheduler channels (type_id=5)
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    discord_webhook_url: Optional[str] = None
    email_to: Optional[str] = None
    api_endpoint: Optional[str] = None


@router.post("/credentials")
async def validate_credentials(request: ValidateCredentialsRequest):
    """
    Validate credentials for a project type before creation.

    type_id=1 (Website): No validation needed, returns valid immediately.
    type_id=2 (Telegram bot): Validates bot_token via Telegram getMe.
    type_id=3 (Discord bot): Validates bot_token via Discord users/@me.
    type_id=5 (Scheduler): Validates each provided sender channel.
    """
    type_id = request.type_id

    # Website - no credentials to validate
    if type_id == 1:
        return {"valid": True, "type_id": type_id, "channels": {}}

    # Telegram bot
    if type_id == 2:
        if not request.bot_token:
            return {"valid": False, "type_id": type_id, "error": "bot_token is required for Telegram bot projects"}

        try:
            from services.telegram.validator import validate_telegram_token
            is_valid, info = validate_telegram_token(request.bot_token)

            if is_valid:
                logger.info(f"✅ Telegram bot token validated: @{info.get('username')}")
                return {
                    "valid": True,
                    "type_id": type_id,
                    "channels": {
                        "telegram": {
                            "valid": True,
                            "bot_id": info.get("bot_id"),
                            "bot_username": info.get("username"),
                            "first_name": info.get("first_name"),
                        }
                    }
                }
            else:
                logger.warning(f"❌ Telegram bot token invalid: {info.get('error')}")
                return {
                    "valid": False,
                    "type_id": type_id,
                    "error": info.get("error", "Invalid token"),
                    "channels": {
                        "telegram": {"valid": False, "error": info.get("error")}
                    }
                }
        except Exception as e:
            logger.error(f"Telegram validation error: {e}")
            return {"valid": False, "type_id": type_id, "error": str(e)}

    # Discord bot
    if type_id == 3:
        if not request.bot_token:
            return {"valid": False, "type_id": type_id, "error": "bot_token is required for Discord bot projects"}

        try:
            from services.discord.validator import validate_discord_token
            is_valid, info = validate_discord_token(request.bot_token)

            if is_valid:
                logger.info(f"✅ Discord bot token validated: {info.get('username')}")
                return {
                    "valid": True,
                    "type_id": type_id,
                    "channels": {
                        "discord": {
                            "valid": True,
                            "bot_id": info.get("bot_id"),
                            "username": info.get("username"),
                            "invite_url": info.get("invite_url"),
                        }
                    }
                }
            else:
                logger.warning(f"❌ Discord bot token invalid: {info.get('error')}")
                return {
                    "valid": False,
                    "type_id": type_id,
                    "error": info.get("error", "Invalid token"),
                    "channels": {
                        "discord": {"valid": False, "error": info.get("error")}
                    }
                }
        except Exception as e:
            logger.error(f"Discord validation error: {e}")
            return {"valid": False, "type_id": type_id, "error": str(e)}

    # Scheduler
    if type_id == 5:
        # At least one channel must be provided
        has_any = any([
            request.telegram_bot_token,
            request.discord_webhook_url,
            request.email_to,
            request.api_endpoint,
        ])
        if not has_any:
            return {
                "valid": False,
                "type_id": type_id,
                "error": "At least one sender channel is required for Scheduler projects"
            }

        try:
            from services.scheduler.validator import validate_scheduler_channels
            result = validate_scheduler_channels(
                telegram_bot_token=request.telegram_bot_token,
                telegram_chat_id=request.telegram_chat_id,
                discord_webhook_url=request.discord_webhook_url,
                email_to=request.email_to,
                api_endpoint=request.api_endpoint,
            )

            result["type_id"] = type_id
            if result["valid"]:
                logger.info(f"✅ Scheduler channels validated")
            else:
                logger.warning(f"❌ Scheduler channel validation failed")
            return result
        except Exception as e:
            logger.error(f"Scheduler validation error: {e}")
            return {"valid": False, "type_id": type_id, "error": str(e)}

    # Unknown type
    return {"valid": False, "type_id": type_id, "error": f"Unknown type_id: {type_id}"}
