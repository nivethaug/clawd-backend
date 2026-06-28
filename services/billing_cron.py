#!/usr/bin/env python3
"""
Billing Cron — Automatic monthly credit reset.

Runs as a daemon thread started at app boot. Checks every hour whether
it's time to reset. Reset day defaults to the 1st of each month (UTC).

This is idempotent — after a successful reset, it won't reset again
until the next month's reset day.

Configuration via billing_config table:
  MONTHLY_RESET_DAY: int (default 1) — day of month to reset
  MONTHLY_RESET_LAST_RUN: ISO date string — last successful run (prevents double-reset)

If billing_config is not available, falls back to reset day = 1.
"""

import os
import time
import logging
import threading
from datetime import datetime, timezone

logger = logging.getLogger("billing.cron")

# Check interval: every 1 hour
CHECK_INTERVAL = int(os.getenv("BILLING_CRON_INTERVAL", "3600"))

# Default reset day if config not set
DEFAULT_RESET_DAY = 1


def _get_reset_day(conn) -> int:
    """Read MONTHLY_RESET_DAY from billing_config (JSONB value)."""
    try:
        row = conn.execute(
            "SELECT value FROM billing_config WHERE key = %s",
            ("MONTHLY_RESET_DAY",),
        ).fetchone()
        if row:
            val = row["value"] if isinstance(row, dict) else dict(row).get("value")
            if isinstance(val, str):
                return int(val.strip('"'))
            return int(val)
    except Exception:
        pass
    return DEFAULT_RESET_DAY


def _get_last_run(conn) -> str | None:
    """Read MONTHLY_RESET_LAST_RUN from billing_config."""
    try:
        row = conn.execute(
            "SELECT value FROM billing_config WHERE key = %s",
            ("MONTHLY_RESET_LAST_RUN",),
        ).fetchone()
        if row:
            val = row["value"] if isinstance(row, dict) else dict(row).get("value")
            if isinstance(val, str):
                return val.strip('"')
            return str(val) if val else None
    except Exception:
        pass
    return None


def _set_last_run(conn, date_str: str):
    """Write MONTHLY_RESET_LAST_RUN to billing_config."""
    import json
    admin_id = 0  # system
    conn.execute(
        """INSERT INTO billing_config (key, value, updated_by, updated_at)
           VALUES (%s, %s::jsonb, %s, NOW())
           ON CONFLICT (key) DO UPDATE SET
             value = EXCLUDED.value,
             updated_by = EXCLUDED.updated_by,
             updated_at = NOW()""",
        ("MONTHLY_RESET_LAST_RUN", json.dumps(date_str), admin_id),
    )


def _should_reset(conn, now: datetime) -> bool:
    """Check if today is reset day AND we haven't already reset this month."""
    reset_day = _get_reset_day(conn)
    today = now.day

    if today != reset_day:
        return False

    # Check last run — if it was this month already, skip
    last_run = _get_last_run(conn)
    if last_run:
        try:
            last = datetime.fromisoformat(last_run)
            if last.year == now.year and last.month == now.month:
                return False  # Already ran this month
        except (ValueError, TypeError):
            pass  # Corrupt value — proceed with reset

    return True


def _run_reset():
    """Execute the monthly reset. Returns count of rows reset."""
    from database_postgres import get_db
    from services.billing_service import reset_monthly_credits

    now = datetime.now(timezone.utc)
    with get_db() as conn:
        if not _should_reset(conn, now):
            return 0

        logger.info(f"[BILLING_CRON] Starting monthly credit reset at {now.isoformat()}")
        count = reset_monthly_credits(conn)
        _set_last_run(conn, now.date().isoformat())
        conn.commit()

        logger.info(f"[BILLING_CRON] Monthly reset complete: {count} balance rows reset")
        return count


def _cron_loop():
    """Main loop — runs forever in daemon thread."""
    logger.info(f"[BILLING_CRON] Started (check every {CHECK_INTERVAL}s)")

    # Initial small delay to let app fully boot
    time.sleep(30)

    while True:
        try:
            _run_reset()
        except Exception as e:
            logger.error(f"[BILLING_CRON] Error during reset check: {e}", exc_info=True)

        time.sleep(CHECK_INTERVAL)


_started = False
_lock = threading.Lock()


def start_billing_cron():
    """Start the billing cron daemon thread (idempotent — only starts once)."""
    global _started
    with _lock:
        if _started:
            return
        _started = True

    thread = threading.Thread(target=_cron_loop, daemon=True, name="billing-cron")
    thread.start()
    logger.info("[BILLING_CRON] Daemon thread launched")
