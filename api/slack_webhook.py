"""
Slack webhook handler for the DreamAgent control bot.

Slack is only a transport. Project/session behavior is delegated to the shared
DevOps chat and selected-session runner used by web, Telegram, and Discord.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime
from typing import Any, Optional
from urllib.parse import parse_qs

from fastapi import APIRouter, Header, HTTPException, Request

from api.ai_chat import process_message
from database_postgres import get_db
from services.external_session_chat import run_selected_session_chat
from services.session_lock_service import SessionLockService
from services.slack_client import (
    SLACK_INTERACTIONS_SECRET,
    SLACK_SIGNING_SECRET,
    action_blocks,
    is_configured,
    post_message,
    respond,
    selection_blocks,
    truncate_content,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _verify_signature(body: bytes, timestamp: Optional[str], signature: Optional[str]) -> bool:
    if not SLACK_SIGNING_SECRET:
        logger.error("[SLACK-CONTROL] SLACK_SIGNING_SECRET not configured")
        return False
    if not timestamp or not signature:
        logger.warning("[SLACK-CONTROL] Missing Slack signature headers")
        return False
    try:
        ts = int(timestamp)
    except Exception:
        return False
    if abs(int(time.time()) - ts) > 60 * 5:
        logger.warning("[SLACK-CONTROL] Rejected stale Slack request timestamp=%s", timestamp)
        return False

    base = b"v0:" + timestamp.encode("utf-8") + b":" + body
    digest = "v0=" + hmac.new(SLACK_SIGNING_SECRET.encode("utf-8"), base, hashlib.sha256).hexdigest()
    ok = hmac.compare_digest(digest, signature)
    if not ok:
        logger.warning("[SLACK-CONTROL] Invalid Slack signature body_bytes=%s", len(body or b""))
    return ok


async def _verified_body(
    request: Request,
    x_slack_request_timestamp: Optional[str],
    x_slack_signature: Optional[str],
) -> bytes:
    body = await request.body()
    logger.info(
        "[SLACK-CONTROL] Request received path=%s content_type=%s body_bytes=%s",
        request.url.path,
        request.headers.get("content-type"),
        len(body or b""),
    )
    if not _verify_signature(body, x_slack_request_timestamp, x_slack_signature):
        raise HTTPException(status_code=401, detail="invalid slack signature")
    return body


def _parse_form(body: bytes) -> dict[str, str]:
    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: values[0] if values else "" for key, values in parsed.items()}


def _session_key(team_id: str, slack_user_id: str) -> str:
    return f"sl_{team_id}_{slack_user_id}"


def _lookup_user_by_slack(team_id: str, slack_user_id: str) -> Optional[int]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id
               FROM users
               WHERE slack_team_id = %s
                 AND slack_user_id = %s
               ORDER BY id DESC""",
            (team_id, slack_user_id),
        ).fetchall()
    if len(rows) > 1:
        logger.warning(
            "[SLACK-CONTROL] Slack identity team=%s user=%s linked to multiple DreamAgent users: %s",
            team_id,
            slack_user_id,
            [row["id"] for row in rows],
        )
    return rows[0]["id"] if rows else None


def _try_link_code(team_id: str, slack_user_id: str, code: str) -> tuple[bool, str]:
    code = (code or "").upper().strip()
    with get_db() as conn:
        row = conn.execute(
            """SELECT id, slack_link_expires_at
               FROM users
               WHERE slack_link_code = %s""",
            (code,),
        ).fetchone()
        if not row:
            return False, f"Invalid code `{code}`. Please check and try again."

        expires_at = row.get("slack_link_expires_at")
        if expires_at and datetime.utcnow() > expires_at:
            return False, "This code has expired. Please generate a new one in DreamAgent."

        existing_rows = conn.execute(
            """SELECT id
               FROM users
               WHERE slack_team_id = %s
                 AND slack_user_id = %s
                 AND id != %s""",
            (team_id, slack_user_id, row["id"]),
        ).fetchall()
        if existing_rows:
            logger.warning(
                "[SLACK-CONTROL] Relinking Slack team=%s user=%s from users=%s to user_id=%s",
                team_id,
                slack_user_id,
                [existing["id"] for existing in existing_rows],
                row["id"],
            )
            conn.execute(
                """UPDATE users
                   SET slack_user_id = NULL,
                       slack_team_id = NULL
                   WHERE slack_team_id = %s
                     AND slack_user_id = %s
                     AND id != %s""",
                (team_id, slack_user_id, row["id"]),
            )

        conn.execute(
            """UPDATE users
               SET slack_user_id = %s,
                   slack_team_id = %s,
                   slack_link_code = NULL,
                   slack_link_expires_at = NULL
               WHERE id = %s""",
            (slack_user_id, team_id, row["id"]),
        )
        conn.commit()

    logger.info("[SLACK-CONTROL] Linked Slack team=%s user=%s to user_id=%s", team_id, slack_user_id, row["id"])
    return True, "Account linked successfully. Use `/dreamagent switch` to choose a project."


def _unlink_slack(team_id: str, slack_user_id: str) -> str:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE slack_team_id = %s AND slack_user_id = %s",
            (team_id, slack_user_id),
        ).fetchone()
        if not row:
            return "This Slack account is not linked."
        conn.execute(
            """UPDATE users
               SET slack_user_id = NULL,
                   slack_team_id = NULL,
                   slack_link_code = NULL,
                   slack_link_expires_at = NULL
               WHERE slack_team_id = %s
                 AND slack_user_id = %s""",
            (team_id, slack_user_id),
        )
        conn.commit()
    return "Slack account unlinked."


def _format_for_slack(resp: dict) -> str:
    resp_type = resp.get("type", "text")
    if resp_type == "text":
        return resp.get("text", resp.get("message", "Done."))
    if resp_type == "execution":
        text = resp.get("text", "")
        progress = resp.get("progress", [])
        if progress:
            parts = [text] if text else []
            for p in progress:
                msg = p.get("message", "")
                if msg:
                    parts.append(f"- {msg}")
            return "\n".join(parts) if parts else "Done."
        return text or "Done."
    if resp_type == "selection":
        return resp.get("message", "Select an option:")
    if resp_type == "confirmation":
        return f"Confirm: {resp.get('message', 'Continue?')}"
    if resp_type == "error":
        return f"Error: {resp.get('text', resp.get('message', 'An error occurred'))}"
    return resp.get("text", resp.get("message", "Done."))


def _format_billing_summary(user_id: int) -> str:
    from services.bot_billing_formatter import format_billing_summary

    with get_db() as conn:
        return format_billing_summary(conn, user_id, bold_marker="*")


def _help_text() -> str:
    return (
        "*DreamAgent Slack Bot*\n\n"
        "Start with the buttons below whenever possible.\n\n"
        "*Fast workflow*\n"
        "1. Link once with `/dreamagent link CODE`\n"
        "2. Click *Switch Project* and pick a project\n"
        "3. Click *Sessions* or *New Session* for edit work\n"
        "4. Use `/dreamagent project MESSAGE` for normal project questions\n"
        "5. Use `/dreamagent chat MESSAGE` for selected-session edits\n\n"
        "In the DreamAgent app DM, ordinary messages continue the selected edit session."
    )


def _normalize_slash_text(text: str) -> tuple[str, str]:
    raw = (text or "").strip()
    if not raw:
        return "help", "/dreamagent help"
    parts = raw.split(maxsplit=1)
    action = parts[0].lower()
    arg = parts[1].strip() if len(parts) == 2 else ""
    if action == "newsession":
        return "newsession", f"/newsession {arg or 'Slack session'}"
    if action == "project":
        return "project", arg
    if action == "chat":
        return "chat", arg
    if action == "link":
        return "link", arg
    return action, f"/{action}" if not arg else f"/{action} {arg}"


def _normalize_slack_command(command: str, text: str) -> tuple[str, str]:
    command = (command or "").strip().lower()
    if command == "/dream-switch":
        target = (text or "").strip()
        return "switch", f"/switch {target}" if target else "/switch"
    return _normalize_slash_text(text)


def _normalize_natural_action(text: str) -> Optional[str]:
    value = (text or "").strip().lower()
    aliases = {
        "help": "help",
        "menu": "help",
        "commands": "help",
        "current": "current",
        "current project": "current",
        "current session": "current",
        "where am i": "current",
        "billing": "billing",
        "credits": "billing",
        "my credits": "billing",
        "balance": "billing",
        "my balance": "billing",
        "plan": "billing",
        "my plan": "billing",
        "sessions": "sessions",
        "show sessions": "sessions",
        "list sessions": "sessions",
        "switch session": "sessions",
        "select session": "sessions",
        "clear session": "clearsession",
        "leave session": "clearsession",
        "complete": "complete",
        "complete session": "complete",
        "finish session": "complete",
        "release session": "complete",
        "status": "status",
        "project status": "status",
        "logs": "logs",
        "show logs": "logs",
        "recent logs": "logs",
        "restart": "restart",
        "start": "start",
        "stop": "stop",
    }
    if value in aliases:
        return aliases[value]
    if value.startswith("new session") or value.startswith("newsession"):
        return "newsession"
    return None


def _get_selected_project_session(user_id: int, slack_session_key: str) -> Optional[dict]:
    try:
        from utils.devops_session_context import get_devops_session_context

        context = get_devops_session_context()
        session_id = context.get_user_active_session_id(user_id)
        if not session_id:
            session_id = context.get_ai_active_session_id(slack_session_key)
        if not session_id:
            return None
        session = context.get_session(user_id, int(session_id))
        if not session:
            context.clear_context(user_id, slack_session_key)
            return None
        return session
    except Exception as e:
        logger.warning("[SLACK-SESSION] Failed to resolve selected session: %s", e, exc_info=True)
        return None


async def _send_result(response_url: Optional[str], channel: Optional[str], text: str, blocks: Optional[list] = None) -> None:
    if response_url:
        await respond(response_url, text, blocks)
    elif channel:
        await post_message(channel, text, blocks)


async def _run_slack_action(
    *,
    user_id: int,
    team_id: str,
    slack_user_id: str,
    action: str,
    message_text: str,
    response_url: Optional[str] = None,
    channel: Optional[str] = None,
) -> None:
    session_key = _session_key(team_id, slack_user_id)

    if action == "help":
        await _send_result(response_url, channel, _help_text(), action_blocks())
        return

    if action == "billing":
        await _send_result(response_url, channel, _format_billing_summary(user_id), action_blocks())
        return

    if action == "clearsession":
        from utils.devops_session_context import get_devops_session_context

        get_devops_session_context().clear_context(user_id, session_key)
        await _send_result(response_url, channel, "Cleared the selected session. Project selection is unchanged.", action_blocks())
        return

    if action == "chat":
        selected = _get_selected_project_session(user_id, session_key)
        if not selected:
            await _send_result(response_url, channel, "No active session selected. Use `/dreamagent sessions` or `/dreamagent newsession LABEL` first.", action_blocks())
            return

        processing_result = SessionLockService.acquire_processing(int(selected["id"]), "slack")
        if not processing_result.get("success"):
            session_label = selected.get("label") or f"session #{selected['id']}"
            active_channel = processing_result.get("processing_channel") or "another client"
            await _send_result(
                response_url,
                channel,
                f"Still working on the previous message in `{session_label}`. Current channel: {active_channel}.",
                action_blocks("busy"),
            )
            return

        result = await run_selected_session_chat(
            user_id=user_id,
            selected_session=selected,
            text=message_text,
            channel="slack",
            processing_already_acquired=True,
        )
        kind = "busy" if result.get("status") == "busy" else "session"
        await _send_result(response_url, channel, result.get("message") or "Session chat completed.", action_blocks(kind))
        return

    if action == "project":
        resp = await process_message(user_id=user_id, message=message_text, session_id=session_key, source="slack")
        await _send_result(response_url, channel, _format_for_slack(resp), selection_blocks(resp) or action_blocks())
        return

    mapped = {
        "switch": "switch project",
        "current": "current session",
        "sessions": "sessions",
        "complete": "complete session",
        "status": "status",
        "logs": "logs",
        "restart": "restart",
        "start": "start",
        "stop": "stop",
    }
    if action == "switch" and len(message_text.split(maxsplit=1)) == 2:
        target = message_text.split(maxsplit=1)[1].strip()
        if target:
            mapped["switch"] = f"switch to {target}"
    if action == "newsession":
        raw_message = (message_text or "").strip()
        lower_message = raw_message.lower()
        if lower_message.startswith("new session"):
            label = raw_message[len("new session"):].strip()
        elif lower_message.startswith("newsession"):
            label = raw_message[len("newsession"):].strip()
        else:
            raw = raw_message.split(maxsplit=1)
            label = raw[1].strip() if len(raw) == 2 else ""
        mapped_message = f"new session {label or 'Slack session'}"
    else:
        mapped_message = mapped.get(action)

    if not mapped_message:
        await _send_result(response_url, channel, "I don't recognize that action yet.", action_blocks())
        return

    resp = await process_message(user_id=user_id, message=mapped_message, session_id=session_key, source="slack")
    kind = "session" if action in {"current", "sessions", "complete"} else "project"
    await _send_result(response_url, channel, _format_for_slack(resp), selection_blocks(resp) or action_blocks(kind))


async def _handle_action_id(action_id: str, user_id: int, team_id: str, slack_user_id: str, response_url: str) -> None:
    session_key = _session_key(team_id, slack_user_id)
    if action_id.startswith("action:"):
        action = action_id[len("action:"):]
        await _run_slack_action(
            user_id=user_id,
            team_id=team_id,
            slack_user_id=slack_user_id,
            action=action,
            message_text=f"/{action}",
            response_url=response_url,
        )
        return
    if action_id.startswith("switch:"):
        project_domain = action_id[len("switch:"):]
        resp = await process_message(user_id=user_id, message=f"switch to {project_domain}", session_id=session_key, source="slack")
        await respond(response_url, _format_for_slack(resp), selection_blocks(resp) or action_blocks())
        return
    if action_id.startswith("session:set:"):
        raw_payload = action_id[len("session:set:"):]
        parts = raw_payload.rsplit(":", 1)
        if len(parts) == 2:
            project_domain, raw_session_id = parts
            await process_message(user_id=user_id, message=f"switch to {project_domain}", session_id=session_key, source="slack")
        else:
            raw_session_id = raw_payload
        resp = await process_message(user_id=user_id, message=f"select session {raw_session_id}", session_id=session_key, source="slack")
        await respond(response_url, _format_for_slack(resp), selection_blocks(resp) or action_blocks("session"))
        return
    await respond(response_url, "Unknown button action.", action_blocks())


@router.post("/bot/slack/commands")
async def slack_commands(
    request: Request,
    x_slack_request_timestamp: Optional[str] = Header(None, alias="X-Slack-Request-Timestamp"),
    x_slack_signature: Optional[str] = Header(None, alias="X-Slack-Signature"),
):
    body = await _verified_body(request, x_slack_request_timestamp, x_slack_signature)
    form = _parse_form(body)
    team_id = form.get("team_id", "")
    slack_user_id = form.get("user_id", "")
    response_url = form.get("response_url", "")
    action, message_text = _normalize_slack_command(form.get("command", ""), form.get("text", ""))

    if action == "help":
        return {"response_type": "ephemeral", "text": _help_text(), "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": _help_text()}}, *action_blocks()]}

    if action == "link":
        ok, msg = _try_link_code(team_id, slack_user_id, message_text)
        return {"response_type": "ephemeral", "text": msg, "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": msg}}, *(action_blocks() if ok else [])]}

    if action == "unlink":
        return {"response_type": "ephemeral", "text": _unlink_slack(team_id, slack_user_id)}

    user_id = _lookup_user_by_slack(team_id, slack_user_id)
    if not user_id:
        return {"response_type": "ephemeral", "text": "Your Slack is not linked. Use `/dreamagent link CODE` first."}

    asyncio.create_task(_run_slack_action(
        user_id=user_id,
        team_id=team_id,
        slack_user_id=slack_user_id,
        action=action,
        message_text=message_text,
        response_url=response_url,
    ))
    return {"response_type": "ephemeral", "text": "Working..."}


@router.post("/bot/slack/interactions")
async def slack_interactions(
    request: Request,
    x_slack_request_timestamp: Optional[str] = Header(None, alias="X-Slack-Request-Timestamp"),
    x_slack_signature: Optional[str] = Header(None, alias="X-Slack-Signature"),
):
    body = await _verified_body(request, x_slack_request_timestamp, x_slack_signature)
    form = _parse_form(body)
    payload = json.loads(form.get("payload", "{}"))
    team_id = str((payload.get("team") or {}).get("id") or "")
    slack_user_id = str((payload.get("user") or {}).get("id") or "")
    response_url = payload.get("response_url", "")
    action_id = (((payload.get("actions") or [{}])[0]) or {}).get("action_id", "")

    user_id = _lookup_user_by_slack(team_id, slack_user_id)
    if not user_id:
        return {"response_type": "ephemeral", "text": "Your Slack is not linked. Use `/dreamagent link CODE` first."}

    asyncio.create_task(_handle_action_id(action_id, user_id, team_id, slack_user_id, response_url))
    return {"response_type": "ephemeral", "text": "Working..."}


@router.post("/bot/slack/events")
async def slack_events(
    request: Request,
    x_slack_request_timestamp: Optional[str] = Header(None, alias="X-Slack-Request-Timestamp"),
    x_slack_signature: Optional[str] = Header(None, alias="X-Slack-Signature"),
):
    body = await _verified_body(request, x_slack_request_timestamp, x_slack_signature)
    payload = json.loads(body.decode("utf-8") or "{}")
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    event = payload.get("event") or {}
    if payload.get("type") != "event_callback" or event.get("type") != "message":
        return {"ok": True}
    if event.get("subtype") or event.get("bot_id"):
        return {"ok": True}
    if event.get("channel_type") != "im":
        return {"ok": True}

    team_id = payload.get("team_id", "")
    slack_user_id = event.get("user", "")
    channel = event.get("channel", "")
    text = (event.get("text") or "").strip()
    if not team_id or not slack_user_id or not channel or not text:
        return {"ok": True}

    asyncio.create_task(_handle_dm_message(team_id, slack_user_id, channel, text))
    return {"ok": True}


async def _handle_dm_message(team_id: str, slack_user_id: str, channel: str, text: str) -> None:
    user_id = _lookup_user_by_slack(team_id, slack_user_id)
    if not user_id:
        await post_message(channel, "Your Slack is not linked. Use `/dreamagent link CODE` first.")
        return

    session_key = _session_key(team_id, slack_user_id)
    natural_action = _normalize_natural_action(text)
    if natural_action:
        await _run_slack_action(
            user_id=user_id,
            team_id=team_id,
            slack_user_id=slack_user_id,
            action=natural_action,
            message_text=text,
            channel=channel,
        )
        return

    selected = _get_selected_project_session(user_id, session_key)
    if selected:
        await _run_slack_action(
            user_id=user_id,
            team_id=team_id,
            slack_user_id=slack_user_id,
            action="chat",
            message_text=text,
            channel=channel,
        )
        return

    await _run_slack_action(
        user_id=user_id,
        team_id=team_id,
        slack_user_id=slack_user_id,
        action="project",
        message_text=text,
        channel=channel,
    )


def _verify_setup_secret(secret: Optional[str]) -> None:
    if SLACK_INTERACTIONS_SECRET and secret != SLACK_INTERACTIONS_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.post("/bot/slack/register-commands")
async def slack_setup_status(x_slack_setup_secret: Optional[str] = Header(None)):
    """Slack slash commands are configured in Slack's app console; this verifies backend config."""
    _verify_setup_secret(x_slack_setup_secret)
    return {
        "ok": is_configured(),
        "commands_url": "/bot/slack/commands",
        "interactions_url": "/bot/slack/interactions",
        "events_url": "/bot/slack/events",
    }
