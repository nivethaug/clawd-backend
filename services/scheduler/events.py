#!/usr/bin/env python3
"""
Scheduler Events — inbound webhook payloads awaiting pickup by the
execution engine.

Flow:
  POST /api/triggers/{token}  ->  record_event(project_id, headers, body)
                              ->  jobs.trigger_event_jobs(project_id)
  worker picks up armed jobs   ->  take_pending_event(project_id) is attached
                                    to the job dict as job["event"] just
                                    before the executor subprocess runs.

One unconsumed event is delivered to the NEXT executed job of the project;
everything older is marked consumed in the same pass (latest-wins, no
backlog replay storms).
"""

import json
import logging
from typing import Optional, Dict, Any

from database_postgres import get_db

logger = logging.getLogger('scheduler.events')

# Headers safe to expose to executors — deliberately excludes cookies,
# authorization and other credential-bearing headers.
SAFE_HEADERS = frozenset({
    "content-type", "user-agent",
    "x-github-event", "x-github-delivery", "x-github-hook-id",
    "x-event-type", "x-event", "x-webhook-event", "x-hook-event",
    "x-signature", "x-hub-signature-256", "x-razorpay-event", "x-razorpay-signature",
    "svix-id", "svix-type", "svix-signature",
})


def _filter_headers(headers: Dict[str, str]) -> Dict[str, str]:
    return {k.lower(): v for k, v in (headers or {}).items()
            if k.lower() in SAFE_HEADERS}


def record_event(project_id: int, headers: Dict[str, str], body: str) -> int:
    """Store an inbound webhook event. Returns the event id."""
    safe = _filter_headers(headers)
    with get_db() as cur:
        cur.execute("""
            INSERT INTO scheduler_events (project_id, headers, body)
            VALUES (%s, %s::jsonb, %s)
            RETURNING id
        """, (project_id, json.dumps(safe), body))
        conn = cur._connection
        conn.commit()
        row = cur.fetchone()
        event_id = (dict(row) if row and not isinstance(row, dict) else row)["id"]
        logger.info("Event %d recorded for project %s", event_id, project_id)
        return int(event_id)


def take_pending_event(project_id: int) -> Optional[Dict[str, Any]]:
    """Newest unconsumed event for the project, marked consumed (all of them).

    Returns {"headers": {...}, "body": "..."} or None. Best-effort parse of
    the body into JSON when possible (body_json key added)."""
    with get_db() as cur:
        cur.execute("""
            SELECT id, headers, body FROM scheduler_events
            WHERE project_id = %s AND consumed = false
            ORDER BY id DESC LIMIT 1
        """, (project_id,))
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row) if not isinstance(row, dict) else row
        cur.execute("""
            UPDATE scheduler_events SET consumed = true
            WHERE project_id = %s AND consumed = false
        """, (project_id,))
        conn = cur._connection
        conn.commit()

        headers = d.get("headers") or {}
        if isinstance(headers, str):
            try:
                headers = json.loads(headers)
            except Exception:
                headers = {}
        body = d.get("body") or ""
        out: Dict[str, Any] = {"headers": headers, "body": body}
        try:
            out["body_json"] = json.loads(body)
        except Exception:
            pass
        return out
