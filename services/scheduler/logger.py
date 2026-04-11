#!/usr/bin/env python3
"""
Scheduler Logger - Logs job execution results to scheduler_logs table.
Uses main dreampilot database via database_postgres.
"""

import logging
from database_postgres import get_db

logger = logging.getLogger('scheduler.logger')


def log_job(job_id: int, status: str, message: str):
    """
    Log a job execution result.

    Args:
        job_id: ID of the job
        status: 'success' or 'failed'
        message: Result message or error details
    """
    try:
        with get_db() as cur:
            cur.execute("""
                INSERT INTO scheduler_logs (job_id, status, message)
                VALUES (%s, %s, %s)
            """, (job_id, status, message[:1000] if message else ''))
            cur._connection.commit()
    except Exception as e:
        logger.error(f"Failed to log job {job_id}: {e}")
