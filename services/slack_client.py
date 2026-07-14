"""
Slack API client for the DreamAgent control bot.

This is a transport helper only. Project/session logic lives in the shared
DevOps chat and external session runner.
"""

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

SLACK_API_BASE = os.getenv("SLACK_API_BASE", "https://slack.com/api")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET", "")
SLACK_APP_ID = os.getenv("SLACK_APP_ID", "")
SLACK_CLIENT_ID = os.getenv("SLACK_CLIENT_ID", "")
SLACK_CLIENT_SECRET = os.getenv("SLACK_CLIENT_SECRET", "")
SLACK_INSTALL_URL = os.getenv("SLACK_INSTALL_URL", "")
SLACK_INTERACTIONS_SECRET = os.getenv("SLACK_INTERACTIONS_SECRET", "")


def is_configured() -> bool:
    return bool(SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
    }


def truncate_content(text: str, limit: int = 2900) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 18)] + "\n\n... (truncated)"


def _button(text: str, action_id: str, style: Optional[str] = None) -> dict:
    button = {
        "type": "button",
        "text": {"type": "plain_text", "text": text[:75]},
        "action_id": action_id[:255],
    }
    if style:
        button["style"] = style
    return button


def action_blocks(kind: str = "project") -> list:
    if kind == "session":
        rows = [
            [("Current", "action:current", None), ("Switch Project", "action:switch", None)],
            [("Sessions", "action:sessions", None), ("New Session", "action:newsession", None)],
            [("Complete", "action:complete", "primary"), ("Clear Session", "action:clearsession", None)],
            [("Status", "action:status", None), ("Logs", "action:logs", None)],
            [("Billing", "action:billing", None), ("Help", "action:help", None)],
        ]
    elif kind == "busy":
        rows = [
            [("Current", "action:current", None), ("Sessions", "action:sessions", None)],
            [("Complete", "action:complete", "primary"), ("Clear Session", "action:clearsession", None)],
            [("Billing", "action:billing", None), ("Help", "action:help", None)],
        ]
    else:
        rows = [
            [("Current", "action:current", None), ("Switch Project", "action:switch", None)],
            [("Sessions", "action:sessions", None), ("New Session", "action:newsession", None)],
            [("Status", "action:status", None), ("Logs", "action:logs", None)],
            [("Restart", "action:restart", None), ("Billing", "action:billing", None)],
            [("Help", "action:help", None)],
        ]

    blocks = []
    for row in rows:
        blocks.append({
            "type": "actions",
            "elements": [_button(label, action, style) for label, action, style in row],
        })
    return blocks


def selection_blocks(resp: dict) -> Optional[list]:
    if resp.get("type") != "selection":
        return None
    options = resp.get("options") or []
    if not options:
        return None

    intent = resp.get("intent", {}) or {}
    tool_name = intent.get("tool")
    intent_args = intent.get("args", {}) or {}
    buttons = []
    for opt in options[:25]:
        if tool_name == "set_active_project_session":
            project_domain = intent_args.get("project_domain", "")
            action_id = f"session:set:{project_domain}:{opt['value']}" if project_domain else f"session:set:{opt['value']}"
        else:
            action_id = f"switch:{opt['value']}"
        buttons.append(_button(str(opt["label"]), action_id, "primary"))

    blocks = []
    for idx in range(0, len(buttons), 3):
        blocks.append({
            "type": "actions",
            "elements": buttons[idx:idx + 3],
        })
    return blocks


async def respond(response_url: str, text: str, blocks: Optional[list] = None, response_type: str = "ephemeral") -> bool:
    payload = {
        "response_type": response_type,
        "replace_original": False,
        "text": truncate_content(text),
    }
    if blocks is not None:
        payload["blocks"] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": truncate_content(text)}},
            *blocks,
        ]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(response_url, json=payload)
            if resp.status_code >= 300:
                logger.error("[SLACK-CONTROL] response_url failed %s: %s", resp.status_code, resp.text[:500])
                return False
            return True
    except Exception as e:
        logger.error("[SLACK-CONTROL] response_url error: %s", e, exc_info=True)
        return False


async def post_message(channel: str, text: str, blocks: Optional[list] = None) -> bool:
    if not SLACK_BOT_TOKEN:
        logger.error("[SLACK-CONTROL] SLACK_BOT_TOKEN not configured")
        return False
    payload = {"channel": channel, "text": truncate_content(text)}
    if blocks is not None:
        payload["blocks"] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": truncate_content(text)}},
            *blocks,
        ]
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{SLACK_API_BASE}/chat.postMessage", headers=_headers(), json=payload)
            data = resp.json() if resp.content else {}
            if resp.status_code >= 300 or not data.get("ok"):
                logger.error("[SLACK-CONTROL] chat.postMessage failed %s: %s", resp.status_code, str(data)[:500])
                return False
            return True
    except Exception as e:
        logger.error("[SLACK-CONTROL] chat.postMessage error: %s", e, exc_info=True)
        return False
