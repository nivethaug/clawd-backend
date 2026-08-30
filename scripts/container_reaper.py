#!/usr/bin/env python3
"""
Idle container reaper — PM2-managed loop that stops containers idle > threshold.

Run via PM2:
    pm2 start scripts/container_reaper.py \\
        --name container-reaper \\
        --interpreter /root/clawd-backend/venv/bin/python3.12
    pm2 save

The loop wakes every 60s and calls ContainerManager.cleanup_idle(). Each call:
  1. Queries user_containers for rows with status='running' AND
     last_used_at < NOW() - IDLE_TIMEOUT.
  2. Issues `docker stop` for each.
  3. Updates status to 'stopped' in the DB.

A stopped container's filesystem + state survive (docker stop, not rm). The
next time that user does anything, ContainerManager.ensure_container() will
`docker start` it in ~1-2s.

Logs go to PM2 logs (search for [REAPER]). Exits cleanly on SIGTERM/SIGINT
(so `pm2 stop` / `pm2 restart` work without orphans).
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time

# Make the repo importable when run as a standalone script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database_adapter import get_db
from services.container_manager import ContainerManager, CONTAINER_IDLE_TIMEOUT_SECONDS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [REAPER] %(levelname)s %(message)s",
)
logger = logging.getLogger("container_reaper")

# How often to scan (seconds). Env-overridable.
POLL_INTERVAL_SECONDS = int(os.getenv("CONTAINER_REAPER_POLL_SECONDS", "60"))

# Graceful shutdown flag.
_running = True


def _handle_signal(signum, _frame):
    global _running
    logger.info("received signal %d — shutting down after current scan", signum)
    _running = False


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


def check_workspace_quotas() -> int:
    """Layer 2 stopgap: soft disk quota per workspace.

    The hard limit is XFS pquota + --storage-opt (see
    services/sandbox/egress.py docstring); until the worker's volume is
    reformatted XFS, this poll catches the honest majority: over-limit
    workspaces get their container STOPPED and the DB status flags the
    breach, so the project fails visibly instead of filling the disk.
    """
    limit_gb = (os.getenv("PROJECT_DISK_LIMIT_GB") or "").strip()
    if not limit_gb:
        return 0
    try:
        limit_bytes = int(limit_gb) * 1024 ** 3
    except ValueError:
        return 0
    with get_db() as conn:
        rows = conn.execute(
            "SELECT container_name, workspace_path FROM user_containers "
            "WHERE status = 'running'"
        ).fetchall()
    stopped = 0
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        ws = d.get("workspace_path")
        name = d.get("container_name")
        if not ws or not os.path.isdir(ws):
            continue
        try:
            usage = subprocess.run(
                ["du", "-sb", ws], capture_output=True, text=True, timeout=60
            ).stdout.split()[0]
        except Exception:
            continue
        if int(usage) > limit_bytes:
            logger.warning(
                "[QUOTA] %s over limit: %.2f GB > %s GB — stopping container",
                name, int(usage) / 1024 ** 3, limit_gb)
            subprocess.run(["docker", "stop", name], capture_output=True, timeout=60)
            with get_db() as conn:
                conn.execute(
                    "UPDATE user_containers SET status = 'disk_quota_exceeded' "
                    "WHERE container_name = ?", (name,))
                conn.commit()
            stopped += 1
    return stopped


def main() -> int:
    logger.info(
        "container reaper starting (poll=%ss, idle_timeout=%ss)",
        POLL_INTERVAL_SECONDS,
        CONTAINER_IDLE_TIMEOUT_SECONDS,
    )

    while _running:
        try:
            stopped = ContainerManager.cleanup_idle(idle_timeout_seconds=CONTAINER_IDLE_TIMEOUT_SECONDS)
            if stopped > 0:
                logger.info("stopped %d idle container(s)", stopped)
        except Exception as exc:
            # Don't let one bad scan kill the loop.
            logger.error("scan failed: %s", exc, exc_info=True)

        try:
            quota_stopped = check_workspace_quotas()
            if quota_stopped:
                logger.info("stopped %d container(s) over disk quota", quota_stopped)
        except Exception as exc:
            logger.error("quota scan failed: %s", exc, exc_info=True)

        # Sleep in short increments so SIGTERM is responsive.
        sleep_remaining = POLL_INTERVAL_SECONDS
        while sleep_remaining > 0 and _running:
            time.sleep(min(5, sleep_remaining))
            sleep_remaining -= 5

    logger.info("container reaper exiting cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
