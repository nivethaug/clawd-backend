#!/usr/bin/env python3
"""
Centralized Scheduler Worker - ONE process manages ALL scheduler projects.

Runs as a daemon thread. Polls main DB for due jobs.
Uses ThreadPoolExecutor for parallel execution.
Execution engine loads each project's executor.py dynamically (cached).

The loop NEVER crashes — all errors are caught and logged.
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# Configure logging for standalone daemon process
# (When run as PM2 process, no other logging config exists)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s:%(name)s:%(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)

from services.scheduler.jobs import get_due_jobs, update_job_run, claim_job
from services.scheduler.parser import calculate_next_run
from services.scheduler.logger import log_job
from services.scheduler.execution_engine import execute_job, JOB_TIMEOUT_SECONDS

logger = logging.getLogger('scheduler.worker')

# Configuration
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "true").lower() == "true"
SCHEDULER_INTERVAL = int(os.getenv("SCHEDULER_INTERVAL", "10"))
MAX_WORKERS = int(os.getenv("SCHEDULER_MAX_WORKERS", "10"))

# Per-job wait timeout on the future. In sandbox mode the subprocess itself
# enforces JOB_TIMEOUT_SECONDS (it SIGKILLs bwrap on timeout). We add a 30s
# buffer here so future.result() doesn't fire before subprocess.run() has
# had time to clean up the bwrap process + emit its result line.
FUTURE_WAIT_TIMEOUT = JOB_TIMEOUT_SECONDS + 30


def _store_sync_result(correlation_id: str, status: str, result: dict):
    """Store result for sync webhook response polling."""
    try:
        from database_postgres import get_db
        with get_db() as conn:
            conn.execute(
                "INSERT INTO scheduler_sync_results (correlation_id, status, result) "
                "VALUES (%s, %s, %s)",
                (correlation_id, status, json.dumps(result, default=str)[:16000]))
            conn.commit()
    except Exception as e:
        logger.warning(f"sync result store error: {e}")


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
        # Poll-race guard: atomically claim the firing. If another poll
        # thread (or a second daemon) already claimed it, skip — without
        # this, a run lasting longer than SCHEDULER_INTERVAL gets picked
        # up again mid-execution and double-fires.
        if not claim_job(job_id):
            logger.info(f"Job {job_id} already claimed by another worker — skipping")
            return

        result = execute_job(
            project={"id": project_id, "path": project_path},
            job=job
        )

        status = result.get("status", "failed")
        message = result.get("message", "No message")

        # ── Retry logic ──
        if status == "failed":
            max_retries = job.get("max_retries", 0)
            retry_count = job.get("retry_count", 0)
            if max_retries > retry_count:
                backoff = job.get("retry_backoff_seconds", 60)
                next_run = datetime.utcnow() + timedelta(
                    seconds=backoff * (retry_count + 1))
                update_job_run(job_id, next_run,
                               retry_count=retry_count + 1)
                log_job(job_id, "retrying",
                        f"retry {retry_count + 1}/{max_retries}: {message[:200]}")
                logger.info(f"Job {job_id} retrying ({retry_count + 1}/{max_retries}) "
                            f"in {backoff * (retry_count + 1)}s")
                return

        # ── On-failure hook ──
        if status == "failed" and job.get("on_failure_job_id"):
            on_fail_id = job["on_failure_job_id"]
            try:
                from services.scheduler.jobs import run_job_now
                run_job_now(on_fail_id)
                logger.info(f"Job {job_id} failed → triggered on-failure job {on_fail_id}")
            except Exception as hook_err:
                logger.warning(f"Job {job_id} on-failure hook {on_fail_id} error: {hook_err}")

        # ── Sub-workflow chaining ──
        payload = job.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        if status != "failed" and isinstance(payload, dict) and payload.get("on_complete_job_id"):
            chain_id = payload["on_complete_job_id"]
            try:
                from services.scheduler.jobs import run_job_now
                run_job_now(chain_id)
                logger.info(f"Job {job_id} completed → chained job {chain_id}")
            except Exception as chain_err:
                logger.warning(f"Job {job_id} chain to {chain_id} error: {chain_err}")

        # ── Sync webhook response store ──
        correlation_id = None
        if isinstance(payload, dict):
            correlation_id = payload.get("_correlation_id")
        if correlation_id:
            _store_sync_result(correlation_id, status, result)

        # Calculate next run
        next_run = calculate_next_run(
            job['job_type'], job['schedule_value'],
            timezone=job.get('timezone'))

        # Reset retry count on success
        updates = {}
        if status != "failed" and job.get("retry_count", 0) > 0:
            updates["retry_count"] = 0

        # Update job timestamps
        update_job_run(job_id, next_run, **updates)

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

                # Wait for all to complete (with timeout safety).
                # In sandbox mode the subprocess.run(timeout=JOB_TIMEOUT_SECONDS)
                # is the real kill switch — this future timeout is just a safety
                # net for the rare case where subprocess cleanup itself hangs.
                for future in futures:
                    try:
                        future.result(timeout=FUTURE_WAIT_TIMEOUT)
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
