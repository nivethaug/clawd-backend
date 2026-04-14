#!/usr/bin/env python3
"""
Centralized Scheduler Worker - ONE process manages ALL scheduler projects.

Runs as a daemon thread. Polls main DB for due jobs.
Uses ThreadPoolExecutor for parallel execution.
Execution engine loads each project's executor.py dynamically (cached).

The loop NEVER crashes — all errors are caught and logged.
"""

import os
import time
import logging
from concurrent.futures import ThreadPoolExecutor

from services.scheduler.jobs import get_due_jobs, update_job_run
from services.scheduler.parser import calculate_next_run
from services.scheduler.logger import log_job
from services.scheduler.execution_engine import execute_job

logger = logging.getLogger('scheduler.worker')

# Configuration
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "true").lower() == "true"
SCHEDULER_INTERVAL = int(os.getenv("SCHEDULER_INTERVAL", "10"))
MAX_WORKERS = int(os.getenv("SCHEDULER_MAX_WORKERS", "10"))


def _execute_single_job(job: dict):
    """
    Execute one job in a worker thread.
    Never raises — all errors are caught and logged.
    """
    job_id = job['id']
    project_id = job['project_id']
    project_path = job.get('project_path', '')
    task_type = job.get('task_type', 'unknown')

    try:
        result = execute_job(
            project={"id": project_id, "path": project_path},
            job=job
        )

        status = result.get("status", "failed")
        message = result.get("message", "No message")

        # Calculate next run
        next_run = calculate_next_run(job['job_type'], job['schedule_value'])

        # Update job timestamps
        update_job_run(job_id, next_run)

        # Log the execution
        log_job(job_id, status, message)

        logger.info(f"Job {job_id} ({task_type}): {status} - {message}")

    except Exception as e:
        logger.error(f"Job {job_id} execution error: {e}")
        try:
            log_job(job_id, 'failed', str(e))
        except Exception:
            pass


def run_scheduler():
    """
    Main scheduler loop. Runs in a daemon thread.

    Every SCHEDULER_INTERVAL seconds:
    1. Single query: fetch ALL due jobs across ALL projects (JOINs projects for path)
    2. Submit each job to thread pool for parallel execution
    3. Each worker: loads executor (cached) → execute_task → update timestamps → log
    """
    logger.info(f"Scheduler started (interval={SCHEDULER_INTERVAL}s, workers={MAX_WORKERS}, enabled={SCHEDULER_ENABLED})")

    if not SCHEDULER_ENABLED:
        logger.error("SCHEDULER_ENABLED=false — scheduler will NOT run. Set SCHEDULER_ENABLED=true to enable.")
        return

    executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    poll_count = 0

    while SCHEDULER_ENABLED:
        poll_count += 1
        try:
            # Single query for ALL due jobs
            due_jobs = get_due_jobs()

            # Log every 30th poll (~5 min) even when idle, so we know it's alive
            if poll_count % 30 == 0:
                logger.info(f"Scheduler alive (poll #{poll_count}, {len(due_jobs)} due jobs)")

            if due_jobs:
                logger.info(f"Found {len(due_jobs)} due job(s): {[{'id': j['id'], 'type': j['task_type'], 'project': j['project_id']} for j in due_jobs]}")

                # Submit all jobs to thread pool (parallel execution)
                futures = []
                for job in due_jobs:
                    logger.info(f"Submitting job {job['id']} (type={job['task_type']}, project_path={job.get('project_path')})")
                    future = executor.submit(_execute_single_job, job)
                    futures.append(future)

                # Wait for all to complete (with timeout safety)
                for future in futures:
                    try:
                        future.result(timeout=120)  # 2 min max per job
                    except Exception as e:
                        logger.error(f"Job thread error: {e}")

        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")
            import traceback
            logger.error(traceback.format_exc())

        # Wait before next poll
        time.sleep(SCHEDULER_INTERVAL)

    # Cleanup
    executor.shutdown(wait=False)
    logger.info("Scheduler stopped (SCHEDULER_ENABLED=false)")
