#!/usr/bin/env python3
"""
Schedule Parser - Calculates next run time for jobs.

Supported formats:
  - interval: "5m", "1h", "30s", "2d"
  - daily: "daily:09:00", "daily:14:30"
  - once: returns None after first execution
"""

import re
from datetime import datetime, timedelta
from typing import Optional


def calculate_next_run(job_type: str, schedule_value: str) -> Optional[datetime]:
    """
    Calculate the next run time based on job type and schedule value.

    Args:
        job_type: 'interval', 'daily', or 'once'
        schedule_value: Schedule definition (e.g., "5m", "daily:09:00")

    Returns:
        Next run datetime, or None for one-time jobs after execution
    """
    if job_type == "interval":
        return _parse_interval(schedule_value)
    elif job_type == "daily":
        return _parse_daily(schedule_value)
    elif job_type == "once":
        return None
    else:
        raise ValueError(f"Unknown job_type: {job_type}")


def _parse_interval(value: str) -> datetime:
    """
    Parse interval schedule value.

    Formats: "30s", "5m", "1h", "2d"

    Returns:
        Current time + interval
    """
    match = re.match(r'^(\d+)(s|m|h|d)$', value.strip().lower())
    if not match:
        raise ValueError(f"Invalid interval format: {value}. Use: 30s, 5m, 1h, 2d")

    amount = int(match.group(1))
    unit = match.group(2)

    deltas = {
        's': timedelta(seconds=amount),
        'm': timedelta(minutes=amount),
        'h': timedelta(hours=amount),
        'd': timedelta(days=amount),
    }

    return datetime.utcnow() + deltas[unit]


def _parse_daily(value: str) -> datetime:
    """
    Parse daily schedule value.

    Formats: "daily:09:00", "daily:14:30"

    Returns:
        Next occurrence of the specified time
    """
    match = re.match(r'^daily:(\d{1,2}):(\d{2})$', value.strip().lower())
    if not match:
        raise ValueError(f"Invalid daily format: {value}. Use: daily:09:00")

    hour = int(match.group(1))
    minute = int(match.group(2))

    if hour > 23 or minute > 59:
        raise ValueError(f"Invalid time: {hour}:{minute:02d}")

    now = datetime.utcnow()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # If the time has already passed today, schedule for tomorrow
    if target <= now:
        target += timedelta(days=1)

    return target
