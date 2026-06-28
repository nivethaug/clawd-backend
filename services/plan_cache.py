"""
Plan Cache — in-memory cache for database-driven plans, credit grants,
AI operations, and billing config.

Replaces the hardcoded TIERS dict in rate_limiter.py.

Cache TTL: 60 seconds. Invalidation hooks allow admin edits to take effect
immediately via invalidate().
"""

import os
import time
import logging
import threading
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = int(os.getenv("PLAN_CACHE_TTL", "60"))


class _PlanCache:
    """Thread-safe in-memory cache for billing configuration."""

    def __init__(self):
        self._lock = threading.RLock()
        self._loaded_at: float = 0.0
        self._plans: Dict[str, Dict[str, Any]] = {}        # slug → plan dict
        self._plans_by_id: Dict[int, Dict[str, Any]] = {}  # id → plan dict
        self._grants: Dict[int, Dict[str, int]] = {}       # plan_id → {credit_type: monthly_limit}
        self._operations: Dict[str, Dict[str, Any]] = {}   # code → operation dict
        self._operations_by_id: Dict[int, Dict[str, Any]] = {}
        self._config: Dict[str, Any] = {}                  # key → value
        self._type_to_operation: Dict[int, Dict[str, Any]] = {}  # project_type.id → operation dict

    def _is_stale(self) -> bool:
        return (time.time() - self._loaded_at) > CACHE_TTL_SECONDS

    def _load_if_stale(self):
        """Reload from DB if cache is stale or empty. Thread-safe."""
        with self._lock:
            if self._plans and not self._is_stale():
                return
            try:
                self._load()
            except Exception as e:
                logger.warning(f"[PLAN-CACHE] Failed to load: {e} (using stale/empty cache)")
                if not self._plans:
                    self._loaded_at = time.time()  # prevent retry storms

    def _load(self):
        """Load all billing config from the database."""
        from database_adapter import get_db

        with self._lock:
            with get_db() as conn:
                # Plans
                rows = conn.execute(
                    "SELECT * FROM billing_plans WHERE active = true ORDER BY sort_order"
                ).fetchall()
                self._plans = {}
                self._plans_by_id = {}
                for r in rows:
                    d = dict(r) if not isinstance(r, dict) else r
                    self._plans[d["slug"]] = d
                    self._plans_by_id[d["id"]] = d

                # Grants
                rows = conn.execute("SELECT plan_id, credit_type, monthly_limit FROM plan_credit_grants").fetchall()
                self._grants = {}
                for r in rows:
                    d = dict(r) if not isinstance(r, dict) else r
                    self._grants.setdefault(d["plan_id"], {})[d["credit_type"]] = int(d["monthly_limit"])

                # Operations
                rows = conn.execute(
                    "SELECT * FROM ai_operations WHERE enabled = true ORDER BY sort_order"
                ).fetchall()
                self._operations = {}
                self._operations_by_id = {}
                for r in rows:
                    d = dict(r) if not isinstance(r, dict) else r
                    self._operations[d["code"]] = d
                    self._operations_by_id[d["id"]] = d

                # Config
                rows = conn.execute("SELECT key, value FROM billing_config").fetchall()
                self._config = {}
                for r in rows:
                    d = dict(r) if not isinstance(r, dict) else r
                    val = d["value"]
                    # value is JSONB — psycopg2 returns it parsed; normalize
                    self._config[d["key"]] = val

                # project_type → operation mapping
                rows = conn.execute(
                    """SELECT pt.id as type_id, o.* FROM project_types pt
                       JOIN ai_operations o ON pt.ai_operation_id = o.id
                       WHERE pt.ai_operation_id IS NOT NULL"""
                ).fetchall()
                self._type_to_operation = {}
                for r in rows:
                    d = dict(r) if not isinstance(r, dict) else r
                    self._type_to_operation[d["type_id"]] = self._operations_by_id.get(
                        d["id"], d
                    )

            self._loaded_at = time.time()
            logger.debug(
                f"[PLAN-CACHE] Loaded {len(self._plans)} plans, "
                f"{len(self._operations)} operations, {len(self._config)} config keys"
            )

    # ----------------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------------

    def get_plan(self, identifier) -> Optional[Dict[str, Any]]:
        """Get plan by slug (str) or id (int)."""
        self._load_if_stale()
        with self._lock:
            if isinstance(identifier, int):
                return self._plans_by_id.get(identifier)
            return self._plans.get(identifier)

    def get_all_plans(self) -> Dict[str, Dict[str, Any]]:
        """Get all active plans keyed by slug."""
        self._load_if_stale()
        with self._lock:
            return dict(self._plans)

    def get_plan_grants(self, plan_id: int) -> Dict[str, int]:
        """Get credit grants for a plan: {credit_type: monthly_limit}."""
        self._load_if_stale()
        with self._lock:
            return dict(self._grants.get(plan_id, {}))

    def get_operation(self, code: str) -> Optional[Dict[str, Any]]:
        """Get an AI operation by code."""
        self._load_if_stale()
        with self._lock:
            return self._operations.get(code)

    def get_all_operations(self) -> Dict[str, Dict[str, Any]]:
        self._load_if_stale()
        with self._lock:
            return dict(self._operations)

    def get_operation_for_type(self, type_id: int) -> Optional[Dict[str, Any]]:
        """Get the AI operation configured for a project_type.id."""
        self._load_if_stale()
        with self._lock:
            return self._type_to_operation.get(type_id)

    def get_billing_config(self, key: str, default=None):
        """Get a billing_config value."""
        self._load_if_stale()
        with self._lock:
            val = self._config.get(key, default)
            # Handle JSONB boolean-as-string normalization
            if isinstance(val, str) and val.lower() in ("true", "false"):
                return val.lower() == "true"
            return val

    def is_early_access_enabled(self) -> bool:
        """Check EARLY_ACCESS_MODE. Env override takes precedence."""
        env_val = os.getenv("EARLY_ACCESS_MODE", "").lower()
        if env_val in ("true", "false", "1", "0"):
            return env_val in ("true", "1")
        db_val = self.get_billing_config("EARLY_ACCESS_MODE", True)
        return bool(db_val)

    def invalidate(self, scope: str = "all"):
        """Force reload on next access.

        scope: 'all' | 'plans' | 'operations' | 'config'
        """
        with self._lock:
            if scope in ("all", "plans", "operations", "config"):
                self._loaded_at = 0.0
            logger.info(f"[PLAN-CACHE] Invalidated scope='{scope}'")


# Singleton
_cache = _PlanCache()


def get_plan_cache() -> _PlanCache:
    """Get the singleton plan cache."""
    return _cache


# Convenience module-level functions
def get_plan(identifier) -> Optional[Dict[str, Any]]:
    return get_plan_cache().get_plan(identifier)


def get_all_plans() -> Dict[str, Dict[str, Any]]:
    return get_plan_cache().get_all_plans()


def get_plan_grants(plan_id: int) -> Dict[str, int]:
    return get_plan_cache().get_plan_grants(plan_id)


def get_operation(code: str) -> Optional[Dict[str, Any]]:
    return get_plan_cache().get_operation(code)


def get_operation_for_type(type_id: int) -> Optional[Dict[str, Any]]:
    return get_plan_cache().get_operation_for_type(type_id)


def is_early_access_enabled() -> bool:
    return get_plan_cache().is_early_access_enabled()


def get_billing_config(key: str, default=None):
    return get_plan_cache().get_billing_config(key, default)


def invalidate(scope: str = "all"):
    get_plan_cache().invalidate(scope)
