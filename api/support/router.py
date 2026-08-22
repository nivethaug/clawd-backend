#!/usr/bin/env python3
"""
Support Chat Router — USER endpoints for the live support system.

Mounted at: /api/support (prefix added in app.py).

Auth: Bearer token on every endpoint. Ownership is enforced by filtering
on the server-resolved user_id from the token — a client-supplied user id
is never read anywhere in this module.

Real-time design: the user's message POST responds as an SSE stream
(existing AI-chat protocol: `data: {...}\\n\\n`, terminated by
`data: [DONE]\\n\\n`). Later admin replies reach the panel via 5s polling
on GET messages?after=<last_id>.

ISOLATION: new tables (support_*) only; lazy `from app import ...` for
require_admin; nothing existing is modified beyond the router mount.
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from utils.auth_helpers import get_user_id_from_token
from services.support import ai_responder, conversation_service
from services.support.project_context import build_project_context
from api.support.schemas import (
    OpenConversationRequest,
    SendMessageRequest,
)

logger = logging.getLogger("api.support")

router = APIRouter()

MAX_MESSAGE_CHARS = 4000


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _own_conversation(conversation_id: int, user_id: int) -> dict:
    conv = conversation_service.get_conversation(conversation_id, user_id=user_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


# ======================================================================
# Conversations
# ======================================================================

@router.get("/conversations")
async def list_conversations(authorization: Optional[str] = Header(None)):
    user_id = get_user_id_from_token(authorization)
    rows = conversation_service.list_user_conversations(user_id)
    return {"conversations": rows}


@router.post("/conversations")
async def open_conversation(
    request: OpenConversationRequest,
    authorization: Optional[str] = Header(None),
):
    """Open (or reuse) the user's active support conversation."""
    user_id = get_user_id_from_token(authorization)

    project_ctx = None
    if request.project_id is not None:
        project_ctx = build_project_context(request.project_id, owner_user_id=user_id)
        if not project_ctx:
            raise HTTPException(status_code=404, detail="Project not found")

    conv = conversation_service.open_conversation(
        user_id, project_id=request.project_id, category=request.category
    )
    return {"conversation": conv}


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: int, authorization: Optional[str] = Header(None)):
    user_id = get_user_id_from_token(authorization)
    conv = _own_conversation(conversation_id, user_id)
    conv.pop("assigned_admin_id", None)  # internal detail — not for users
    return {"conversation": conv}


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: int,
    after: int = 0,
    authorization: Optional[str] = Header(None),
):
    """Incremental message sync (reconnect-safe: id > after)."""
    user_id = get_user_id_from_token(authorization)
    _own_conversation(conversation_id, user_id)
    rows = conversation_service.get_messages(conversation_id, after_id=after)
    return {"messages": rows}


# ======================================================================
# Messaging (user → SSE stream with AI reply)
# ======================================================================

@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: int,
    request: SendMessageRequest,
    authorization: Optional[str] = Header(None),
):
    """Persist the user's message, then stream the assistant's reply as SSE.

    While responder_mode='admin' (escalated/active) the AI stays paused —
    the stream simply confirms the persisted message so the admin's next
    reply arrives via polling.
    """
    user_id = get_user_id_from_token(authorization)
    conv = _own_conversation(conversation_id, user_id)

    text = (request.message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message is required")
    if len(text) > MAX_MESSAGE_CHARS:
        raise HTTPException(status_code=400, detail=f"Message too long (max {MAX_MESSAGE_CHARS} chars)")

    # Rate-limit sends on the existing general_api limiter.
    try:
        from services.rate_limiter import rate_limit, RateLimitExceeded
        rate_limit(user_id, "general_api")
    except RateLimitExceeded as e:
        raise HTTPException(status_code=429, detail="Too many messages — please slow down.")
    except Exception:
        pass  # limiter unavailable must not take support chat down

    # Resolved conversation + user reply → reopen to AI.
    if conv.get("status") == "resolved":
        conversation_service.reopen(conversation_id, by_admin=False)

    user_msg = conversation_service.add_message(conversation_id, "user", user_id, text)

    project_ctx = None
    if conv.get("project_id"):
        project_ctx = build_project_context(conv["project_id"], owner_user_id=user_id)

    async def event_stream():
        try:
            yield _sse({"type": "message", "message": user_msg})

            history = conversation_service.get_messages(conversation_id, limit=500)

            if conv.get("responder_mode") == "admin":
                # Human owns this conversation — no AI reply.
                yield _sse({"type": "done", "responder": "admin"})
                yield "data: [DONE]\n\n"
                return

            if not ai_responder.ai_available():
                # Graceful degrade: straight to human support.
                conversation_service.escalate_to_admin(
                    conversation_id, reason="AI assistant unavailable"
                )
                yield _sse({"type": "escalate",
                            "text": "The AI assistant is unavailable right now — "
                                    "connecting you with DreamAgent Support."})
                yield _sse({"type": "done", "responder": "admin"})
                yield "data: [DONE]\n\n"
                return

            assembled: list = []
            escalate_reason = None
            async for ev in ai_responder.stream_reply(conv, history, project_ctx):
                if ev["type"] == "token":
                    assembled.append(ev["text"])
                    yield _sse(ev)
                elif ev["type"] == "escalate":
                    escalate_reason = ev.get("reason", "assistant decision")
                    yield _sse({"type": "token", "text": ev.get("text", "")})
                    assembled.append(ev.get("text", ""))
                elif ev["type"] == "error":
                    yield _sse(ev)
                    yield "data: [DONE]\n\n"
                    return

            reply_text = "".join(assembled).strip()

            # Model-signalled escalation ([ESCALATE] prefix)?
            if ai_responder.check_model_escalation(reply_text):
                escalate_reason = escalate_reason or "assistant decision"
                reply_text = ai_responder.strip_escalation_tag(reply_text).strip()
                if not reply_text:
                    reply_text = ("I'm not able to resolve this reliably from here — "
                                  "connecting you with DreamAgent Support.")

            if reply_text:
                assistant_msg = conversation_service.add_message(
                    conversation_id, "assistant", None, reply_text
                )
                yield _sse({"type": "message", "message": assistant_msg})

            if escalate_reason:
                conversation_service.escalate_to_admin(conversation_id, reason=escalate_reason)
                yield _sse({"type": "escalated"})
                yield _sse({"type": "done", "responder": "admin"})
            else:
                # First exchange: open → ai_handling + auto-summary.
                from database_adapter import get_db
                with get_db() as conn:
                    conn.execute(
                        "UPDATE support_conversations SET status = 'ai_handling' "
                        "WHERE id = ? AND status = 'open'",
                        (conversation_id,),
                    )
                    conn.commit()
                if not conversation_service.get_conversation(conversation_id).get("summary"):
                    conversation_service.set_summary(conversation_id, text[:120])
                yield _sse({"type": "done", "responder": "ai"})

            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error("[SUPPORT] stream error conv=%s: %s", conversation_id, e, exc_info=True)
            yield _sse({"type": "error", "detail": "Something went wrong — please retry."})
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ======================================================================
# Typing + read state
# ======================================================================

@router.post("/conversations/{conversation_id}/typing")
async def typing(conversation_id: int, authorization: Optional[str] = Header(None)):
    user_id = get_user_id_from_token(authorization)
    _own_conversation(conversation_id, user_id)
    conversation_service.bump_typing(conversation_id, "user")
    return {"success": True}


@router.post("/conversations/{conversation_id}/read")
async def mark_read(conversation_id: int, authorization: Optional[str] = Header(None)):
    user_id = get_user_id_from_token(authorization)
    _own_conversation(conversation_id, user_id)
    n = conversation_service.mark_read(conversation_id, reader="user")
    return {"success": True, "marked": n}
