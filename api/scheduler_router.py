#!/usr/bin/env python3
"""
Scheduler Job API Router - REST endpoints for job management.

LLM agents call these endpoints to create, list, update, and manage
scheduler jobs. Jobs are stored in the main dreampilot DB.

Prefix: /api/scheduler

INTERNAL BYPASS
---------------
Requests from a trusted internal caller (the worker VPS that runs scheduler
executors inside bwrap sandboxes) bypass JWT auth. The executor's job_manager.py
has no user token — it lives inside the sandbox with only its own project's
.env. Without this bypass, job_manager.create/list/etc. fail with 401.

The allowlist is configured via SCHEDULER_INTERNAL_ALLOWLIST (comma-separated
IPs/CIDRs). If unset, bypass is disabled and all requests require JWT (the
default for local dev + main VPS without a separate worker).

Security model:
  - The bypass trusts the SOURCE IP only. A request claiming to be from the
    worker VPS but actually from elsewhere is rejected (TCP source can't be
    spoofed; the connection itself wouldn't establish).
  - Project-scoping still applies: the executor's job_manager only knows its
    own PROJECT_ID, so even a compromised executor can only touch its own
    project's jobs.
  - The allowlist should ONLY contain the worker VPS public IP, never
    arbitrary public IPs.
"""

import logging
import os
import ipaddress
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from services.scheduler import (
    create_job,
    update_job,
    delete_job,
    list_jobs,
    get_job,
    pause_job,
    resume_job,
    run_job_now,
    clear_jobs,
)
from services.scheduler.logger import log_job
from database_postgres import get_db
from utils.auth_helpers import get_user_id_from_token

logger = logging.getLogger('api.scheduler')

router = APIRouter()


# ---------------------------------------------------------------------------
# Internal IP allowlist (worker VPS bypass)
# ---------------------------------------------------------------------------

def _load_internal_allowlist() -> List[ipaddress.IPv4Network]:
    """Parse SCHEDULER_INTERNAL_ALLOWLIST env into a list of networks.

    Accepts plain IPs ("203.0.113.5") or CIDRs ("203.0.113.0/24"). Whitespace
    around entries is ignored. Empty/unset → empty list (bypass disabled).
    """
    raw = os.getenv("SCHEDULER_INTERNAL_ALLOWLIST", "").strip()
    if not raw:
        return []
    networks = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            # strict=False so a bare IP is interpreted as /32 (IPv4) or /128 (IPv6)
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError as e:
            logger.warning(f"SCHEDULER_INTERNAL_ALLOWLIST: ignoring invalid entry {entry!r}: {e}")
    return networks


_INTERNAL_ALLOWLIST = _load_internal_allowlist()


def _is_internal_call(request_obj: Request) -> bool:
    """True if the caller's IP is in SCHEDULER_INTERNAL_ALLOWLIST.

    Reads request_obj.client.host — FastAPI's view of the TCP peer. When the
    backend sits behind nginx, this is nginx's IP (127.0.0.1 or the docker
    bridge), so nginx MUST be configured to forward the real client IP via
    X-Forwarded-For AND the backend must trust that header. We check both:
      1. Direct client IP (TCP peer)
      2. X-Forwarded-For (last entry, set by nginx) — if the peer is local

    The X-Forwarded-For check is gated on the peer being a trusted proxy IP
    (loopback or docker bridge) so an external attacker can't just set the
    header themselves.
    """
    if not _INTERNAL_ALLOWLIST:
        return False

    peer = request_obj.client.host if request_obj.client else ""
    if not peer:
        return False

    # 1. Direct peer match (worker VPS connecting directly to backend port,
    #    bypassing nginx — common for inter-VPS internal traffic).
    if _ip_in_allowlist(peer):
        return True

    # 2. X-Forwarded-For match, but ONLY if the peer is a trusted proxy.
    #    This prevents an attacker from setting X-Forwarded-For from outside.
    if _is_trusted_proxy(peer):
        xff = request_obj.headers.get("x-forwarded-for", "")
        if xff:
            # XFF can be a chain "client, proxy1, proxy2". The original client
            # is the FIRST entry; we check ALL of them since the worker VPS
            # IP could appear at any position depending on proxy chain depth.
            for xff_ip in [s.strip() for s in xff.split(",") if s.strip()]:
                if _ip_in_allowlist(xff_ip):
                    return True

    return False


def _ip_in_allowlist(ip_str: str) -> bool:
    """True if ip_str matches any network in _INTERNAL_ALLOWLIST."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(ip in net for net in _INTERNAL_ALLOWLIST)


def _is_trusted_proxy(ip_str: str) -> bool:
    """True if ip_str is loopback, link-local, or a private RFC1918 range.

    These are the IPs we trust to have set X-Forwarded-For honestly. nginx,
    docker bridge, and any internal proxy all fall in these ranges.
    """
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_link_local or ip.is_private


def _resolve_caller_user_id(request_obj: Request, authorization: Optional[str], project_id: int) -> int:
    """Resolve user_id from JWT, OR bypass if the caller is on the allowlist.

    Used by every endpoint in this router. The bypass returns the project's
    owner_id from the DB — so downstream code paths that need user_id (logging,
    ownership checks) still see a valid ID. This keeps the executor able to
    create/list/update jobs for its OWN project while still enforcing
    project-scoping at the DB layer.
    """
    if _is_internal_call(request_obj):
        # Internal caller (worker VPS executor): no JWT. Look up the project
        # owner directly so the rest of the code path has a valid user_id.
        with get_db() as cur:
            cur.execute("SELECT user_id FROM projects WHERE id = %s", (project_id,))
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")
        return int(_row_value(row, "user_id", 0))

    # Public path: require a valid JWT.
    return get_user_id_from_token(authorization)


def _row_value(row: Any, key: str, index: int = 0) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return row[index]


def _require_project_owner(project_id: int, authorization: Optional[str], request_obj: Request = None) -> int:
    """Authorize the caller for project_id.

    If request_obj is provided and the caller is on SCHEDULER_INTERNAL_ALLOWLIST,
    skip JWT auth and return the project's owner_id (the executor running in
    the bwrap sandbox has no JWT, but is scoped to its own PROJECT_ID env).
    Otherwise require a valid JWT matching the project owner.
    """
    if request_obj is not None and _is_internal_call(request_obj):
        with get_db() as cur:
            cur.execute("SELECT user_id FROM projects WHERE id = %s", (project_id,))
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")
        return int(_row_value(row, "user_id", 0))

    user_id = get_user_id_from_token(authorization)
    with get_db() as cur:
        cur.execute("SELECT user_id FROM projects WHERE id = %s", (project_id,))
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    owner_id = _row_value(row, "user_id", 0)
    if int(owner_id) != int(user_id):
        raise HTTPException(status_code=403, detail="Not authorized for this project")
    return int(user_id)


def _require_job_owner(job_id: int, authorization: Optional[str], request_obj: Request = None) -> int:
    """Authorize the caller for job_id (and its parent project).

    Same bypass logic as _require_project_owner — internal callers from the
    allowlist skip JWT and get the project owner's user_id.
    """
    if request_obj is not None and _is_internal_call(request_obj):
        with get_db() as cur:
            cur.execute(
                """
                SELECT sj.id, sj.project_id, p.user_id
                FROM scheduler_jobs sj
                JOIN projects p ON p.id = sj.project_id
                WHERE sj.id = %s
                """,
                (job_id,),
            )
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Job not found")
        return int(_row_value(row, "user_id", 2))

    user_id = get_user_id_from_token(authorization)
    with get_db() as cur:
        cur.execute(
            """
            SELECT sj.id, sj.project_id, p.user_id
            FROM scheduler_jobs sj
            JOIN projects p ON p.id = sj.project_id
            WHERE sj.id = %s
            """,
            (job_id,),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    owner_id = _row_value(row, "user_id", 2)
    if int(owner_id) != int(user_id):
        raise HTTPException(status_code=403, detail="Not authorized for this job")
    return int(user_id)


# ============================================================================
# Pydantic Models
# ============================================================================

class JobCreateRequest(BaseModel):
    job_type: str  # interval, daily, once
    schedule_value: str  # 10m, 1h, 2d, daily:09:00
    task_type: str  # free-form: telegram, email, btc_email, weather_alert, etc.
    payload: Dict[str, Any] = {}


class JobUpdateRequest(BaseModel):
    schedule_value: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    status: Optional[str] = None


class JobResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    job: Optional[Dict[str, Any]] = None
    jobs: Optional[List[Dict[str, Any]]] = None


class LogEntry(BaseModel):
    id: int
    job_id: int
    status: str
    message: Optional[str] = None
    created_at: Optional[str] = None


class LogsResponse(BaseModel):
    success: bool
    logs: Optional[List[Dict[str, Any]]] = None
    count: Optional[int] = None


# ============================================================================
# Job CRUD Endpoints
# ============================================================================

@router.post("/projects/{project_id}/jobs", response_model=JobResponse)
async def api_create_job(
    project_id: int,
    request: JobCreateRequest,
    authorization: Optional[str] = Header(None),
    request_obj: Request = None,
):
    """Create a new scheduled job for a project."""
    _require_project_owner(project_id, authorization, request_obj)
    try:
        job = create_job(project_id=project_id, job_data={
            "job_type": request.job_type,
            "schedule_value": request.schedule_value,
            "task_type": request.task_type,
            "payload": request.payload,
        })
        logger.info(f"Job created via API: project={project_id} type={request.task_type}")
        return JobResponse(success=True, message="Job created", job=job)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/jobs", response_model=JobResponse)
async def api_list_jobs(
    project_id: int,
    authorization: Optional[str] = Header(None),
    request_obj: Request = None,
):
    """List all jobs for a project."""
    _require_project_owner(project_id, authorization, request_obj)
    try:
        jobs = list_jobs(project_id)
        return JobResponse(success=True, jobs=jobs, count=len(jobs))
    except Exception as e:
        logger.error(f"Failed to list jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def api_get_job(
    job_id: int,
    authorization: Optional[str] = Header(None),
    request_obj: Request = None,
):
    """Get a specific job by ID."""
    _require_job_owner(job_id, authorization, request_obj)
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse(success=True, job=job)


@router.put("/jobs/{job_id}", response_model=JobResponse)
async def api_update_job(
    job_id: int,
    request: JobUpdateRequest,
    authorization: Optional[str] = Header(None),
    request_obj: Request = None,
):
    """Update a job's schedule, payload, or status."""
    _require_job_owner(job_id, authorization, request_obj)
    try:
        updates = {}
        if request.schedule_value is not None:
            updates["schedule_value"] = request.schedule_value
        if request.payload is not None:
            updates["payload"] = request.payload
        if request.status is not None:
            updates["status"] = request.status

        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        job = update_job(job_id, updates)
        return JobResponse(success=True, message="Job updated", job=job)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/jobs/{job_id}", response_model=JobResponse)
async def api_delete_job(
    job_id: int,
    authorization: Optional[str] = Header(None),
    request_obj: Request = None,
):
    """Delete a job and its execution logs."""
    _require_job_owner(job_id, authorization, request_obj)
    deleted = delete_job(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse(success=True, message="Job deleted")


@router.post("/jobs/{job_id}/pause", response_model=JobResponse)
async def api_pause_job(
    job_id: int,
    authorization: Optional[str] = Header(None),
    request_obj: Request = None,
):
    """Pause an active job."""
    _require_job_owner(job_id, authorization, request_obj)
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get('status') != 'active':
        raise HTTPException(status_code=400, detail=f"Job is {job.get('status')}, not active")
    pause_job(job_id)
    return JobResponse(success=True, message="Job paused")


@router.post("/jobs/{job_id}/resume", response_model=JobResponse)
async def api_resume_job(
    job_id: int,
    authorization: Optional[str] = Header(None),
    request_obj: Request = None,
):
    """Resume a paused job."""
    _require_job_owner(job_id, authorization, request_obj)
    try:
        resume_job(job_id)
        return JobResponse(success=True, message="Job resumed")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/jobs/{job_id}/run", response_model=JobResponse)
async def api_run_job_now(
    job_id: int,
    authorization: Optional[str] = Header(None),
    request_obj: Request = None,
):
    """Trigger a job to run immediately."""
    _require_job_owner(job_id, authorization, request_obj)
    try:
        job = run_job_now(job_id)
        return JobResponse(success=True, message="Job triggered for immediate execution", job=job)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/projects/{project_id}/jobs", response_model=JobResponse)
async def api_clear_project_jobs(
    project_id: int,
    authorization: Optional[str] = Header(None),
    request_obj: Request = None,
):
    """Delete all jobs for a project."""
    _require_project_owner(project_id, authorization, request_obj)
    count = clear_jobs(project_id)
    return JobResponse(success=True, message=f"Cleared {count} jobs")


# ============================================================================
# Project State Endpoints (cross-run memory — scheduler + agent projects)
# ============================================================================

class StateUpdateRequest(BaseModel):
    state: Dict[str, Any]

# Hard cap so a buggy executor can't balloon the JSONB row.
_STATE_MAX_BYTES = 64 * 1024


@router.get("/projects/{project_id}/state")
async def api_get_state(
    project_id: int,
    authorization: Optional[str] = Header(None),
    request_obj: Request = None,
):
    """Get the project's persisted run-state (JSONB). Empty dict when never set."""
    _require_project_owner(project_id, authorization, request_obj)
    with get_db() as cur:
        cur.execute("SELECT state FROM scheduler_state WHERE project_id = %s", (project_id,))
        row = cur.fetchone()
    state = _row_value(row, "state", {}) if row else {}
    if isinstance(state, str):
        import json as _json
        try:
            state = _json.loads(state)
        except Exception:
            state = {}
    return {"project_id": project_id, "state": state or {}}


@router.put("/projects/{project_id}/state")
async def api_put_state(
    project_id: int,
    request: StateUpdateRequest,
    authorization: Optional[str] = Header(None),
    request_obj: Request = None,
):
    """Replace the project's persisted run-state (one JSONB row, 64KB cap).

    Executors merge before calling — this is a full replace."""
    _require_project_owner(project_id, authorization, request_obj)
    import json as _json
    encoded = _json.dumps(request.state)
    if len(encoded.encode("utf-8")) > _STATE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="State exceeds 64KB cap")
    with get_db() as cur:
        cur.execute(
            """INSERT INTO scheduler_state (project_id, state, updated_at)
               VALUES (%s, %s::jsonb, NOW())
               ON CONFLICT (project_id) DO UPDATE SET
                 state = EXCLUDED.state, updated_at = NOW()""",
            (project_id, encoded),
        )
        conn = cur._connection
        conn.commit()
    return {"success": True, "project_id": project_id, "bytes": len(encoded)}


# ============================================================================
# Log Endpoints
# ============================================================================

@router.get("/jobs/{job_id}/logs", response_model=LogsResponse)
async def api_get_job_logs(
    job_id: int,
    authorization: Optional[str] = Header(None),
    request_obj: Request = None,
):
    """Get execution logs for a specific job."""
    _require_job_owner(job_id, authorization, request_obj)
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT id, job_id, status, message, created_at
                FROM scheduler_logs
                WHERE job_id = %s
                ORDER BY created_at DESC
                LIMIT 100
            """, (job_id,))
            rows = cur.fetchall()
            logs = [dict(r) if not isinstance(r, dict) else r for r in rows]
            return LogsResponse(success=True, logs=logs, count=len(logs))
    except Exception as e:
        logger.error(f"Failed to get logs for job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/logs", response_model=LogsResponse)
async def api_get_project_logs(
    project_id: int,
    authorization: Optional[str] = Header(None),
    request_obj: Request = None,
):
    """Get all execution logs for a project's jobs."""
    _require_project_owner(project_id, authorization, request_obj)
    try:
        with get_db() as cur:
            cur.execute("""
                SELECT sl.id, sl.job_id, sj.task_type, sj.schedule_value,
                       sl.status, sl.message, sl.created_at
                FROM scheduler_logs sl
                JOIN scheduler_jobs sj ON sj.id = sl.job_id
                WHERE sj.project_id = %s
                ORDER BY sl.created_at DESC
                LIMIT 200
            """, (project_id,))
            rows = cur.fetchall()
            logs = [dict(r) if not isinstance(r, dict) else r for r in rows]
            return LogsResponse(success=True, logs=logs, count=len(logs))
    except Exception as e:
        logger.error(f"Failed to get logs for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
