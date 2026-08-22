#!/usr/bin/env python3
"""
Support Admin Router — admin-only endpoints for the Support Inbox.

Mounted at: /api/support/admin (prefix added in app.py).

Auth: `_require_admin` on EVERY route (spec §12) — resolves the admin from
the token (never client-supplied), 403s non-admins. Admin actions are
audit-logged with `[SUPPORT]` lines.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from utils.auth_helpers import get_user_id_from_token
from services.support import conversation_service
from api.support.schemas import (
    AdminNoteRequest,
    AdminReplyRequest,
    AssignRequest,
    HandBackRequest,
    PriorityRequest,
)

logger = logging.getLogger("api.support.admin")

router = APIRouter()

MAX_MESSAGE_CHARS = 4000


def _require_admin(authorization: Optional[str]) -> int:
    """Resolve admin id from the token and enforce the admin role."""
    user_id = get_user_id_from_token(authorization)
    from app import require_admin  # lazy — avoid circular import
    require_admin(user_id)
    return user_id


def _conv(conversation_id: int) -> dict:
    conv = conversation_service.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


# ======================================================================
# Inbox
# ======================================================================

@router.get("/inbox")
async def inbox(
    status: Optional[str] = None,
    page: int = 0,
    authorization: Optional[str] = Header(None),
):
    _require_admin(authorization)
    rows = conversation_service.admin_inbox(status=status, page=max(0, page))
    return {"conversations": rows}


@router.get("/unread-count")
async def unread_count(authorization: Optional[str] = Header(None)):
    _require_admin(authorization)
    return {"count": conversation_service.admin_unread_count()}


# ======================================================================
# Conversation detail + messaging
# ======================================================================

@router.get("/conversations/{conversation_id}")
async def conversation_detail(conversation_id: int, authorization: Optional[str] = Header(None)):
    _require_admin(authorization)
    conv = _conv(conversation_id)
    return {
        "conversation": conv,
        "notes": conversation_service.admin_list_notes(conversation_id),
    }


@router.get("/conversations/{conversation_id}/messages")
async def messages(
    conversation_id: int,
    after: int = 0,
    authorization: Optional[str] = Header(None),
):
    _require_admin(authorization)
    _conv(conversation_id)
    rows = conversation_service.get_messages(conversation_id, after_id=after)
    return {"messages": rows}


@router.post("/conversations/{conversation_id}/reply")
async def reply(
    conversation_id: int,
    request: AdminReplyRequest,
    authorization: Optional[str] = Header(None),
):
    admin_id = _require_admin(authorization)
    _conv(conversation_id)
    text = (request.message or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message is required")
    if len(text) > MAX_MESSAGE_CHARS:
        raise HTTPException(status_code=400, detail=f"Message too long (max {MAX_MESSAGE_CHARS} chars)")

    msg = conversation_service.admin_reply(conversation_id, admin_id, text)
    return {"message": msg}


@router.post("/conversations/{conversation_id}/take-over")
async def take_over(conversation_id: int, authorization: Optional[str] = Header(None)):
    admin_id = _require_admin(authorization)
    _conv(conversation_id)
    conversation_service.admin_take_over(conversation_id, admin_id)
    return {"success": True}


@router.post("/conversations/{conversation_id}/handback-to-ai")
async def handback_to_ai(
    conversation_id: int,
    request: HandBackRequest,
    authorization: Optional[str] = Header(None),
):
    admin_id = _require_admin(authorization)
    _conv(conversation_id)
    conversation_service.hand_back_to_ai(conversation_id, admin_id, request.note or "")
    return {"success": True}


@router.post("/conversations/{conversation_id}/assign")
async def assign(
    conversation_id: int,
    request: AssignRequest,
    authorization: Optional[str] = Header(None),
):
    admin_id = _require_admin(authorization)
    _conv(conversation_id)
    if request.admin_id is not None:
        # Validate the target is actually an admin.
        from database_adapter import get_db
        with get_db() as conn:
            row = conn.execute(
                "SELECT role FROM users WHERE id = ?", (request.admin_id,)
            ).fetchone()
        role = (dict(row) if row and not isinstance(row, dict) else row or {}).get("role")
        if role != "admin":
            raise HTTPException(status_code=400, detail="Target user is not an admin")
    conversation_service.assign_admin(conversation_id, request.admin_id)
    logger.info("[SUPPORT] admin %s assigned conversation %s to %s",
                admin_id, conversation_id, request.admin_id)
    return {"success": True}


@router.post("/conversations/{conversation_id}/priority")
async def set_priority(
    conversation_id: int,
    request: PriorityRequest,
    authorization: Optional[str] = Header(None),
):
    _require_admin(authorization)
    _conv(conversation_id)
    try:
        conversation_service.set_priority(conversation_id, request.priority)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True}


@router.post("/conversations/{conversation_id}/resolve")
async def resolve(conversation_id: int, authorization: Optional[str] = Header(None)):
    admin_id = _require_admin(authorization)
    _conv(conversation_id)
    conversation_service.resolve(conversation_id, admin_id)
    return {"success": True}


@router.post("/conversations/{conversation_id}/reopen")
async def reopen(conversation_id: int, authorization: Optional[str] = Header(None)):
    admin_id = _require_admin(authorization)
    _conv(conversation_id)
    conversation_service.reopen(conversation_id, by_admin=True)
    logger.info("[SUPPORT] admin %s reopened conversation %s", admin_id, conversation_id)
    return {"success": True}


# ======================================================================
# Internal notes + typing/read state
# ======================================================================

@router.post("/conversations/{conversation_id}/notes")
async def add_note(
    conversation_id: int,
    request: AdminNoteRequest,
    authorization: Optional[str] = Header(None),
):
    admin_id = _require_admin(authorization)
    _conv(conversation_id)
    note = (request.note or "").strip()
    if not note:
        raise HTTPException(status_code=400, detail="Note is required")
    row = conversation_service.admin_add_note(conversation_id, admin_id, note[:2000])
    return {"note": row}


@router.post("/conversations/{conversation_id}/typing")
async def typing(conversation_id: int, authorization: Optional[str] = Header(None)):
    _require_admin(authorization)
    _conv(conversation_id)
    conversation_service.bump_typing(conversation_id, "admin")
    return {"success": True}


@router.post("/conversations/{conversation_id}/read")
async def mark_read(conversation_id: int, authorization: Optional[str] = Header(None)):
    _require_admin(authorization)
    _conv(conversation_id)
    n = conversation_service.mark_read(conversation_id, reader="admin")
    return {"success": True, "marked": n}
