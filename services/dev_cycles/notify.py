#!/usr/bin/env python3
"""LISTEN/NOTIFY transport for the dev cycle engine.

Channel: `dev_cycle_events`. Payloads are JSON objects with an `event` key:
  {"event": "cycle_created",  "cycle_id": 1}
  {"event": "user_message",   "cycle_id": 1, "message_id": 42}
  {"event": "run_completed",  "run_id": 55, "kind": "session"|"creation",
   "status": "completed"|"failed"|"cancelled", "cycle_task_id": 3}

Producers call notify_cycle() (fire-and-forget, never raises into callers).
The engine holds one dedicated LISTEN connection (psycopg2 sync +
threaded poll — matches the platform's sync DB stack) and wakes on each
notification; a 60s reconcile pass covers lost events.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("services.dev_cycles.notify")

CHANNEL = "dev_cycle_events"


def notify_cycle(event: str, payload: Optional[Dict[str, Any]] = None) -> None:
    """Fire a dev-cycle event. Never raises — notification loss is tolerated
    (the engine's reconcile pass is the safety net)."""
    body = {"event": event, **(payload or {})}
    try:
        from database_postgres import get_db

        with get_db() as conn:
            conn.execute("SELECT pg_notify(%s, %s)", (CHANNEL, json.dumps(body)[:8000]))
            conn.commit()
    except Exception as exc:
        logger.warning("[DEV-CYCLE] notify failed (%s %s): %s", event, payload or {}, exc)


def notify_session_run(run_id: int, status: str, cycle_task_id: Optional[int] = None) -> None:
    """Hook helper — call after session_chat_runs status transitions."""
    notify_cycle("run_completed", {
        "kind": "session",
        "run_id": int(run_id),
        "status": status,
        "cycle_task_id": cycle_task_id,
    })


def notify_creation_run(run_id: int, project_id: Optional[int], status: str,
                        cycle_task_id: Optional[int] = None) -> None:
    """Hook helper — call after project_creation_runs status transitions."""
    notify_cycle("run_completed", {
        "kind": "creation",
        "run_id": int(run_id),
        "project_id": project_id,
        "status": status,
        "cycle_task_id": cycle_task_id,
    })


# ---------------------------------------------------------------------------
# Consumer side — a dedicated LISTEN connection with a thread-safe queue.
# ---------------------------------------------------------------------------

def open_listen_connection():
    """Open a dedicated psycopg2 connection with LISTEN on the channel.

    Returns the raw connection (NOT from the pool — LISTEN connections must
    stay idle-dedicated; pooling them breaks notification delivery).
    Caller is responsible for keeping it alive (the engine reconnects on
    error).
    """
    import psycopg2
    import os

    dsn_parts = []
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "dreampilot")
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "")
    conn = psycopg2.connect(
        host=host, port=port, dbname=name, user=user, password=password,
        connect_timeout=10,
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"LISTEN {CHANNEL};")
    return conn
