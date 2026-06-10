#!/usr/bin/env python3
"""
Codex Cron Runner — invoked by system crontab / Task Scheduler every 5 minutes.

Guards:
  1. Lock file prevents concurrent runs
  2. Usage tracker ensures daily 5-hour limit is respected
  3. 20-minute timeout on the maintainer subprocess

Usage:
  python autonomous_developer/codex_cron.py
"""

import logging
import subprocess
import sys
from pathlib import Path

# Setup paths so we can import from our package
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR.parent))  # For codex_code_agent import

from config import (
    LOCK_FILE,
    LOG_FILE,
    CRON_LOG_FILE,
    LOG_FORMAT,
    MAX_SUBPROCESS_TIMEOUT,
)
from codex_usage_tracker import CodexUsageTracker


def main() -> int:
    """Cron entry point."""
    logging.basicConfig(
        filename=str(CRON_LOG_FILE),
        level=logging.INFO,
        format=LOG_FORMAT,
    )
    logger = logging.getLogger("codex_cron")
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(console)

    logger.info("Cron tick — checking guards")

    # Guard 1: Already running?
    if LOCK_FILE.exists():
        # Check if the lock is stale (older than 30 minutes)
        try:
            import time
            lock_age = time.time() - LOCK_FILE.stat().st_mtime
            if lock_age > 1800:  # 30 minutes
                logger.warning("Stale lock file detected (%.0f min old) — removing", lock_age / 60)
                LOCK_FILE.unlink(missing_ok=True)
            else:
                logger.warning("Maintainer already running (lock age: %.0f min) — skipping", lock_age / 60)
                return 0
        except OSError:
            logger.warning("Could not check lock file age — skipping")
            return 0

    # Guard 2: Usage limit check
    tracker = CodexUsageTracker()
    if not tracker.can_proceed():
        remaining = tracker.remaining_hours()
        logger.info(
            "Usage limit reached. Remaining: %.1fh (paused=%s)",
            remaining,
            tracker.state.get("paused", False),
        )
        return 0

    # Spawn maintainer
    maintainer_script = BASE_DIR / "codex_maintainer.py"
    if not maintainer_script.exists():
        logger.error("Maintainer script not found: %s", maintainer_script)
        return 1

    try:
        LOCK_FILE.touch()
        logger.info("Spawning codex_maintainer.py (timeout=%ds)", MAX_SUBPROCESS_TIMEOUT)

        result = subprocess.run(
            [sys.executable, str(maintainer_script)],
            capture_output=True,
            text=True,
            timeout=MAX_SUBPROCESS_TIMEOUT,
            cwd=str(BASE_DIR),
        )

        logger.info("Maintainer exited: code=%d", result.returncode)

        if result.stdout:
            for line in result.stdout.splitlines()[-10:]:
                logger.info("[maintainer stdout] %s", line)

        if result.stderr:
            for line in result.stderr.splitlines()[-10:]:
                logger.error("[maintainer stderr] %s", line)

        return result.returncode

    except subprocess.TimeoutExpired:
        logger.error("Maintainer timed out after %d seconds", MAX_SUBPROCESS_TIMEOUT)
        return 124

    except Exception as exc:
        logger.error("Maintainer failed: %s", exc, exc_info=True)
        return 1

    finally:
        LOCK_FILE.unlink(missing_ok=True)
        logger.info("Cron tick complete")


if __name__ == "__main__":
    sys.exit(main())
