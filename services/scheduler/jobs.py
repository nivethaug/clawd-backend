#!/usr/bin/env python3
"""
Job Service - Centralized CRUD for scheduler jobs in main DB.

ALL job operations go through this module.
Templates and AI agents use these functions — NOT direct SQL.

Uses database_postgres.get_db() for thread-safe pooled connections.
"""

import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from database_postgres import get_db
from services.scheduler.parser import calculate_next_run

logger = logging.getLogger('scheduler.jobs')

# Limits
MAX_JOBS_PER_PROJECT = 100

# Valid job types (schedule types). task_type is free-form — executor validates.
VALID_JOB_TYPES = ('interval', 'daily', 'once')


def create_job(project_id: int, job_data: dict) -> dict:
    """
    Create a new scheduled job.

    Args:
        project_id: Project ID (FK to projects table)
        job_data: {
            "job_type": "interval"|"daily"|"once",
            "schedule_value": "10m"|"daily:09:00",
            "task_type": "telegram"|"btc_email"|"weather_alert"|... (free-form),
            "payload": {"chat_id": "123", "text": "...", "fetch": ["btc_price"]}
        }

    Returns:
        Created job dict

    Raises:
        ValueError: Invalid input
        RuntimeError: Project at job limit
    """
    job_type = job_data.get('job_type', '')
    schedule_value = job_data.get('schedule_value', '')
    task_type = job_data.get('task_type', '')
    payload = job_data.get('payload', {})

    # Validate required fields
    if job_type not in VALID_JOB_TYPES:
        raise ValueError(f"Invalid job_type: {job_type}. Must be: {VALID_JOB_TYPES}")
    if not schedule_value:
        raise ValueError("schedule_value is required")
    if not task_type:
        raise ValueError("task_type is required")

    # Validate payload is JSON-safe
    try:
        json.dumps(payload)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Payload must be JSON-serializable: {e}")

    # Enforce job limit
    current_count = _count_project_jobs(project_id)
    if current_count >= MAX_JOBS_PER_PROJECT:
        raise RuntimeError(
            f"Project {project_id} has {current_count} jobs (max {MAX_JOBS_PER_PROJECT})"
        )

    # Compute first next_run
    next_run = calculate_next_run(job_type, schedule_value)
    payload_json = json.dumps(payload)

    with get_db() as cur:
        cur.execute("""
            INSERT INTO scheduler_jobs
                (project_id, job_type, schedule_value, task_type, payload, next_run, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'active')
            RETURNING id, project_id, job_type, schedule_value, task_type,
                      payload, last_run, next_run, status, created_at
        """, (project_id, job_type, schedule_value, task_type, payload_json, next_run))
        conn = cur._connection
        conn.commit()
        job = cur.fetchone()
        logger.info(f"Job created: id={job['id']} project={project_id} "
                     f"type={job_type}/{task_type} next_run={next_run}")
        return dict(job) if not isinstance(job, dict) else job


def update_job(job_id: int, updates: dict) -> dict:
    """
    Update a job's schedule_value, payload, or status.
    Recalculates next_run if schedule_value changes.

    Args:
        job_id: Job ID
        updates: Dict with optional keys: schedule_value, payload, status

    Returns:
        Updated job dict
    """
    allowed_fields = {'schedule_value', 'payload', 'status'}
    filtered = {k: v for k, v in updates.items() if k in allowed_fields}

    if not filtered:
        raise ValueError("No valid fields to update")

    # If schedule_value changed, recalculate next_run
    if 'schedule_value' in filtered and 'status' not in filtered:
        job = get_job(job_id)
        if job:
            next_run = calculate_next_run(job['job_type'], filtered['schedule_value'])
            filtered['next_run'] = next_run

    if 'payload' in filtered:
        filtered['payload'] = json.dumps(filtered['payload'])

    set_clauses = [f"{k} = %s" for k in filtered]
    values = list(filtered.values()) + [job_id]

    with get_db() as cur:
        cur.execute(f"""
            UPDATE scheduler_jobs SET {', '.join(set_clauses)}
            WHERE id = %s
            RETURNING id, project_id, job_type, schedule_value, task_type,
                      payload, last_run, next_run, status, created_at
        """, values)
        conn = cur._connection
        conn.commit()
        job = cur.fetchone()
        if not job:
            raise ValueError(f"Job {job_id} not found")
        logger.info(f"Job {job_id} updated: {list(filtered.keys())}")
        return dict(job) if not isinstance(job, dict) else job


def delete_job(job_id: int) -> bool:
    """
    Delete a job. Returns True if deleted, False if not found.
    Cascades to scheduler_logs.
    """
    with get_db() as cur:
        cur.execute("DELETE FROM scheduler_jobs WHERE id = %s", (job_id,))
        conn = cur._connection
        conn.commit()
        deleted = cur._cursor.rowcount > 0
        if deleted:
            logger.info(f"Job {job_id} deleted")
        return deleted


def list_jobs(project_id: int) -> list:
    """
    List all jobs for a project, sorted by next_run.
    """
    with get_db() as cur:
        cur.execute("""
            SELECT id, project_id, job_type, schedule_value, task_type,
                   payload, last_run, next_run, status, created_at
            FROM scheduler_jobs
            WHERE project_id = %s
            ORDER BY next_run ASC NULLS LAST, created_at DESC
        """, (project_id,))
        rows = cur.fetchall()
        return [dict(r) if not isinstance(r, dict) else r for r in rows]


def get_job(job_id: int) -> Optional[dict]:
    """Get a single job by ID."""
    with get_db() as cur:
        cur.execute("""
            SELECT id, project_id, job_type, schedule_value, task_type,
                   payload, last_run, next_run, status, created_at
            FROM scheduler_jobs WHERE id = %s
        """, (job_id,))
        row = cur.fetchone()
        return dict(row) if row and not isinstance(row, dict) else row


def get_due_jobs() -> List[Dict]:
    """
    Fetch ALL due jobs across ALL scheduler projects.
    JOINs projects table to get project_path for execution_engine.

    Single query — the core of the centralized scheduler.

    Returns:
        List of job dicts with project_path and project_name added
    """
    with get_db() as cur:
        cur.execute("""
            SELECT j.id, j.project_id, j.job_type, j.schedule_value,
                   j.task_type, j.payload, j.last_run, j.next_run,
                   j.status, j.created_at,
                   p.project_path, p.name as project_name
            FROM scheduler_jobs j
            JOIN projects p ON p.id = j.project_id
            WHERE j.status = 'active'
              AND j.next_run <= NOW()
              AND p.type_id = 5
            ORDER BY j.next_run ASC
        """)
        rows = cur.fetchall()
        return [dict(r) if not isinstance(r, dict) else r for r in rows]


def update_job_run(job_id: int, next_run: Optional[datetime]):
    """
    Update job after execution: set last_run and next_run.
    For one-time jobs (next_run=None), mark as completed.
    """
    with get_db() as cur:
        if next_run is None:
            cur.execute("""
                UPDATE scheduler_jobs
                SET last_run = NOW(), next_run = NULL, status = 'completed'
                WHERE id = %s
            """, (job_id,))
        else:
            cur.execute("""
                UPDATE scheduler_jobs
                SET last_run = NOW(), next_run = %s
                WHERE id = %s
            """, (next_run, job_id))
        conn = cur._connection
        conn.commit()


def pause_job(job_id: int):
    """Pause an active job."""
    with get_db() as cur:
        cur.execute("UPDATE scheduler_jobs SET status = 'paused' WHERE id = %s", (job_id,))
        conn = cur._connection
        conn.commit()


def resume_job(job_id: int):
    """Resume a paused job by recalculating next_run."""
    job = get_job(job_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    next_run = calculate_next_run(job['job_type'], job['schedule_value'])

    with get_db() as cur:
        cur.execute("""
            UPDATE scheduler_jobs SET status = 'active', next_run = %s
            WHERE id = %s
        """, (next_run, job_id))
        conn = cur._connection
        conn.commit()


def run_job_now(job_id: int) -> dict:
    """
    Trigger a job to run immediately.
    Sets next_run = NOW() so the next scheduler poll picks it up.
    """
    with get_db() as cur:
        cur.execute("""
            UPDATE scheduler_jobs
            SET next_run = NOW(), status = 'active'
            WHERE id = %s
            RETURNING id, project_id, job_type, schedule_value, task_type,
                      payload, last_run, next_run, status, created_at
        """, (job_id,))
        conn = cur._connection
        conn.commit()
        job = cur.fetchone()
        if not job:
            raise ValueError(f"Job {job_id} not found")
        logger.info(f"Job {job_id} triggered for immediate execution")
        return dict(job) if not isinstance(job, dict) else job


def clear_jobs(project_id: int = None) -> int:
    """
    Delete jobs and their logs. If project_id given, only that project's jobs.
    Also clears the executor cache for the project.
    Returns number of deleted jobs.
    """
    with get_db() as cur:
        if project_id:
            # Delete logs first (explicit, even though CASCADE exists)
            cur.execute("""
                DELETE FROM scheduler_logs
                WHERE job_id IN (SELECT id FROM scheduler_jobs WHERE project_id = %s)
            """, (project_id,))
            cur.execute("DELETE FROM scheduler_jobs WHERE project_id = %s", (project_id,))
            logger.info(f"Cleared all jobs and logs for project {project_id}")
        else:
            cur.execute("DELETE FROM scheduler_logs")
            cur.execute("DELETE FROM scheduler_jobs")
            logger.info("Cleared ALL scheduler jobs and logs")
        count = cur._cursor.rowcount
        conn = cur._connection
        conn.commit()

    # Clear executor cache so the deleted project's module is unloaded
    try:
        from services.scheduler.execution_engine import clear_cache
        if project_id:
            clear_cache(project_id)
        else:
            clear_cache()
    except Exception as e:
        logger.warning(f"Failed to clear executor cache: {e}")

    return count


def _count_project_jobs(project_id: int) -> int:
    """Count active/paused jobs for a project."""
    with get_db() as cur:
        cur.execute("""
            SELECT COUNT(*) as cnt FROM scheduler_jobs
            WHERE project_id = %s AND status IN ('active', 'paused')
        """, (project_id,))
        row = cur.fetchone()
        return row['cnt'] if isinstance(row, dict) else row[0]
