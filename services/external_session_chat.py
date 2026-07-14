"""
Shared selected-session chat runner for external transports.

Web chat owns the canonical ACP streaming path. Telegram and Discord use this
module to run the same selected project session from a chat transport while
keeping billing, processing locks, message persistence, and auto-commit aligned.
"""

import json
import logging
from typing import Any, Dict, Optional

from database_postgres import get_db
from services.session_lock_service import SessionLockService

logger = logging.getLogger(__name__)


def load_session_context(session_id: int, limit: int = 10) -> str:
    """Load recent editor chat messages for ACP continuity."""
    try:
        with get_db() as conn:
            rows = conn.execute(
                """SELECT role, content, image FROM messages
                   WHERE session_id = %s
                   ORDER BY created_at DESC LIMIT %s""",
                (session_id, limit),
            ).fetchall()

        if not rows:
            return ""

        parts = []
        for row in reversed(rows):
            role = row["role"] if isinstance(row, dict) else row[0]
            content = row["content"] if isinstance(row, dict) else row[1]
            image = row.get("image") if isinstance(row, dict) else (row[2] if len(row) > 2 else None)
            if image:
                content = f"{content}\n\n[Image was attached in previous message]"
            parts.append(f"{str(role).upper()}: {content}")
        return "\n\n".join(parts)
    except Exception as e:
        logger.warning("[EXTERNAL-SESSION] Failed to load session context: %s", e, exc_info=True)
        return ""


def total_tokens_from_usage(usage_data: dict) -> int:
    return int(
        usage_data.get("total_tokens", 0)
        or usage_data.get("totalTokens", 0)
        or (usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0))
        or (usage_data.get("inputTokens", 0) + usage_data.get("outputTokens", 0))
        or 0
    )


def finalize_session_token_usage(
    *,
    handler,
    project_id: int,
    session_id: int,
    billing_user_id: Optional[int] = None,
    precharged_amount: int = 0,
    channel_label: str = "External",
) -> Optional[str]:
    """Persist token analytics and apply the same post-edit billing used by web sessions."""
    if not handler or not hasattr(handler, "get_last_token_usage"):
        return None

    usage_data = handler.get_last_token_usage()
    if not usage_data:
        return None

    token_usage_json = json.dumps(usage_data)
    try:
        from services.token_tracker import record_from_token_usage_json
        from services.billing_service import charge_token_usage

        with get_db() as tconn:
            owner_user_id = billing_user_id
            if not owner_user_id:
                prow = tconn.execute(
                    "SELECT user_id FROM projects WHERE id = %s",
                    (project_id,),
                ).fetchone()
                if not prow:
                    logger.warning("[%s-SESSION] Token billing skipped: project %s owner not found", channel_label.upper(), project_id)
                    return token_usage_json
                owner_user_id = prow["user_id"] if isinstance(prow, dict) else prow[0]

            total_tokens = total_tokens_from_usage(usage_data)
            if precharged_amount:
                usage_data["operation"] = "ADD_FEATURE"
                usage_data["credits_charged"] = precharged_amount + max(0, total_tokens - precharged_amount)

            record_from_token_usage_json(
                user_id=owner_user_id,
                token_usage_json=usage_data,
                usage_type="ai_chat",
                project_id=project_id,
                session_id=session_id,
                description=f"{channel_label} project session chat",
            )

            if total_tokens > 0:
                cache_read_tokens = int(usage_data.get("cache_read_input_tokens", 0) or 0)
                charge_result = charge_token_usage(
                    conn=tconn,
                    user_id=owner_user_id,
                    total_tokens=total_tokens,
                    operation_code="ADD_FEATURE",
                    project_id=project_id,
                    session_id=session_id,
                    model=usage_data.get("model"),
                    precharged_amount=precharged_amount,
                    cache_read_tokens=cache_read_tokens,
                )
                tconn.commit()
                logger.info("[%s-SESSION] Post-edit token charge: %s", channel_label.upper(), charge_result)
    except Exception as e:
        logger.warning("[%s-SESSION] Token tracking/billing failed: %s", channel_label.upper(), e, exc_info=True)

    return token_usage_json


def reserve_session_chat_credits(project_id: int, channel_label: str = "External") -> dict:
    """Reserve the same upfront ADD_FEATURE credit hold used by web ACP streaming."""
    try:
        from services.billing_service import reserve_credits

        with get_db() as conn:
            prow = conn.execute(
                "SELECT user_id FROM projects WHERE id = %s",
                (project_id,),
            ).fetchone()
            if not prow:
                return {"success": True, "user_id": None, "charged": []}

            owner_user_id = prow["user_id"] if isinstance(prow, dict) else prow[0]
            result = reserve_credits(conn, owner_user_id, "ADD_FEATURE", amount=1)
            conn.commit()

        if not result.get("success"):
            return {
                "success": False,
                "user_id": owner_user_id,
                "charged": [],
                "error": result.get("error", "insufficient_credits"),
                "cost": result.get("cost"),
                "available": result.get("total_available", 0),
            }

        charged = result.get("charged", [])
        logger.info("[%s-SESSION] Reserved chat credits for user %s: %s", channel_label.upper(), owner_user_id, charged)
        return {"success": True, "user_id": owner_user_id, "charged": charged}
    except Exception as e:
        logger.warning("[%s-SESSION] Credit reservation failed; allowing request: %s", channel_label.upper(), e)
        return {"success": True, "user_id": None, "charged": []}


def refund_session_chat_credits(user_id: Optional[int], charged: list, channel_label: str = "External") -> None:
    if not user_id or not charged:
        return
    try:
        from services.billing_service import refund_credits

        with get_db() as conn:
            refund_credits(conn, user_id, "ADD_FEATURE", charged)
            conn.commit()
        logger.info("[%s-SESSION] Refunded reserved chat credits for user %s", channel_label.upper(), user_id)
    except Exception as e:
        logger.warning("[%s-SESSION] Reserved credit refund failed: %s", channel_label.upper(), e)


async def auto_commit_selected_session_change(project_id: int, session_id: int, handler, channel_label: str = "External") -> None:
    """Reuse the web session auto-commit path for external session edits."""
    if not handler:
        return
    try:
        from app import _auto_commit_and_push

        await _auto_commit_and_push(project_id, session_id, handler, "dream")
    except Exception as e:
        logger.warning("[%s-SESSION] Auto-commit check failed: %s", channel_label.upper(), e)


async def run_handler_like_web_session(handler, user_message: str, session_context: str) -> str:
    """
    Run ACP chat through the same streaming entrypoint used by web sessions.

    External chat transports cannot stream chunks into the editor UI, but
    collecting chunks from run_chat_streaming_unified keeps the important web
    behavior: Claude session resume keyed by project/session, streaming prompt
    routing, and full-response extraction from handler._last_query_response.
    """
    chunks = []
    async for chunk in handler.run_chat_streaming_unified(user_message, session_context):
        if chunk:
            chunks.append(str(chunk))

    final_response = getattr(handler, "_last_query_response", None)
    if final_response:
        return str(final_response).strip()

    real_chunks = []
    for chunk in chunks:
        text = str(chunk).strip()
        if not text or text.startswith("PROGRESS:"):
            continue
        if text.startswith("TEXT:"):
            text = text[5:].strip()
        if text:
            real_chunks.append(text)

    return "\n".join(real_chunks).strip()


async def run_selected_session_chat(
    *,
    user_id: int,
    selected_session: Dict[str, Any],
    text: str,
    channel: str,
    processing_already_acquired: bool = False,
) -> Dict[str, Any]:
    """Run selected project-session chat and return a transport-neutral result."""
    session_id = int(selected_session["id"])
    project_id = int(selected_session["project_id"])
    session_key = selected_session["session_key"]
    session_label = selected_session.get("label") or f"session #{session_id}"
    channel_label = (channel or "external").strip().title()
    handler = None
    billing_user_id = None
    reserved_charges = []
    assistant_saved = False
    processing_acquired = processing_already_acquired

    try:
        if not processing_acquired:
            processing_result = SessionLockService.acquire_processing(session_id, channel)
            if not processing_result.get("success"):
                return {
                    "status": "busy",
                    "message": (
                        f"Still working on the previous message in {session_label}. "
                        "Please wait for it to finish before sending another one. "
                        f"Current channel: {processing_result.get('processing_channel') or 'another client'}."
                    ),
                    "result": processing_result,
                }
            processing_acquired = True

        lock_result = SessionLockService.acquire_lock(project_id, session_id)
        if not lock_result.get("success"):
            from utils.devops_session_context import get_devops_session_context

            lock_owner = get_devops_session_context().format_lock_owner(lock_result)
            return {
                "status": "locked",
                "message": (
                    f"This project is currently active in {lock_owner}. "
                    "Complete/release that session first. If it is open in web chat, finish it there first."
                ),
                "result": lock_result,
            }

        reserve_result = reserve_session_chat_credits(project_id, channel_label)
        billing_user_id = reserve_result.get("user_id")
        reserved_charges = reserve_result.get("charged", [])
        if not reserve_result.get("success"):
            SessionLockService.release_lock(project_id, session_id)
            return {
                "status": "insufficient_credits",
                "message": (
                    "You don't have enough AI credits for this request. "
                    f"Required: {reserve_result.get('cost')}, available: {reserve_result.get('available', 0)}."
                ),
                "result": reserve_result,
            }

        with get_db() as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, mode) VALUES (%s, %s, %s, %s)",
                (session_id, "user", text, "dream"),
            )
            conn.commit()

        from acp_chat_handler import get_acp_chat_handler

        handler = get_acp_chat_handler(session_key)
        if not handler:
            assistant_content = "Error: Could not initialize the project session chat handler."
        else:
            handler.set_session_id(session_id)
            session_context = load_session_context(session_id)
            logger.info(
                "[%s-SESSION] Routing chat to selected session id=%s label=%s project_id=%s user=%s via web streaming handler",
                channel_label.upper(),
                session_id,
                session_label,
                project_id,
                user_id,
            )
            assistant_content = await run_handler_like_web_session(handler, text, session_context)
            if not assistant_content:
                assistant_content = "Session chat completed, but no response text was returned."

        token_usage_json = finalize_session_token_usage(
            handler=handler,
            project_id=project_id,
            session_id=session_id,
            billing_user_id=billing_user_id,
            precharged_amount=sum(abs(c.get("amount", 0)) for c in reserved_charges),
            channel_label=channel_label,
        )

        with get_db() as conn:
            if token_usage_json:
                conn.execute(
                    "INSERT INTO messages (session_id, role, content, token_usage) VALUES (%s, %s, %s, %s)",
                    (session_id, "assistant", assistant_content, token_usage_json),
                )
            else:
                conn.execute(
                    "INSERT INTO messages (session_id, role, content) VALUES (%s, %s, %s)",
                    (session_id, "assistant", assistant_content),
                )
            conn.execute("UPDATE sessions SET last_used_at = CURRENT_TIMESTAMP WHERE id = %s", (session_id,))
            conn.commit()
        assistant_saved = True
        await auto_commit_selected_session_change(project_id, session_id, handler, channel_label)

        return {
            "status": "success",
            "message": assistant_content,
            "result": {
                "project_id": project_id,
                "session_id": session_id,
                "token_usage_json": token_usage_json,
            },
        }

    except Exception as e:
        logger.error("[%s-SESSION] Selected session chat failed: %s", channel_label.upper(), e, exc_info=True)
        if not assistant_saved:
            refund_session_chat_credits(billing_user_id, reserved_charges, channel_label)
        return {"status": "error", "message": f"Session chat failed: {str(e)}"}
    finally:
        if handler:
            try:
                handler.kill_orphan_processes()
            except Exception as cleanup_error:
                logger.warning("[%s-SESSION] Cleanup failed: %s", channel_label.upper(), cleanup_error)
        if processing_acquired:
            SessionLockService.release_processing(session_id)


def truncate_for_transport(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 18)] + "\n\n... (truncated)"
