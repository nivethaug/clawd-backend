"""
Durable Claude session chat worker.

Run this as a separate PM2 process from the FastAPI backend. It claims queued
session chat runs, executes Claude, persists streamed chunks/results, and keeps
running even when the API process restarts.
"""

import asyncio
import logging
import os
import signal

from database_postgres import init_schema
from services.session_chat_runs import claim_next_run, execute_run, recover_stale_runs, worker_id

logging.basicConfig(
    level=os.getenv("SESSION_CHAT_WORKER_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s:%(name)s:%(message)s",
)
logger = logging.getLogger("session_chat_worker")

POLL_SECONDS = float(os.getenv("SESSION_CHAT_WORKER_POLL_SECONDS", "2"))
STALE_AFTER_MINUTES = int(os.getenv("SESSION_CHAT_RUN_STALE_MINUTES", "20"))

_stop = False


def _request_stop(*_args):
    global _stop
    _stop = True
    logger.info("[SESSION-WORKER] stop requested")


async def main() -> None:
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    init_schema()
    wid = worker_id()
    logger.info("[SESSION-WORKER] started worker_id=%s", wid)
    recover_stale_runs(STALE_AFTER_MINUTES)

    while not _stop:
        try:
            run = claim_next_run(wid)
            if not run:
                await asyncio.sleep(POLL_SECONDS)
                continue

            run_id = int(run["id"])
            logger.info("[SESSION-WORKER] claimed run=%s session=%s channel=%s", run_id, run.get("session_id"), run.get("channel"))
            await execute_run(run_id)
        except Exception as e:
            logger.error("[SESSION-WORKER] loop error: %s", e, exc_info=True)
            await asyncio.sleep(POLL_SECONDS)

    logger.info("[SESSION-WORKER] stopped")


if __name__ == "__main__":
    asyncio.run(main())
