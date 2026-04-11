#!/usr/bin/env python3
"""
Job Manager - Create, list, and manage scheduler jobs via backend API.

This is the TOOL the LLM uses to manage jobs. It calls the backend
REST API at /api/scheduler/ endpoints.

Usage by AI agents inside executor.py or directly:

    from scheduler import job_manager

    # Create a job
    job_manager.create("interval", "10m", "btc_email", {
        "to": "user@email.com",
        "body": "BTC: {{btc_price}}",
        "fetch": ["btc_price"]
    })

    # List jobs
    job_manager.list_jobs()

    # Get execution logs
    job_manager.get_logs(42)
"""

import os
import requests

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
PROJECT_ID = os.getenv("PROJECT_ID", "1")
TIMEOUT = 10


def _api(method: str, path: str, **kwargs) -> dict:
    """Call the scheduler API."""
    url = f"{BACKEND_URL}/api/scheduler{path}"
    kwargs.setdefault("timeout", TIMEOUT)
    try:
        resp = requests.request(method, url, **kwargs)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        return {"success": False, "error": str(e)}


def create(job_type: str, schedule_value: str, task_type: str, payload: dict = None) -> dict:
    """
    Create a new scheduled job.

    Args:
        job_type: "interval", "daily", or "once"
        schedule_value: "10m", "1h", "2d", "daily:09:00"
        task_type: Free-form name matching executor.py route (e.g., "btc_email")
        payload: Job data (to, subject, body, chat_id, fetch, etc.)

    Returns:
        {"success": true, "job": {...}}
    """
    return _api("POST", f"/projects/{PROJECT_ID}/jobs", json={
        "job_type": job_type,
        "schedule_value": schedule_value,
        "task_type": task_type,
        "payload": payload or {}
    })


def list_jobs() -> dict:
    """List all jobs for this project."""
    return _api("GET", f"/projects/{PROJECT_ID}/jobs")


def get(job_id: int) -> dict:
    """Get a specific job by ID."""
    return _api("GET", f"/jobs/{job_id}")


def update(job_id: int, **kwargs) -> dict:
    """
    Update a job. Allowed fields: schedule_value, payload, status.

    Example:
        update(42, schedule_value="30m")
        update(42, payload={"to": "new@email.com"})
    """
    return _api("PUT", f"/jobs/{job_id}", json=kwargs)


def delete(job_id: int) -> dict:
    """Delete a job."""
    return _api("DELETE", f"/jobs/{job_id}")


def pause(job_id: int) -> dict:
    """Pause an active job."""
    return _api("POST", f"/jobs/{job_id}/pause")


def resume(job_id: int) -> dict:
    """Resume a paused job."""
    return _api("POST", f"/jobs/{job_id}/resume")


def run_now(job_id: int) -> dict:
    """Trigger a job to run immediately (sets next_run = NOW)."""
    return _api("POST", f"/jobs/{job_id}/run")


def get_logs(job_id: int) -> dict:
    """Get execution logs for a specific job."""
    return _api("GET", f"/jobs/{job_id}/logs")


def get_project_logs() -> dict:
    """Get all execution logs for this project."""
    return _api("GET", f"/projects/{PROJECT_ID}/logs")


def clear_all() -> dict:
    """Delete all jobs for this project."""
    return _api("DELETE", f"/projects/{PROJECT_ID}/jobs")
