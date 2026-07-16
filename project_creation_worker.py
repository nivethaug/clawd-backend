"""
Durable project creation worker.

Run this as a separate PM2 process. It claims queued project creation runs,
executes the scaffold/build/publish pipeline, and records completion in the DB
so API restarts do not strand projects in the creating state.
"""

import logging
import os
import signal
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env.postgres")
load_dotenv()

from database_postgres import init_schema
from services.sentry_config import capture_exception, configure_sentry, scoped_context
from services.project_creation_runs import claim_next_run, execute_run, recover_stale_runs, worker_id

logging.basicConfig(
    level=os.getenv("PROJECT_CREATION_WORKER_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s:%(name)s:%(message)s",
)
logger = logging.getLogger("project_creation_worker")
configure_sentry("project-creation-worker")

# Startup diagnostic: confirm env vars are reaching the worker process and
# whether Sentry actually enabled. Logs PRESENCE only, never values.
try:
    from services.sentry_config import is_enabled as _sentry_is_enabled
    if _sentry_is_enabled():
        logger.info("[STARTUP-ENV] Sentry ENABLED for project-creation-worker")
    else:
        _dsn = os.getenv("SENTRY_DSN", "")
        _why = ("INVALID (expected https://<key>@o<org>.ingest.sentry.io/<project>)"
                if _dsn else "missing from env")
        logger.warning("[STARTUP-ENV] Sentry DISABLED for project-creation-worker — SENTRY_DSN %s", _why)
except Exception as _e:
    logger.warning("[STARTUP-ENV] diagnostic failed: %s", _e)

POLL_SECONDS = float(os.getenv("PROJECT_CREATION_WORKER_POLL_SECONDS", "2"))
STALE_AFTER_MINUTES = int(os.getenv("PROJECT_CREATION_RUN_STALE_MINUTES", "20"))

_stop = False


def _request_stop(*_args):
    global _stop
    _stop = True
    logger.info("[PROJECT-WORKER] stop requested")


def main() -> None:
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    init_schema()
    wid = worker_id()
    logger.info("[PROJECT-WORKER] started worker_id=%s", wid)
    recover_stale_runs(STALE_AFTER_MINUTES)

    while not _stop:
        try:
            run = claim_next_run(wid)
            if not run:
                time.sleep(POLL_SECONDS)
                continue

            run_id = int(run["id"])
            logger.info("[PROJECT-WORKER] claimed run=%s project=%s type=%s", run_id, run.get("project_id"), run.get("type_id"))
            with scoped_context(
                tags={
                    "service": "project-creation-worker",
                    "run_id": run_id,
                    "project_id": run.get("project_id"),
                    "type_id": run.get("type_id"),
                }
            ):
                execute_run(run_id)
        except Exception as e:
            logger.error("[PROJECT-WORKER] loop error: %s", e, exc_info=True)
            capture_exception(e, tags={"service": "project-creation-worker", "worker_id": wid})
            time.sleep(POLL_SECONDS)

    logger.info("[PROJECT-WORKER] stopped")


if __name__ == "__main__":
    main()
