"""
Discord Interactions API client for the DreamAgent control bot.

This is intentionally separate from services.discord.*, which belongs to
generated Discord bot projects.
"""

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DISCORD_API_BASE = os.getenv("DISCORD_API_BASE", "https://discord.com/api/v10")
DISCORD_CONTROL_BOT_TOKEN = os.getenv("DISCORD_CONTROL_BOT_TOKEN", "")
DISCORD_PUBLIC_KEY = os.getenv("DISCORD_PUBLIC_KEY", "")
DISCORD_APPLICATION_ID = os.getenv("DISCORD_APPLICATION_ID", "")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID", "")
DISCORD_INTERACTIONS_SECRET = os.getenv("DISCORD_INTERACTIONS_SECRET", "")


def is_configured() -> bool:
    return bool(DISCORD_CONTROL_BOT_TOKEN and DISCORD_APPLICATION_ID and DISCORD_PUBLIC_KEY)


def _headers() -> dict:
    return {
        "Authorization": f"Bot {DISCORD_CONTROL_BOT_TOKEN}",
        "Content-Type": "application/json",
    }


def truncate_content(text: str, limit: int = 1900) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 18)] + "\n\n... (truncated)"


async def edit_original_response(
    interaction_token: str,
    content: str,
    components: Optional[list] = None,
) -> bool:
    """Edit the deferred original interaction response."""
    if not DISCORD_APPLICATION_ID:
        logger.error("[DISCORD-CONTROL] DISCORD_APPLICATION_ID not configured")
        return False

    payload: dict = {"content": truncate_content(content)}
    if components is not None:
        payload["components"] = components

    url = f"{DISCORD_API_BASE}/webhooks/{DISCORD_APPLICATION_ID}/{interaction_token}/messages/@original"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.patch(url, json=payload)
            if resp.status_code >= 300:
                logger.error("[DISCORD-CONTROL] edit original failed %s: %s", resp.status_code, resp.text[:500])
                return False
            return True
    except Exception as e:
        logger.error("[DISCORD-CONTROL] edit original error: %s", e, exc_info=True)
        return False


async def create_followup_message(
    interaction_token: str,
    content: str,
    components: Optional[list] = None,
    ephemeral: bool = True,
) -> bool:
    """Send a follow-up message for an interaction."""
    if not DISCORD_APPLICATION_ID:
        logger.error("[DISCORD-CONTROL] DISCORD_APPLICATION_ID not configured")
        return False

    payload: dict = {"content": truncate_content(content)}
    if ephemeral:
        payload["flags"] = 64
    if components is not None:
        payload["components"] = components

    url = f"{DISCORD_API_BASE}/webhooks/{DISCORD_APPLICATION_ID}/{interaction_token}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code >= 300:
                logger.error("[DISCORD-CONTROL] followup failed %s: %s", resp.status_code, resp.text[:500])
                return False
            return True
    except Exception as e:
        logger.error("[DISCORD-CONTROL] followup error: %s", e, exc_info=True)
        return False


CONTROL_COMMANDS = [
    {"name": "switch", "description": "Select or change project", "type": 1, "options": [
        {"name": "project", "description": "Project name or domain", "type": 3, "required": False}
    ]},
    {"name": "sessions", "description": "Select a project session", "type": 1},
    {"name": "newsession", "description": "Create and select a project session", "type": 1, "options": [
        {"name": "label", "description": "Session label", "type": 3, "required": True}
    ]},
    {"name": "clearsession", "description": "Clear selected session", "type": 1},
    {"name": "complete", "description": "Release selected session", "type": 1},
    {"name": "current", "description": "Show active project and session", "type": 1},
    {"name": "billing", "description": "Show plan and credits", "type": 1},
    {"name": "status", "description": "Check project status", "type": 1},
    {"name": "logs", "description": "Show recent logs", "type": 1},
    {"name": "start", "description": "Start active project", "type": 1},
    {"name": "stop", "description": "Stop active project", "type": 1},
    {"name": "restart", "description": "Restart active project", "type": 1},
    {"name": "chat", "description": "Continue the selected project session", "type": 1, "options": [
        {"name": "message", "description": "What should DreamAgent do?", "type": 3, "required": True}
    ]},
    {"name": "link", "description": "Link your DreamAgent account", "type": 1, "options": [
        {"name": "code", "description": "Link code from DreamAgent", "type": 3, "required": True}
    ]},
    {"name": "unlink", "description": "Unlink this Discord account", "type": 1},
    {"name": "help", "description": "How to use DreamAgent Bot", "type": 1},
]


async def register_commands(guild_id: Optional[str] = None) -> dict:
    """Register Discord slash commands globally or to one guild for faster dev updates."""
    if not DISCORD_CONTROL_BOT_TOKEN or not DISCORD_APPLICATION_ID:
        return {"ok": False, "error": "Discord control bot token/application id not configured"}

    target_guild = guild_id or DISCORD_GUILD_ID
    if target_guild:
        url = f"{DISCORD_API_BASE}/applications/{DISCORD_APPLICATION_ID}/guilds/{target_guild}/commands"
    else:
        url = f"{DISCORD_API_BASE}/applications/{DISCORD_APPLICATION_ID}/commands"

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.put(url, headers=_headers(), json=CONTROL_COMMANDS)
            data = resp.json() if resp.content else {}
            return {
                "ok": resp.status_code < 300,
                "status_code": resp.status_code,
                "scope": "guild" if target_guild else "global",
                "guild_id": target_guild,
                "result": data,
            }
    except Exception as e:
        logger.error("[DISCORD-CONTROL] register commands error: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


async def delete_commands(guild_id: Optional[str] = None) -> dict:
    """Delete registered Discord slash commands by replacing the set with an empty list."""
    if not DISCORD_CONTROL_BOT_TOKEN or not DISCORD_APPLICATION_ID:
        return {"ok": False, "error": "Discord control bot token/application id not configured"}

    target_guild = guild_id or DISCORD_GUILD_ID
    if target_guild:
        url = f"{DISCORD_API_BASE}/applications/{DISCORD_APPLICATION_ID}/guilds/{target_guild}/commands"
    else:
        url = f"{DISCORD_API_BASE}/applications/{DISCORD_APPLICATION_ID}/commands"

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.put(url, headers=_headers(), json=[])
            data = resp.json() if resp.content else {}
            return {
                "ok": resp.status_code < 300,
                "status_code": resp.status_code,
                "scope": "guild" if target_guild else "global",
                "guild_id": target_guild,
                "result": data,
            }
    except Exception as e:
        logger.error("[DISCORD-CONTROL] delete commands error: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}
