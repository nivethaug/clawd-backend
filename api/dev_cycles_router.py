#!/usr/bin/env python3
"""Dev Cycles Router — the chat + board API for the delivery orchestrator.

Mounted at: /api/dev-cycles

  POST /api/dev-cycles                          create a cycle (one active/user)
  GET  /api/dev-cycles                          list user's cycles
  GET  /api/dev-cycles/{id}                     detail: messages + tasks + plan/dod
  POST /api/dev-cycles/{id}/messages            user turn (notifies engine)
  GET  /api/dev-cycles/{id}/events              SSE stream of new messages/tasks
                                               (v1: frontend polls detail instead)

All endpoints owner-gated. Paid tier required (same gate as custom domains).
"""

from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("api.dev_cycles")

router = APIRouter()


def _uid(authorization: Optional[str]) -> int:
    from app import get_user_id_from_token
    return get_user_id_from_token(authorization)


def _require_paid(user_id: int) -> None:
    try:
        from services.rate_limiter import get_user_tier_and_role
        tr = get_user_tier_and_role(user_id) or {}
        if tr.get("tier") == "free" and tr.get("role") != "admin":
            raise HTTPException(status_code=402, detail="Dev Cycles require a paid plan")
    except HTTPException:
        raise
    except Exception:
        pass  # tier lookup failure → allow


def _own_cycle(cycle_id: int, user_id: int) -> dict:
    from services.dev_cycles import store
    cycle = store.get_cycle(cycle_id)
    if not cycle:
        raise HTTPException(status_code=404, detail="Cycle not found")
    if cycle["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not your cycle")
    return cycle


class CreateCycleRequest(BaseModel):
    telegram_chat_id: Optional[str] = None
    project_id: Optional[int] = None


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=8000)


@router.post("")
async def create_cycle(request: CreateCycleRequest, authorization: Optional[str] = Header(None)):
    from services.dev_cycles import store
    from services.dev_cycles.notify import notify_cycle

    user_id = _uid(authorization)
    _require_paid(user_id)
    if store.has_active_cycle(user_id):
        raise HTTPException(status_code=409,
                             detail="You already have an active dev cycle — finish or pause it first")

    # Existing-project mode: validate the project is the user's website
    if request.project_id is not None:
        from database_postgres import get_db
        with get_db() as conn:
            proj = conn.execute(
                "SELECT id, user_id, type_id FROM projects WHERE id = %s",
                (request.project_id,),
            ).fetchone()
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")
        proj = dict(proj) if not isinstance(proj, dict) else proj
        if proj["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Not your project")
        if int(proj.get("type_id") or 0) != 1:
            raise HTTPException(status_code=400, detail="Dev Cycles only work with website projects")

    cycle = store.create_cycle(user_id, request.telegram_chat_id, request.project_id)
    notify_cycle("cycle_created", {"cycle_id": cycle["id"]})
    return {"success": True, "cycle": cycle}


@router.get("")
async def list_cycles(authorization: Optional[str] = Header(None)):
    from database_postgres import get_db
    user_id = _uid(authorization)
    with get_db() as conn:
        rows = conn.execute(
            """SELECT c.*, (SELECT COUNT(*) FROM cycle_tasks t
                           WHERE t.cycle_id = c.id AND t.status = 'done') AS tasks_done,
                      (SELECT COUNT(*) FROM cycle_tasks t WHERE t.cycle_id = c.id) AS tasks_total
               FROM dev_cycles c WHERE c.user_id = %s
               ORDER BY c.id DESC LIMIT 50""",
            (user_id,),
        ).fetchall()
    return {"cycles": [dict(r) if not isinstance(r, dict) else r for r in rows]}


@router.get("/{cycle_id}")
async def cycle_detail(cycle_id: int, authorization: Optional[str] = Header(None)):
    from services.dev_cycles import store
    user_id = _uid(authorization)
    cycle = _own_cycle(cycle_id, user_id)
    messages = store.get_messages(cycle_id)
    tasks = store.get_tasks(cycle_id)
    return {"cycle": cycle, "messages": messages, "tasks": tasks}


@router.post("/{cycle_id}/cancel")
async def cancel_cycle(cycle_id: int, authorization: Optional[str] = Header(None)):
    """User-initiated stop: closes unfinished tasks and frees the one-active
    slot. An in-flight build run is left to finish on the worker; its
    completion event finds no open task and is ignored."""
    from services.dev_cycles import store
    from services.dev_cycles.notify import notify_cycle

    user_id = _uid(authorization)
    cycle = _own_cycle(cycle_id, user_id)
    if cycle["status"] in ("delivered", "failed", "cancelled"):
        raise HTTPException(status_code=409, detail="Cycle already finished")
    store.cancel_cycle(cycle_id)
    store.add_message(cycle_id, "agent",
                      "🛑 Cycle cancelled. Your project is kept as-is — start a "
                      "new cycle anytime.")
    notify_cycle("cycle_cancelled", {"cycle_id": cycle_id})
    return {"ok": True, "status": "cancelled"}


@router.post("/{cycle_id}/messages")
async def send_message(cycle_id: int, request: SendMessageRequest,
                       authorization: Optional[str] = Header(None)):
    from services.dev_cycles import store
    from services.dev_cycles.notify import notify_cycle

    user_id = _uid(authorization)
    cycle = _own_cycle(cycle_id, user_id)
    if cycle["status"] == "cancelled":
        raise HTTPException(status_code=409,
                            detail="This cycle was cancelled — start a new one to continue")
    msg = store.add_message(cycle_id, "user", request.content)
    notify_cycle("user_message", {"cycle_id": cycle_id, "message_id": msg["id"]})
    return {"success": True, "message": msg}
