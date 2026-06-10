"""
Codex Usage Tracker — Monitors Codex API usage to enforce daily limits.

State is persisted to a JSON file. The tracker:
  - Records session start/end times
  - Accumulates total seconds used
  - Pauses when the daily limit is reached
  - Resumes after the 24-hour reset window
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from config import (
    STATE_FILE,
    USAGE_LIMIT_SECONDS,
    USAGE_LIMIT_HOURS,
    RESET_INTERVAL_HOURS,
)

logger = logging.getLogger("codex_usage_tracker")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _default_state() -> Dict[str, Any]:
    return {
        "total_seconds_used": 0,
        "limit_seconds": USAGE_LIMIT_SECONDS,
        "limit_hours": USAGE_LIMIT_HOURS,
        "current_run_start": None,
        "paused": False,
        "last_reset": _utcnow().isoformat(),
        "reset_interval_hours": RESET_INTERVAL_HOURS,
    }


class CodexUsageTracker:
    """Track and enforce Codex API usage limits."""

    def __init__(self, state_file: Optional[Path] = None):
        self.state_file = Path(state_file or STATE_FILE)
        self.state = self._load_state()

    # ── Persistence ────────────────────────────────────

    def _load_state(self) -> Dict[str, Any]:
        """Load state from JSON, creating defaults if missing."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Ensure all expected keys exist (forward compat)
                defaults = _default_state()
                for key in defaults:
                    if key not in data:
                        data[key] = defaults[key]
                return data
            except (json.JSONDecodeError, IOError) as exc:
                logger.warning("State file corrupt, resetting: %s", exc)
        return _default_state()

    def _save_state(self) -> None:
        """Persist current state to JSON."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2)
        logger.debug("State saved to %s", self.state_file)

    # ── Core Logic ─────────────────────────────────────

    def can_proceed(self) -> bool:
        """Check if usage is within limits. Auto-resets if window passed."""
        if self.state["paused"]:
            if self._reset_window_passed():
                logger.info("Reset window passed — clearing usage counter")
                self._reset_usage()
                return True
            return False
        return self.state["total_seconds_used"] < self.state["limit_seconds"]

    def record_start(self) -> None:
        """Mark the beginning of a Codex session."""
        self.state["current_run_start"] = _utcnow().isoformat()
        self._save_state()
        logger.info("Codex session started")

    def record_end(self) -> None:
        """Record elapsed seconds and clear the run start timestamp."""
        start_iso = self.state.get("current_run_start")
        if not start_iso:
            logger.warning("record_end() called without active session")
            return

        start_time = datetime.fromisoformat(start_iso)
        elapsed = (_utcnow() - start_time).total_seconds()
        self.state["total_seconds_used"] += elapsed
        self.state["current_run_start"] = None

        if self.state["total_seconds_used"] >= self.state["limit_seconds"]:
            self.state["paused"] = True
            logger.warning(
                "Usage limit reached: %.0f / %d seconds — pausing",
                self.state["total_seconds_used"],
                self.state["limit_seconds"],
            )

        self._save_state()
        logger.info("Codex session ended: +%.0fs (total: %.0fs)", elapsed, self.state["total_seconds_used"])

    def _reset_window_passed(self) -> bool:
        """Check if the 24-hour reset window has elapsed."""
        last_reset_str = self.state.get("last_reset")
        if not last_reset_str:
            return True
        last_reset = datetime.fromisoformat(last_reset_str)
        elapsed_hours = (_utcnow() - last_reset).total_seconds() / 3600
        return elapsed_hours >= self.state["reset_interval_hours"]

    def _reset_usage(self) -> None:
        """Reset usage counter after the reset window."""
        self.state["total_seconds_used"] = 0
        self.state["paused"] = False
        self.state["last_reset"] = _utcnow().isoformat()
        self._save_state()

    # ── Read-only helpers ──────────────────────────────

    def remaining_seconds(self) -> float:
        """Return remaining seconds before the limit."""
        remaining = self.state["limit_seconds"] - self.state["total_seconds_used"]
        return max(0.0, remaining)

    def remaining_hours(self) -> float:
        """Return remaining hours before the limit."""
        return self.remaining_seconds() / 3600

    def usage_summary(self) -> Dict[str, Any]:
        """Return a summary dict for logging / display."""
        return {
            "used_hours": round(self.state["total_seconds_used"] / 3600, 2),
            "limit_hours": self.state["limit_hours"],
            "remaining_hours": round(self.remaining_hours(), 2),
            "paused": self.state["paused"],
            "last_reset": self.state.get("last_reset"),
        }
