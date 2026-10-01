#!/usr/bin/env python3
"""
Schedule Parser - Calculates next run time for jobs.

Supported formats:
  - interval: "5m", "1h", "30s", "2d"
  - daily: "daily:09:00", "daily:14:30"
  - weekly: "weekly:mon:09:00", "weekly:fri:17:30"
  - monthly: "monthly:1:09:00", "monthly:15:14:30"
  - once: returns None after first execution
  - event: returns None (webhook-triggered)

All parsers accept an optional timezone (IANA name, e.g. "Asia/Kolkata").
"""

import re
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

DAYS = {'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6}


def _now(tz: Optional[str] = None) -> datetime:
    if tz:
        return datetime.now(ZoneInfo(tz)).replace(tzinfo=None)
    return datetime.utcnow()


def calculate_next_run(job_type: str, schedule_value: str,
                       timezone: Optional[str] = None) -> Optional[datetime]:
    if job_type == "interval":
        return _parse_interval(schedule_value)
    elif job_type == "daily":
        return _parse_daily(schedule_value, timezone)
    elif job_type == "weekly":
        return _parse_weekly(schedule_value, timezone)
    elif job_type == "monthly":
        return _parse_monthly(schedule_value, timezone)
    elif job_type == "once":
        return None
    elif job_type == "event":
        return None
    else:
        raise ValueError(f"Unknown job_type: {job_type}")


def _parse_interval(value: str) -> datetime:
    match = re.match(r'^(\d+)(s|m|h|d)$', value.strip().lower())
    if not match:
        raise ValueError(f"Invalid interval format: {value}. Use: 30s, 5m, 1h, 2d")
    amount = int(match.group(1))
    unit = match.group(2)
    deltas = {'s': timedelta(seconds=amount), 'm': timedelta(minutes=amount),
              'h': timedelta(hours=amount), 'd': timedelta(days=amount)}
    return datetime.utcnow() + deltas[unit]


def _parse_daily(value: str, tz: Optional[str] = None) -> datetime:
    match = re.match(r'^daily:(\d{1,2}):(\d{2})$', value.strip().lower())
    if not match:
        raise ValueError(f"Invalid daily format: {value}. Use: daily:09:00")
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise ValueError(f"Invalid time: {hour}:{minute:02d}")
    now = _now(tz)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def _parse_weekly(value: str, tz: Optional[str] = None) -> datetime:
    """Format: 'weekly:mon:09:00' or 'weekly:fri:17:30'"""
    match = re.match(r'^weekly:(mon|tue|wed|thu|fri|sat|sun):(\d{1,2}):(\d{2})$',
                     value.strip().lower())
    if not match:
        raise ValueError(f"Invalid weekly format: {value}. Use: weekly:mon:09:00")
    target_day = DAYS[match.group(1)]
    hour, minute = int(match.group(2)), int(match.group(3))
    now = _now(tz)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    days_ahead = (target_day - target.weekday()) % 7
    if days_ahead == 0 and target <= now:
        days_ahead = 7
    target += timedelta(days=days_ahead)
    return target


def _parse_monthly(value: str, tz: Optional[str] = None) -> datetime:
    """Format: 'monthly:1:09:00' (day 1), 'monthly:15:14:30' (day 15)"""
    match = re.match(r'^monthly:(\d{1,2}):(\d{1,2}):(\d{2})$', value.strip().lower())
    if not match:
        raise ValueError(f"Invalid monthly format: {value}. Use: monthly:1:09:00")
    day = int(match.group(1))
    hour, minute = int(match.group(2)), int(match.group(3))
    if day < 1 or day > 31 or hour > 23 or minute > 59:
        raise ValueError(f"Invalid monthly schedule: {value}")
    now = _now(tz)
    target = now.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        if now.month == 12:
            target = target.replace(year=now.year + 1, month=1)
        else:
            target = target.replace(month=now.month + 1)
    return target
