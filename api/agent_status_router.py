#!/usr/bin/env python3
"""
Agent Status Router — public, token-scoped, read-only data for an agent's
frontend-only dashboard.

Mounted at: /api/agent-status

  GET /api/agent-status/{token}
      → {name, description, jobs[], recent_logs[], state, collections, trigger_url}
  GET /api/agent-status/{token}/collections/{name}?limit=100
      → {name, count, docs[]} (from the agent's SQLite document DB)

The token is the project's EXISTING webhook trigger token (token_urlsafe(24),
per project, UNIQUE — minted at agent creation). Same credential model as the
webhook itself: the URL is the secret, unknown token → 404 without leaking
existence. Everything is read-only and scoped to exactly one project.

Data sources:
  - Platform Postgres (this VPS): scheduler_jobs, scheduler_logs,
    scheduler_state — same queries the owner-facing scheduler_router serves.
  - The project's agent.db (SQLite on the worker VPS): proxied read-only via
    the worker's /internal/agent-db endpoints. Worker unreachable → the
    collections field degrades to {}; platform data still serves.

A small per-token response cache (default 5s) keeps dashboard polling (15s)
from hammering either store.
"""

import logging
import threading
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from database_postgres import get_db

logger = logging.getLogger("api.agent_status")

router = APIRouter()

_CACHE_TTL_SECONDS = 5.0
_cache: Dict[str, tuple] = {}  # token -> (monotonic_ts, payload)
_cache_lock = threading.Lock()


def _row(row):
    return dict(row) if row is not None and not isinstance(row, dict) else row


def _resolve_token(token: str) -> Optional[dict]:
    """Project row for a trigger token, or None. Mirrors triggers_router."""
    if not token or len(token) > 128:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, user_id, name, description FROM projects WHERE trigger_token = %s",
            (token,),
        ).fetchone()
    return _row(row) if row else None


def _platform_data(project_id: int) -> Dict[str, Any]:
    """Jobs, recent logs and state from the platform scheduler tables."""
    data: Dict[str, Any] = {"jobs": [], "recent_logs": [], "state": None}
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, job_type, schedule_value, task_type, status,
                   last_run, next_run
            FROM scheduler_jobs
            WHERE project_id = %s
            ORDER BY id
            """,
            (project_id,),
        ).fetchall()
        data["jobs"] = [_row(r) for r in rows]

        rows = conn.execute(
            """
            SELECT sl.created_at, sj.task_type, sl.status, sl.message
            FROM scheduler_logs sl
            JOIN scheduler_jobs sj ON sj.id = sl.job_id
            WHERE sj.project_id = %s
            ORDER BY sl.created_at DESC
            LIMIT 50
            """,
            (project_id,),
        ).fetchall()
        data["recent_logs"] = [_row(r) for r in rows]

        row = conn.execute(
            "SELECT state FROM scheduler_state WHERE project_id = %s",
            (project_id,),
        ).fetchone()
        if row:
            state = _row(row).get("state")
            if isinstance(state, str):
                try:
                    import json as _json
                    state = _json.loads(state)
                except ValueError:
                    state = {}
            data["state"] = state or None
    return data


def _proxy_agent_db(project_id: int, collection: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
    """Read the project's agent.db through the worker's internal endpoint.

    Any failure (no registered node, worker down, timeout) → empty
    collections — the dashboard degrades gracefully to platform data.
    """
    try:
        from services import worker_registry as _wr
        from services.project_proxy import _get_worker_url
        import os as _os

        node = _wr.resolve_for_project(project_id)
        if node and node.get("api_url"):
            worker_url = str(node["api_url"]).rstrip("/")
            headers = {}
            sec = _wr.internal_secret_for_node(node.get("id"))
            if sec:
                headers["x-internal-secret"] = sec
        else:
            worker_url = (_os.getenv("WORKER_VPS_URL") or _get_worker_url() or "").rstrip("/")
            headers = {}
            fleet = _os.getenv("INTERNAL_API_SECRET", "").strip()
            if fleet:
                headers["x-internal-secret"] = fleet

        if not worker_url:
            return {"collections": {}}

        import httpx as _httpx

        if collection is None:
            url = f"{worker_url}/internal/agent-db/{project_id}/collections?limit={int(limit)}"
        else:
            url = f"{worker_url}/internal/agent-db/{project_id}/collections/{collection}?limit={int(limit)}"
        resp = _httpx.get(url, headers=headers, timeout=4.0)
        if resp.status_code == 200:
            return resp.json()
        logger.info(
            "[AGENT-STATUS] worker agent-db read for %s returned %s", project_id, resp.status_code
        )
    except Exception as exc:
        logger.warning("[AGENT-STATUS] worker agent-db read for %s failed: %s", project_id, exc)
    return {"collections": {}}


def _trigger_url(token: str) -> str:
    import os as _os
    backend = _os.getenv("SCHEDULER_BACKEND_URL", "https://api.dreamagent.cloud").rstrip("/")
    return f"{backend}/api/triggers/{token}"


@router.get("/{token}")
async def agent_status(token: str):
    """Full dashboard payload for the agent owning this token."""
    project = _resolve_token(token)
    if not project:
        raise HTTPException(status_code=404, detail="Not found")

    with _cache_lock:
        hit = _cache.get(token)
        if hit and time.monotonic() - hit[0] < _CACHE_TTL_SECONDS:
            return hit[1]

    project_id = int(project["id"])
    payload = _platform_data(project_id)
    payload["name"] = project.get("name")
    payload["description"] = project.get("description")
    proxy_data = _proxy_agent_db(project_id)
    payload["collections"] = proxy_data.get("collections", {})
    payload["channels"] = proxy_data.get("channels", [])
    payload["trigger_url"] = _trigger_url(token)

    with _cache_lock:
        _cache[token] = (time.monotonic(), payload)
        if len(_cache) > 512:  # bound memory: drop the oldest quarter
            oldest = sorted(_cache.items(), key=lambda kv: kv[1][0])[:128]
            for k, _ in oldest:
                _cache.pop(k, None)
    return payload


@router.get("/{token}/collections/{collection}")
async def agent_status_collection(token: str, collection: str, limit: int = 100):
    """Latest documents of ONE agent.db collection (dashboard detail fetch)."""
    import re as _re
    if not _re.match(r"^[A-Za-z0-9_.-]+$", collection or ""):
        raise HTTPException(status_code=400, detail="Invalid collection name")

    project = _resolve_token(token)
    if not project:
        raise HTTPException(status_code=404, detail="Not found")

    data = _proxy_agent_db(int(project["id"]), collection=collection, limit=limit)
    entry = (data.get("collections") or {}).get(collection)
    if entry is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    return {"name": collection, "count": entry.get("count", 0), "docs": entry.get("docs", [])}
