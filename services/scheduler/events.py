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

Delivery model: TTL-based, NOT consumed-on-read. Every job executed within
the freshness window (10 min) sees the newest event — so ALL of a project's
armed event jobs receive the same webhook body (handlers filter by event
content). Events expire after 15 min and are pruned opportunistically, so
stale webhooks never replay and the table stays tiny.
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

FRESH_SECONDS = 600      # events are deliverable for 10 minutes
PRUNE_MINUTES = 15       # hard delete after 15 minutes


def _filter_headers(headers: Dict[str, str]) -> Dict[str, str]:
    return {k.lower(): v for k, v in (headers or {}).items()
            if k.lower() in SAFE_HEADERS}


def record_event(project_id: int, headers: Dict[str, str], body: str) -> int:
    """Store an inbound webhook event. Returns the event id.
    Opportunistically prunes expired events for the project."""
    safe = _filter_headers(headers)
    with get_db() as cur:
        cur.execute("""
            DELETE FROM scheduler_events
            WHERE project_id = %s AND created_at < NOW() - INTERVAL '15 minutes'
        """, (project_id,))
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
    """Newest FRESH event for the project (within 10 minutes), if any.

    Does NOT consume — every job executing in the freshness window sees it.
    Returns {"headers": {...}, "body": "..."} (+ "body_json" when parseable)."""
    with get_db() as cur:
        cur.execute("""
            SELECT id, headers, body FROM scheduler_events
            WHERE project_id = %s
              AND created_at >= NOW() - INTERVAL '10 minutes'
            ORDER BY id DESC LIMIT 1
        """, (project_id,))
        row = cur.fetchone()
        if not row:
            return None
        d = dict(row) if not isinstance(row, dict) else row

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
