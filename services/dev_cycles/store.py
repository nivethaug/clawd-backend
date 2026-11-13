#!/usr/bin/env python3
"""DB access for dev cycles — cycles, messages, tasks.

All state lives in Postgres rows (engine is restart-safe by construction).
Pure CRUD + status transitions; no business logic here.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("services.dev_cycles.store")

from database_postgres import get_db


def _d(row) -> Optional[Dict[str, Any]]:
    return dict(row) if row is not None and not isinstance(row, dict) else row


# ── cycles ───────────────────────────────────────────────────────────────

def create_cycle(user_id: int, telegram_chat_id: Optional[str] = None,
                 project_id: Optional[int] = None) -> Dict[str, Any]:
    """Create a cycle. project_id set = drive an EXISTING project
    (instruct/verify tasks only); None = engine creates a new project."""
    with get_db() as conn:
        row = conn.execute(
            """INSERT INTO dev_cycles (user_id, status, telegram_chat_id, project_id)
               VALUES (%s, 'intake', %s, %s) RETURNING *""",
            (user_id, telegram_chat_id, project_id),
        ).fetchone()
        conn.commit()
    return _d(row)


def get_cycle(cycle_id: int) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM dev_cycles WHERE id = %s", (cycle_id,)).fetchone()
    return _d(row)


def update_cycle(cycle_id: int, **fields: Any) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k} = %s" for k in fields)
    vals = list(fields.values()) + [cycle_id]
    with get_db() as conn:
        conn.execute(
            f"UPDATE dev_cycles SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            vals,
        )
        conn.commit()


def has_active_cycle(user_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute(
            """SELECT 1 FROM dev_cycles
               WHERE user_id = %s AND status NOT IN ('delivered', 'failed', 'cancelled')
               LIMIT 1""",
            (user_id,),
        ).fetchone()
    return row is not None


def active_cycles() -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM dev_cycles WHERE status NOT IN ('delivered', 'failed', 'cancelled') ORDER BY id"
        ).fetchall()
    return [_d(r) for r in rows]


def cancel_cycle(cycle_id: int) -> None:
    """User-initiated stop: the cycle leaves the active set (so a new one
    can start) and every unfinished task is closed. A build run already on
    the worker is left to finish; its completion event finds no open task."""
    with get_db() as conn:
        conn.execute(
            """UPDATE cycle_tasks SET status = 'failed',
                      result = '{"error": "cancelled"}'::jsonb,
                      updated_at = CURRENT_TIMESTAMP
               WHERE cycle_id = %s AND status NOT IN ('done', 'failed')""",
            (cycle_id,),
        )
        conn.execute(
            "UPDATE dev_cycles SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (cycle_id,),
        )
        conn.commit()


# ── messages ─────────────────────────────────────────────────────────────

def add_message(cycle_id: int, role: str, content: str, meta: Optional[Dict] = None) -> Dict[str, Any]:
    with get_db() as conn:
        row = conn.execute(
            """INSERT INTO cycle_messages (cycle_id, role, content, meta)
               VALUES (%s, %s, %s, %s::jsonb) RETURNING *""",
            (cycle_id, role, content, json.dumps(meta or {})),
        ).fetchone()
        conn.commit()
    return _d(row)


def get_messages(cycle_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM cycle_messages WHERE cycle_id = %s
               ORDER BY id DESC LIMIT %s""",
            (cycle_id, limit),
        ).fetchall()
    out = [_d(r) for r in rows]
    out.reverse()
    return out


# ── tasks ────────────────────────────────────────────────────────────────

def add_task(cycle_id: int, position: int, title: str, description: str,
             kind: str, payload: Optional[Dict] = None,
             dod_item: Optional[Dict] = None) -> Dict[str, Any]:
    with get_db() as conn:
        row = conn.execute(
            """INSERT INTO cycle_tasks
               (cycle_id, position, title, description, kind, payload, dod_item)
               VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb) RETURNING *""",
            (cycle_id, position, title, description, kind,
             json.dumps(payload or {}), json.dumps(dod_item) if dod_item else None),
        ).fetchone()
        conn.commit()
    return _d(row)


def get_tasks(cycle_id: int) -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            # age_s = seconds since the last status change, computed in SQL:
            # updated_at is a naive TIMESTAMP, so comparing it to a Python
            # datetime is timezone-ambiguous (it silently broke the
            # wall-clock timeout).
            """SELECT *, EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - updated_at))::int AS age_s
               FROM cycle_tasks WHERE cycle_id = %s ORDER BY position, id""",
            (cycle_id,),
        ).fetchall()
    return [_d(r) for r in rows]


def update_task(task_id: int, **fields: Any) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k} = %s" for k in fields)
    vals = list(fields.values()) + [task_id]
    with get_db() as conn:
        conn.execute(
            f"UPDATE cycle_tasks SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            vals,
        )
        conn.commit()


def task_by_session_run(run_id: int) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM cycle_tasks WHERE session_run_id = %s AND status IN ('in_progress', 'under_review') LIMIT 1",
            (run_id,),
        ).fetchone()
    return _d(row)


def task_by_creation_run(run_id: int) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM cycle_tasks WHERE creation_run_id = %s AND status IN ('in_progress', 'under_review') LIMIT 1",
            (run_id,),
        ).fetchone()
    return _d(row)


def find_task_by_run(run_id: int, kind: str) -> Optional[Dict[str, Any]]:
    return task_by_session_run(run_id) if kind == "session" else task_by_creation_run(run_id)
