#!/usr/bin/env python3
"""
Scheduler Service - Centralized job management for ALL scheduler projects.

Templates and AI agents import from here:
    from services.scheduler import create_job, list_jobs, delete_job

DO NOT access DB directly. Use these functions.
"""

from services.scheduler.jobs import (
    create_job,
    update_job,
    delete_job,
    list_jobs,
    get_job,
    get_due_jobs,
    update_job_run,
    pause_job,
    resume_job,
    run_job_now,
    clear_jobs,
)

from services.scheduler.scheduler import run_scheduler

__all__ = [
    'create_job',
    'update_job',
    'delete_job',
    'list_jobs',
    'get_job',
    'get_due_jobs',
    'update_job_run',
    'pause_job',
    'resume_job',
    'run_job_now',
    'clear_jobs',
    'run_scheduler',
]
