"""
Discord Interactions handler for the DreamAgent control bot.

This controls DreamAgent projects from Discord. It is unrelated to generated
Discord bot projects under services.discord.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request
try:
    from nacl.signing import VerifyKey
    from nacl.exceptions import BadSignatureError
except Exception:  # pragma: no cover - deployment config issue
    VerifyKey = None
    BadSignatureError = None

from api.ai_chat import process_message
from database_postgres import get_db
from services.discord_client import (
    DISCORD_INTERACTIONS_SECRET,
    DISCORD_PUBLIC_KEY,
    delete_commands,
    edit_original_response,
    is_configured,
    register_commands,
    truncate_content,
)
from services.external_session_chat import run_selected_session_chat
from services.session_lock_service import SessionLockService

logger = logging.getLogger(__name__)
router = APIRouter()


INTERACTION_PING = 1
INTERACTION_APPLICATION_COMMAND = 2
INTERACTION_MESSAGE_COMPONENT = 3
RESPONSE_PONG = 1
RESPONSE_CHANNEL_MESSAGE = 4
RESPONSE_DEFERRED_CHANNEL_MESSAGE = 5

EPHEMERAL_FLAG = 64


def _verify_signature(body: bytes, timestamp: Optional[str], signature: Optional[str]) -> bool:
    public_key_len = len(DISCORD_PUBLIC_KEY or "")
    logger.info(
        "[DISCORD-CONTROL] Verifying interaction signature body_bytes=%s public_key_configured=%s public_key_len=%s timestamp_present=%s signature_present=%s signature_len=%s",
        len(body or b""),
        bool(DISCORD_PUBLIC_KEY),
        public_key_len,
        bool(timestamp),
        bool(signature),
        len(signature or ""),
    )
    if not DISCORD_PUBLIC_KEY:
        logger.error("[DISCORD-CONTROL] DISCORD_PUBLIC_KEY not configured")
        return False
    if not timestamp or not signature:
        logger.warning(
            "[DISCORD-CONTROL] Missing Discord signature headers timestamp_present=%s signature_present=%s",
            bool(timestamp),
            bool(signature),
        )
        return False
    try:
        if VerifyKey is None:
            logger.error("[DISCORD-CONTROL] PyNaCl is not installed or could not be imported")
            return False

        verify_key = VerifyKey(bytes.fromhex(DISCORD_PUBLIC_KEY))
        verify_key.verify(timestamp.encode("utf-8") + body, bytes.fromhex(signature))
        logger.info("[DISCORD-CONTROL] Signature verified successfully")
        return True
    except Exception as e:
        if BadSignatureError is not None and isinstance(e, BadSignatureError):
            logger.warning(
                "[DISCORD-CONTROL] Bad Discord signature public_key_len=%s timestamp_len=%s signature_len=%s body_bytes=%s",
                public_key_len,
                len(timestamp or ""),
                len(signature or ""),
                len(body or b""),
            )
            return False
        logger.error("[DISCORD-CONTROL] Signature verification error: %s", e, exc_info=True)
        return False


def _interaction_response(content: str, components: Optional[list] = None, ephemeral: bool = True) -> dict:
    data: dict[str, Any] = {"content": truncate_content(content)}
    if ephemeral:
        data["flags"] = EPHEMERAL_FLAG
    if components is not None:
        data["components"] = components
    return {"type": RESPONSE_CHANNEL_MESSAGE, "data": data}


def _deferred_response(ephemeral: bool = True) -> dict:
    data = {"flags": EPHEMERAL_FLAG} if ephemeral else {}
    return {"type": RESPONSE_DEFERRED_CHANNEL_MESSAGE, "data": data}


def _button(label: str, custom_id: str, style: int = 2) -> dict:
    return {"type": 2, "style": style, "label": label[:80], "custom_id": custom_id[:100]}


def _components(rows: list[list[tuple[str, str, int]]]) -> list:
    return [
        {"type": 1, "components": [_button(label, custom_id, style) for label, custom_id, style in row[:5]]}
        for row in rows[:5]
        if row
    ]


def _action_components(kind: str = "project") -> list:
    if kind == "session":
        rows = [
            [("Current", "action:current", 2), ("Sessions", "action:sessions", 2)],
            [("Complete", "action:complete", 3), ("Clear Session", "action:clearsession", 2)],
            [("Status", "action:status", 2), ("Logs", "action:logs", 2)],
            [("Billing", "action:billing", 2), ("Help", "action:help", 2)],
        ]
    elif kind == "busy":
        rows = [
            [("Current", "action:current", 2), ("Sessions", "action:sessions", 2)],
            [("Complete", "action:complete", 3), ("Clear Session", "action:clearsession", 2)],
            [("Billing", "action:billing", 2)],
        ]
    else:
        rows = [
            [("Current", "action:current", 2), ("Sessions", "action:sessions", 2)],
            [("Status", "action:status", 2), ("Logs", "action:logs", 2)],
            [("Restart", "action:restart", 2), ("Billing", "action:billing", 2)],
            [("Help", "action:help", 2)],
        ]
    return _components(rows)


def _components_from_response(resp: dict) -> Optional[list]:
    if resp.get("type") != "selection":
        return None

    options = resp.get("options") or []
    if not options:
        return None

    intent = resp.get("intent", {}) or {}
    tool_name = intent.get("tool")
    intent_args = intent.get("args", {}) or {}
    rows: list[list[tuple[str, str, int]]] = []
    for opt in options[:25]:
        if tool_name == "set_active_project_session":
            project_domain = intent_args.get("project_domain", "")
            custom_id = f"session:set:{project_domain}:{opt['value']}" if project_domain else f"session:set:{opt['value']}"
        else:
            custom_id = f"switch:{opt['value']}"
        rows.append([(str(opt["label"])[:80], custom_id, 1)])
    return _components(rows)


def _format_for_discord(resp: dict) -> str:
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


def _extract_discord_user_id(interaction: dict) -> Optional[str]:
    user = (interaction.get("member") or {}).get("user") or interaction.get("user") or {}
    value = user.get("id")
    return str(value) if value else None


def _option_value(data: dict, name: str) -> Optional[str]:
    for opt in data.get("options") or []:
        if opt.get("name") == name:
            value = opt.get("value")
            return str(value) if value is not None else None
    return None


def _lookup_user_by_discord_id(discord_user_id: str) -> Optional[int]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE discord_user_id = %s",
            (discord_user_id,),
        ).fetchone()
    return row["id"] if row else None


def _try_link_code(discord_user_id: str, code: str) -> tuple[bool, str]:
    code = code.upper().strip()
    with get_db() as conn:
        row = conn.execute(
            """SELECT id, discord_link_expires_at, telegram_link_expires_at
               FROM users
               WHERE discord_link_code = %s OR telegram_link_code = %s""",
            (code, code),
        ).fetchone()
        if not row:
            return False, f"Invalid code `{code}`. Please check and try again."

        expires_at = row.get("discord_link_expires_at") or row.get("telegram_link_expires_at")
        if expires_at and datetime.utcnow() > expires_at:
            return False, "This code has expired. Please generate a new one in DreamAgent."

        existing = conn.execute(
            "SELECT id FROM users WHERE discord_user_id = %s AND id != %s",
            (discord_user_id, row["id"]),
        ).fetchone()
        if existing:
            return False, "This Discord account is already linked to another DreamAgent account."

        conn.execute(
            """UPDATE users
               SET discord_user_id = %s,
                   discord_link_code = NULL,
                   discord_link_expires_at = NULL
               WHERE id = %s""",
            (discord_user_id, row["id"]),
        )
        conn.commit()

    logger.info("[DISCORD-CONTROL] Linked discord_user_id=%s to user_id=%s", discord_user_id, row["id"])
    return True, "Account linked successfully. Use `/switch` to choose a project."


def _unlink_discord(discord_user_id: str) -> str:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE discord_user_id = %s",
            (discord_user_id,),
        ).fetchone()
        if not row:
            return "This Discord account is not linked."

        conn.execute(
            """UPDATE users
               SET discord_user_id = NULL,
                   discord_link_code = NULL,
                   discord_link_expires_at = NULL
               WHERE discord_user_id = %s""",
            (discord_user_id,),
        )
        conn.commit()
    return "Discord account unlinked."


def _format_int(value: Any) -> str:
    try:
        return f"{int(value or 0):,}"
    except Exception:
        return str(value or 0)


def _format_money_cents(value: Any) -> str:
    try:
        cents = int(value or 0)
        return "$0/mo" if cents == 0 else f"${cents / 100:.0f}/mo"
    except Exception:
        return "$0/mo"


def _credit_label(credit_type: str) -> str:
    labels = {"project_ai": "AI credits", "edit_token": "Edit tokens"}
    return labels.get((credit_type or "").lower(), (credit_type or "Credits").replace("_", " ").title())


def _format_billing_summary(user_id: int) -> str:
    from services.bot_billing_formatter import format_billing_summary

    with get_db() as conn:
        return format_billing_summary(conn, user_id, bold_marker="**")


def _help_text() -> str:
    return (
        "**DreamAgent Discord Bot**\n\n"
        "Workflow:\n"
        "1. `/link code:YOURCODE` - link your DreamAgent account\n"
        "2. `/switch` - choose a project\n"
        "3. `/sessions` or `/newsession label:Fix navbar` - choose work\n"
        "4. `/project message:make the hero more premium` - continue the selected session\n"
        "5. `/complete` - finish and release the session\n\n"
        "Project controls: `/current` `/status` `/logs` `/billing` `/restart` `/start` `/stop`\n"
        "Note: normal Discord server messages do not reach DreamAgent. Use `/project message:...` or `/chat message:...`."
    )


def _normalize_action(command: str, data: Optional[dict] = None) -> tuple[str, str]:
    data = data or {}
    command = (command or "").lower().strip()
    if command == "switch":
        project = _option_value(data, "project")
        return "switch", f"/switch {project}" if project else "/switch"
    if command == "newsession":
        label = _option_value(data, "label") or "Discord session"
        return "newsession", f"/newsession {label}"
    if command in {"chat", "project"}:
        return "chat", _option_value(data, "message") or ""
    return command, f"/{command}"


async def _run_discord_action(
    *,
    interaction_token: str,
    user_id: int,
    discord_user_id: str,
    action: str,
    message_text: str,
) -> None:
    session_key = f"dc_{discord_user_id}"

    if action == "help":
        await edit_original_response(interaction_token, _help_text(), _action_components())
        return

    if action == "billing":
        await edit_original_response(interaction_token, _format_billing_summary(user_id), _action_components())
        return

    if action == "clearsession":
        from utils.devops_session_context import get_devops_session_context

        get_devops_session_context().clear_context(user_id, session_key)
        await edit_original_response(interaction_token, "Cleared the selected session. Project selection is unchanged.", _action_components())
        return

    if action == "chat":
        selected = _get_selected_project_session(user_id, session_key)
        if not selected:
            await edit_original_response(
                interaction_token,
                "No active session selected. Use `/sessions` or `/newsession` first.",
                _action_components(),
            )
            return

        result = await run_selected_session_chat(
            user_id=user_id,
            selected_session=selected,
            text=message_text,
            channel="discord",
        )
        kind = "busy" if result.get("status") == "busy" else "session"
        await edit_original_response(interaction_token, result.get("message") or "Session chat completed.", _action_components(kind))
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
        raw = message_text.split(maxsplit=1)
        mapped_message = f"new session {raw[1].strip()}" if len(raw) == 2 else "new session Discord session"
    else:
        mapped_message = mapped.get(action)

    if not mapped_message:
        await edit_original_response(interaction_token, "I don't recognize that action yet.", _action_components())
        return

    resp = await process_message(
        user_id=user_id,
        message=mapped_message,
        session_id=session_key,
        source="discord",
    )
    components = _components_from_response(resp) or (_session_action_components_if_needed(action))
    await edit_original_response(interaction_token, _format_for_discord(resp), components)


def _session_action_components_if_needed(action: str) -> list:
    return _action_components("session" if action in {"current", "sessions", "complete"} else "project")


def _get_selected_project_session(user_id: int, discord_session_key: str) -> Optional[dict]:
    try:
        from utils.devops_session_context import get_devops_session_context

        context = get_devops_session_context()
        session_id = context.get_user_active_session_id(user_id)
        if not session_id:
            session_id = context.get_ai_active_session_id(discord_session_key)
        if not session_id:
            return None
        session = context.get_session(user_id, int(session_id))
        if not session:
            context.clear_context(user_id, discord_session_key)
            return None
        return session
    except Exception as e:
        logger.warning("[DISCORD-SESSION] Failed to resolve selected session: %s", e, exc_info=True)
        return None


async def _handle_component(interaction: dict) -> None:
    token = interaction.get("token", "")
    data = interaction.get("data") or {}
    custom_id = data.get("custom_id", "")
    discord_user_id = _extract_discord_user_id(interaction)
    if not discord_user_id:
        await edit_original_response(token, "Could not identify your Discord user.")
        return

    user_id = _lookup_user_by_discord_id(discord_user_id)
    if not user_id:
        await edit_original_response(token, "Your Discord is not linked. Use `/link code:YOURCODE` first.")
        return

    session_key = f"dc_{discord_user_id}"
    if custom_id.startswith("action:"):
        action = custom_id[len("action:"):]
        await _run_discord_action(
            interaction_token=token,
            user_id=user_id,
            discord_user_id=discord_user_id,
            action=action,
            message_text=f"/{action}",
        )
        return

    if custom_id.startswith("switch:"):
        project_domain = custom_id[len("switch:"):]
        resp = await process_message(
            user_id=user_id,
            message=f"switch to {project_domain}",
            session_id=session_key,
            source="discord",
        )
        await edit_original_response(token, _format_for_discord(resp), _components_from_response(resp) or _action_components())
        return

    if custom_id.startswith("session:set:"):
        raw_payload = custom_id[len("session:set:"):]
        parts = raw_payload.rsplit(":", 1)
        if len(parts) == 2:
            project_domain, raw_session_id = parts
            await process_message(
                user_id=user_id,
                message=f"switch to {project_domain}",
                session_id=session_key,
                source="discord",
            )
        else:
            raw_session_id = raw_payload

        resp = await process_message(
            user_id=user_id,
            message=f"select session {raw_session_id}",
            session_id=session_key,
            source="discord",
        )
        await edit_original_response(token, _format_for_discord(resp), _components_from_response(resp) or _action_components("session"))
        return

    await edit_original_response(token, "Unknown button action.", _action_components())


async def _handle_command(interaction: dict) -> None:
    token = interaction.get("token", "")
    data = interaction.get("data") or {}
    command, message_text = _normalize_action(data.get("name", ""), data)
    discord_user_id = _extract_discord_user_id(interaction)
    if not discord_user_id:
        await edit_original_response(token, "Could not identify your Discord user.")
        return

    if command == "link":
        ok, msg = _try_link_code(discord_user_id, _option_value(data, "code") or "")
        await edit_original_response(token, msg, _action_components() if ok else None)
        return

    if command == "unlink":
        await edit_original_response(token, _unlink_discord(discord_user_id))
        return

    user_id = _lookup_user_by_discord_id(discord_user_id)
    if not user_id:
        await edit_original_response(token, "Your Discord is not linked. Use `/link code:YOURCODE` first.")
        return

    await _run_discord_action(
        interaction_token=token,
        user_id=user_id,
        discord_user_id=discord_user_id,
        action=command,
        message_text=message_text,
    )


@router.post("/bot/discord/interactions")
async def discord_interactions(
    request: Request,
    x_signature_ed25519: Optional[str] = Header(None, alias="X-Signature-Ed25519"),
    x_signature_timestamp: Optional[str] = Header(None, alias="X-Signature-Timestamp"),
):
    """Receive Discord Interactions. Verified by Discord Ed25519 signature."""
    body = await request.body()
    logger.info(
        "[DISCORD-CONTROL] Interaction request received method=%s path=%s content_type=%s body_bytes=%s",
        request.method,
        request.url.path,
        request.headers.get("content-type"),
        len(body or b""),
    )
    if not _verify_signature(body, x_signature_timestamp, x_signature_ed25519):
        logger.warning("[DISCORD-CONTROL] Interaction rejected: invalid signature")
        raise HTTPException(status_code=401, detail="invalid request signature")

    interaction = await request.json()
    interaction_type = interaction.get("type")
    logger.info(
        "[DISCORD-CONTROL] Interaction accepted type=%s command=%s custom_id=%s user_id_present=%s",
        interaction_type,
        (interaction.get("data") or {}).get("name"),
        (interaction.get("data") or {}).get("custom_id"),
        bool(_extract_discord_user_id(interaction)),
    )
    if interaction_type == INTERACTION_PING:
        logger.info("[DISCORD-CONTROL] Responding to Discord PING verification")
        return {"type": RESPONSE_PONG}

    if interaction_type == INTERACTION_APPLICATION_COMMAND:
        data = interaction.get("data") or {}
        command = data.get("name", "")
        discord_user_id = _extract_discord_user_id(interaction)

        if command == "help":
            return _interaction_response(_help_text(), _action_components(), ephemeral=True)

        if not discord_user_id:
            return _interaction_response("Could not identify your Discord user.", ephemeral=True)

        if command == "link":
            ok, msg = _try_link_code(discord_user_id, _option_value(data, "code") or "")
            return _interaction_response(msg, _action_components() if ok else None, ephemeral=True)

        if command == "unlink":
            return _interaction_response(_unlink_discord(discord_user_id), ephemeral=True)

        ephemeral = command not in {"status", "logs", "start", "stop", "restart"}
        asyncio.create_task(_handle_command(interaction))
        return _deferred_response(ephemeral=ephemeral)

    if interaction_type == INTERACTION_MESSAGE_COMPONENT:
        asyncio.create_task(_handle_component(interaction))
        return _deferred_response(ephemeral=True)

    return _interaction_response("Unsupported Discord interaction type.")


def _verify_setup_secret(secret: Optional[str]) -> None:
    if DISCORD_INTERACTIONS_SECRET and secret != DISCORD_INTERACTIONS_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.post("/bot/discord/register-commands")
async def setup_discord_commands(x_discord_setup_secret: Optional[str] = Header(None)):
    """Register Discord slash commands."""
    _verify_setup_secret(x_discord_setup_secret)
    if not is_configured():
        return {"ok": False, "error": "Discord control bot is not fully configured"}
    return await register_commands()


@router.delete("/bot/discord/commands")
async def remove_discord_commands(x_discord_setup_secret: Optional[str] = Header(None)):
    """Delete Discord slash commands by replacing the command set with an empty list."""
    _verify_setup_secret(x_discord_setup_secret)
    return await delete_commands()
