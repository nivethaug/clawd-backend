"""
Rate Limiter Service — Subscription-aware per-user rate limiting.

Tiers:  Free → Pro → Dream (+ Admin bypass)
Storage: In-memory sliding window (collections.defaultdict of timestamps).
    Resets on server restart — acceptable for MVP.
    Can be swapped for Redis later without API changes.

Usage in endpoints:
    from services.rate_limiter import rate_limit, RateLimitError

    # Inside an endpoint:
    rate_limit(user_id, "ai_chat")      # raises HTTPException 429 if exceeded
    rate_limit(user_id, "project_create")
"""

import time
import logging
import threading
from collections import defaultdict
from typing import Optional, Dict, List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ============================================================================
# Tier Definitions
# ============================================================================

@dataclass
class RateLimit:
    """Single rate limit: max_requests per window_seconds."""
    max_requests: int          # 0 = unlimited
    window_seconds: int = 3600 # default 1 hour


@dataclass
class TierLimits:
    """All rate limits for a single subscription tier."""
    name: str
    general_api: RateLimit      # GET endpoints (projects list, status, etc.)
    ai_chat: RateLimit          # POST /chat, /chat/stream, /ai/completion
    project_create: RateLimit   # POST /projects
    max_projects: int           # 0 = unlimited


# Unlimited sentinel
UNLIMITED = RateLimit(max_requests=0)

TIERS: Dict[str, TierLimits] = {
    "free": TierLimits(
        name="Free",
        general_api=RateLimit(max_requests=60, window_seconds=3600),
        ai_chat=RateLimit(max_requests=10, window_seconds=3600),
        project_create=RateLimit(max_requests=3, window_seconds=86400),
        max_projects=3,
    ),
    "pro": TierLimits(
        name="Pro",
        general_api=RateLimit(max_requests=300, window_seconds=3600),
        ai_chat=RateLimit(max_requests=100, window_seconds=3600),
        project_create=RateLimit(max_requests=25, window_seconds=86400),
        max_projects=25,
    ),
    "dream": TierLimits(
        name="Dream",
        general_api=UNLIMITED,
        ai_chat=UNLIMITED,
        project_create=UNLIMITED,
        max_projects=0,  # unlimited
    ),
}

DEFAULT_TIER = "free"
VALID_TIERS = list(TIERS.keys())
VALID_ROLES = ["user", "admin"]
VALID_LIMIT_TYPES = ["general_api", "ai_chat", "project_create", "max_projects"]


# ============================================================================
# Per-User Limit Overrides (in-memory, persists until restart)
# ============================================================================

_user_overrides: Dict[int, Dict[str, any]] = {}
"""
Structure: { user_id: { "general_api": RateLimit, "ai_chat": RateLimit, ... , "max_projects": int } }
Missing keys fall back to the user's tier config.
"""


def set_user_override(user_id: int, overrides: Dict[str, any]) -> Dict[str, any]:
    """
    Set per-user rate limit overrides.
    overrides can contain any of: general_api, ai_chat, project_create (as {max, window_seconds}),
    and max_projects (as int).
    Returns the full override config after applying.
    """
    if user_id not in _user_overrides:
        _user_overrides[user_id] = {}

    for key, value in overrides.items():
        if key == "max_projects":
            _user_overrides[user_id][key] = int(value)
        elif key in ("general_api", "ai_chat", "project_create"):
            if isinstance(value, dict):
                _user_overrides[user_id][key] = RateLimit(
                    max_requests=int(value.get("max", 0)),
                    window_seconds=int(value.get("window_seconds", 3600)),
                )
            else:
                # Simple int → just set max, keep default window
                _user_overrides[user_id][key] = RateLimit(max_requests=int(value))

    logger.info(f"Set rate limit overrides for user {user_id}: {overrides}")
    return get_user_overrides(user_id)


def get_user_overrides(user_id: int) -> Dict[str, any]:
    """Get per-user overrides (serialized for API response)."""
    overrides = _user_overrides.get(user_id, {})
    result = {}
    for key, value in overrides.items():
        if isinstance(value, RateLimit):
            result[key] = {"max": value.max_requests, "window_seconds": value.window_seconds}
        else:
            result[key] = value
    return result


def clear_user_overrides(user_id: int):
    """Remove all per-user overrides, reverting to tier defaults."""
    _user_overrides.pop(user_id, None)
    logger.info(f"Cleared rate limit overrides for user {user_id}")


def _get_effective_limit(user_id: int, limit_type: str, tier_config: TierLimits) -> RateLimit:
    """Get the effective RateLimit for a user (override > tier)."""
    override = _user_overrides.get(user_id, {}).get(limit_type)
    if override and isinstance(override, RateLimit):
        return override
    return getattr(tier_config, limit_type, UNLIMITED)


def _get_effective_max_projects(user_id: int, tier_config: TierLimits) -> int:
    """Get effective max_projects (override > tier)."""
    override = _user_overrides.get(user_id, {}).get("max_projects")
    if override is not None:
        return int(override)
    return tier_config.max_projects


# ============================================================================
# In-Memory Sliding Window Store
# ============================================================================

class _WindowStore:
    """Thread-safe sliding-window counters: key → list of timestamps."""

    def __init__(self):
        self._lock = threading.Lock()
        self._windows: Dict[str, List[float]] = defaultdict(list)

    def record(self, key: str) -> int:
        """
        Record a hit and return the count in the current window.
        Evicts expired entries on each call.
        """
        now = time.time()
        with self._lock:
            self._windows[key].append(now)
            return len(self._windows[key])

    def count(self, key: str, window_seconds: int) -> int:
        """Count hits in the last `window_seconds` seconds."""
        cutoff = time.time() - window_seconds
        with self._lock:
            # Evict old entries
            self._windows[key] = [
                ts for ts in self._windows[key] if ts > cutoff
            ]
            return len(self._windows[key])

    def reset(self, key: Optional[str] = None):
        """Reset a specific key or all counters."""
        with self._lock:
            if key:
                self._windows.pop(key, None)
            else:
                self._windows.clear()


_store = _WindowStore()


# ============================================================================
# User Tier / Role Lookup (from DB)
# ============================================================================

def get_user_tier_and_role(user_id: int) -> Dict[str, str]:
    """
    Look up subscription_tier and role from the users table.
    Returns {"tier": "free", "role": "user"} as defaults.
    """
    from database_adapter import get_db

    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT subscription_tier, role FROM users WHERE id = %s",
                (user_id,)
            ).fetchone()

        if row:
            tier = (row.get("subscription_tier") if isinstance(row, dict) else row[0]) or DEFAULT_TIER
            role = (row.get("role") if isinstance(row, dict) else row[1]) or "user"
        else:
            tier = DEFAULT_TIER
            role = "user"

        return {"tier": tier, "role": role}

    except Exception as e:
        logger.warning(f"Rate limiter DB lookup failed for user {user_id}: {e}")
        return {"tier": DEFAULT_TIER, "role": "user"}


# ============================================================================
# Public API
# ============================================================================

class RateLimitExceeded(Exception):
    """Raised when a user exceeds their rate limit."""
    def __init__(self, limit_type: str, tier: str, retry_after_seconds: int, max_requests: int):
        self.limit_type = limit_type
        self.tier = tier
        self.retry_after_seconds = retry_after_seconds
        self.max_requests = max_requests
        super().__init__(
            f"Rate limit exceeded for '{limit_type}' on '{tier}' tier. "
            f"Max {max_requests} requests. Retry after {retry_after_seconds}s."
        )


def check_rate_limit(user_id: int, limit_type: str = "general_api") -> Dict[str, any]:
    """
    Check if a user can make a request. Returns status dict.
    Does NOT raise — caller decides what to do.

    Returns:
        {"allowed": True} or
        {"allowed": False, "retry_after": seconds, "limit": max, "tier": "...", "limit_type": "..."}
    """
    info = get_user_tier_and_role(user_id)
    tier_name = info["tier"]
    role = info["role"]

    # Admin bypass
    if role == "admin":
        return {"allowed": True, "tier": tier_name, "role": role, "bypass": True}

    tier_config = TIERS.get(tier_name, TIERS[DEFAULT_TIER])
    # Use per-user override if set, otherwise tier default
    limit: RateLimit = _get_effective_limit(user_id, limit_type, tier_config)

    if limit is None:
        # Unknown limit_type — allow by default
        return {"allowed": True, "tier": tier_name, "role": role}

    # Unlimited
    if limit.max_requests == 0:
        return {"allowed": True, "tier": tier_name, "role": role, "unlimited": True}

    # Check sliding window
    key = f"{user_id}:{limit_type}"
    current_count = _store.count(key, limit.window_seconds)

    if current_count >= limit.max_requests:
        # Calculate retry_after
        cutoff = time.time() - limit.window_seconds
        # Find the oldest entry in window
        with _store._lock:
            timestamps = [ts for ts in _store._windows.get(key, []) if ts > cutoff]
        oldest = min(timestamps) if timestamps else time.time()
        retry_after = int(oldest + limit.window_seconds - time.time()) + 1

        return {
            "allowed": False,
            "retry_after": max(retry_after, 1),
            "limit": limit.max_requests,
            "remaining": 0,
            "window_seconds": limit.window_seconds,
            "tier": tier_name,
            "role": role,
            "limit_type": limit_type,
        }

    # Record this hit
    _store.record(key)
    remaining = limit.max_requests - current_count - 1

    return {
        "allowed": True,
        "remaining": remaining,
        "limit": limit.max_requests,
        "window_seconds": limit.window_seconds,
        "tier": tier_name,
        "role": role,
        "limit_type": limit_type,
    }


def rate_limit(user_id: int, limit_type: str = "general_api") -> Dict[str, any]:
    """
    Convenience wrapper: checks rate limit and raises RateLimitExceeded if blocked.
    Use this in endpoints to enforce limits.

    Returns the status dict on success (for headers/metadata).
    Raises RateLimitExceeded on failure.
    """
    result = check_rate_limit(user_id, limit_type)
    if not result.get("allowed"):
        raise RateLimitExceeded(
            limit_type=result.get("limit_type", limit_type),
            tier=result.get("tier", DEFAULT_TIER),
            retry_after_seconds=result.get("retry_after", 60),
            max_requests=result.get("limit", 0),
        )
    return result


def check_project_limit(user_id: int) -> Dict[str, any]:
    """
    Check if user can create more projects (max_projects limit per tier).
    Returns {"allowed": True/False, "current": N, "max": N, "tier": "..."}
    """
    info = get_user_tier_and_role(user_id)
    tier_name = info["tier"]
    role = info["role"]

    if role == "admin":
        return {"allowed": True, "current": 0, "max": 0, "tier": tier_name, "role": role, "bypass": True}

    tier_config = TIERS.get(tier_name, TIERS[DEFAULT_TIER])
    max_projects = _get_effective_max_projects(user_id, tier_config)

    if max_projects == 0:
        return {"allowed": True, "current": 0, "max": 0, "tier": tier_name, "role": role, "unlimited": True}

    from database_adapter import get_db
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM projects WHERE user_id = %s",
                (user_id,)
            ).fetchone()
        current = row["cnt"] if isinstance(row, dict) else row[0]
    except Exception:
        current = 0

    allowed = current < max_projects
    return {
        "allowed": allowed,
        "current": current,
        "max": max_projects,
        "tier": tier_name,
        "role": role,
    }


def get_user_limits(user_id: int) -> Dict[str, any]:
    """
    Get full limit info for a user (for frontend display).
    Returns tier name, role, all limits with current usage.
    """
    info = get_user_tier_and_role(user_id)
    tier_name = info["tier"]
    role = info["role"]
    tier_config = TIERS.get(tier_name, TIERS[DEFAULT_TIER])

    limits = {}
    for limit_type in ["general_api", "ai_chat", "project_create"]:
        limit: RateLimit = _get_effective_limit(user_id, limit_type, tier_config)
        key = f"{user_id}:{limit_type}"
        current = _store.count(key, limit.window_seconds) if limit.max_requests > 0 else 0
        is_overridden = user_id in _user_overrides and limit_type in _user_overrides[user_id]
        limits[limit_type] = {
            "max": limit.max_requests if limit.max_requests > 0 else "unlimited",
            "remaining": max(0, limit.max_requests - current) if limit.max_requests > 0 else "unlimited",
            "window_seconds": limit.window_seconds,
            "current_usage": current,
            "overridden": is_overridden,
        }

    # Project count
    proj_info = check_project_limit(user_id)
    effective_max_projects = _get_effective_max_projects(user_id, tier_config)
    limits["projects"] = {
        "max": effective_max_projects if effective_max_projects > 0 else "unlimited",
        "current": proj_info["current"],
        "overridden": user_id in _user_overrides and "max_projects" in _user_overrides.get(user_id, {}),
    }

    overrides = get_user_overrides(user_id)

    return {
        "user_id": user_id,
        "tier": tier_name,
        "tier_display": tier_config.name,
        "role": role,
        "is_admin": role == "admin",
        "limits": limits,
        "overrides": overrides,
    }


def reset_user_limits(user_id: int):
    """Admin: Reset all rate limit counters for a user."""
    for limit_type in ["general_api", "ai_chat", "project_create"]:
        _store.reset(f"{user_id}:{limit_type}")
    logger.info(f"Rate limits reset for user {user_id}")


def update_tier(tier_name: str, updates: Dict[str, any]) -> Dict[str, any]:
    """
    Admin: Update limits for an existing tier at runtime.
    updates can contain: general_api, ai_chat, project_create (as {max, window_seconds}),
    and max_projects (as int).
    Returns the updated tier config.
    """
    if tier_name not in TIERS:
        return {"error": f"Unknown tier: {tier_name}"}

    tier = TIERS[tier_name]

    for key, value in updates.items():
        if key == "max_projects":
            tier.max_projects = int(value)
        elif key == "name":
            tier.name = str(value)
        elif key in ("general_api", "ai_chat", "project_create"):
            current: RateLimit = getattr(tier, key)
            if isinstance(value, dict):
                setattr(tier, key, RateLimit(
                    max_requests=int(value.get("max", current.max_requests)),
                    window_seconds=int(value.get("window_seconds", current.window_seconds)),
                ))
            else:
                setattr(tier, key, RateLimit(max_requests=int(value), window_seconds=current.window_seconds))

    logger.info(f"Updated tier '{tier_name}': {updates}")

    # Return updated tier
    return {
        tier_name: {
            "name": tier.name,
            "general_api": {"max": tier.general_api.max_requests or "unlimited", "window_seconds": tier.general_api.window_seconds},
            "ai_chat": {"max": tier.ai_chat.max_requests or "unlimited", "window_seconds": tier.ai_chat.window_seconds},
            "project_create": {"max": tier.project_create.max_requests or "unlimited", "window_seconds": tier.project_create.window_seconds},
            "max_projects": tier.max_projects or "unlimited",
        }
    }
