#!/usr/bin/env python3
"""
Scheduler Job API Router - REST endpoints for job management.

LLM agents call these endpoints to create, list, update, and manage
scheduler jobs. Jobs are stored in the main dreampilot DB.

Prefix: /api/scheduler
"""

import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException
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

logger = logging.getLogger('api.scheduler')

router = APIRouter()


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
async def api_create_job(project_id: int, request: JobCreateRequest):
    """Create a new scheduled job for a project."""
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
async def api_list_jobs(project_id: int):
    """List all jobs for a project."""
    try:
        jobs = list_jobs(project_id)
        return JobResponse(success=True, jobs=jobs, count=len(jobs))
    except Exception as e:
        logger.error(f"Failed to list jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def api_get_job(job_id: int):
    """Get a specific job by ID."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse(success=True, job=job)


@router.put("/jobs/{job_id}", response_model=JobResponse)
async def api_update_job(job_id: int, request: JobUpdateRequest):
    """Update a job's schedule, payload, or status."""
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
async def api_delete_job(job_id: int):
    """Delete a job and its execution logs."""
    deleted = delete_job(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse(success=True, message="Job deleted")


@router.post("/jobs/{job_id}/pause", response_model=JobResponse)
async def api_pause_job(job_id: int):
    """Pause an active job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.get('status') != 'active':
        raise HTTPException(status_code=400, detail=f"Job is {job.get('status')}, not active")
    pause_job(job_id)
    return JobResponse(success=True, message="Job paused")


@router.post("/jobs/{job_id}/resume", response_model=JobResponse)
async def api_resume_job(job_id: int):
    """Resume a paused job."""
    try:
        resume_job(job_id)
        return JobResponse(success=True, message="Job resumed")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/jobs/{job_id}/run", response_model=JobResponse)
async def api_run_job_now(job_id: int):
    """Trigger a job to run immediately."""
    try:
        job = run_job_now(job_id)
        return JobResponse(success=True, message="Job triggered for immediate execution", job=job)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/projects/{project_id}/jobs", response_model=JobResponse)
async def api_clear_project_jobs(project_id: int):
    """Delete all jobs for a project."""
    count = clear_jobs(project_id)
    return JobResponse(success=True, message=f"Cleared {count} jobs")


# ============================================================================
# Log Endpoints
# ============================================================================

@router.get("/jobs/{job_id}/logs", response_model=LogsResponse)
async def api_get_job_logs(job_id: int):
    """Get execution logs for a specific job."""
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
async def api_get_project_logs(project_id: int):
    """Get all execution logs for a project's jobs."""
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
