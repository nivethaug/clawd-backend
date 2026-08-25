#!/usr/bin/env python3
"""
Triggers Router — public webhook endpoints that fire a project's event jobs.

Mounted at: /api/triggers

  POST /api/triggers/{token}   → record the webhook event + re-arm the
                                  project's job_type='event' jobs (run on
                                  the next scheduler poll, ≤10s). The event
                                  body/headers reach the executor as
                                  job["event"].
  GET  /api/triggers/{token}   → browser-verifiable ping.
  GET  /api/triggers/info/{project_id} → owner-JWT / worker-IP-allowlist
                                  → the project's trigger URL (lazily
                                  generates the token for legacy projects).

Auth model: the token IS the credential (token_urlsafe(24), per project,
UNIQUE) — standard webhook practice (GitHub/Stripe style). Unknown token →
404 without leaking existence. Bodies are capped at 64KB; only a safe
header subset is persisted (never cookies/authorization). Rate-limited via
the platform limiter keyed by the project owner.
"""

import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request, Request as _Req
from fastapi.responses import JSONResponse

from database_postgres import get_db

logger = logging.getLogger("api.triggers")

router = APIRouter()

_BODY_MAX_BYTES = 64 * 1024


def _row(row):
    return dict(row) if row is not None and not isinstance(row, dict) else row


def _resolve_token(token: str) -> Optional[dict]:
    """Project row for a trigger token, or None."""
    if not token or len(token) > 128:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, user_id, name FROM projects WHERE trigger_token = %s",
            (token,),
        ).fetchone()
    return _row(row) if row else None


def _ensure_trigger_token(project_id: int) -> str:
    """Return the project's trigger token, generating one if missing
    (legacy projects / clones created before triggers shipped)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT trigger_token FROM projects WHERE id = %s", (project_id,)
        ).fetchone()
    token = (_row(row) or {}).get("trigger_token") if row else None
    if token:
        return token
    token = secrets.token_urlsafe(24)
    with get_db() as conn:
        conn.execute(
            "UPDATE projects SET trigger_token = %s WHERE id = %s",
            (token, project_id),
        )
        conn.commit()
    logger.info("[TRIGGERS] generated token for project %s", project_id)
    return token


@router.post("/{token}")
async def trigger_event(token: str, request: Request):
    """Webhook ingress: store the event, arm the project's event jobs."""
    project = _resolve_token(token)
    if not project:
        raise HTTPException(status_code=404, detail="Not found")

    # Tier-based rate limit keyed by the project owner
    try:
        from services.rate_limiter import check_rate_limit
        verdict = check_rate_limit(int(project["user_id"]), "webhook_trigger")
        if not verdict.get("allowed"):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(verdict.get("retry_after", 60))},
            )
    except Exception as e:  # limiter down → fail open (webhooks retry anyway)
        logger.warning("[TRIGGERS] rate limiter unavailable: %s", e)

    raw = await request.body()
    if len(raw) > _BODY_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Body exceeds 64KB")
    body = raw.decode("utf-8", errors="replace")

    from services.scheduler.events import record_event
    from services.scheduler.jobs import trigger_event_jobs
    event_id = record_event(int(project["id"]), dict(request.headers), body)
    armed = trigger_event_jobs(int(project["id"]))

    logger.info(
        "[TRIGGERS] project %s (%s): event %d recorded, %d job(s) armed",
        project["id"], project.get("name"), event_id, armed,
    )
    return {"triggered": armed, "event_id": event_id}


@router.get("/{token}")
async def trigger_ping(token: str):
    """Browser-verifiable ping for the trigger URL."""
    project = _resolve_token(token)
    if not project:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True, "project": project.get("name")}


@router.get("/info/{project_id}")
async def trigger_info(
    project_id: int,
    authorization: Optional[str] = Header(None),
    request_obj: Request = None,
):
    """The project's webhook trigger URL (owner JWT or worker-IP allowlist —
    same auth as the scheduler job API, so in-container agents can curl it)."""
    from api.scheduler_router import _require_project_owner
    _require_project_owner(project_id, authorization, request_obj)

    token = _ensure_trigger_token(project_id)
    backend = "https://api.dreamagent.cloud"
    import os as _os
    backend = _os.getenv("SCHEDULER_BACKEND_URL", backend).rstrip("/")
    return {"project_id": project_id, "url": f"{backend}/api/triggers/{token}"}
