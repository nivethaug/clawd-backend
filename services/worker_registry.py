"""Worker-node registry: routing lookups for dedicated (enterprise) workers.

Single source of truth for "which worker serves this user/project/run".
Everything falls back to the legacy single-worker env behavior when no
registry rows apply, so an empty registry is byte-identical to today.

Idempotent-safe: all lookups tolerate a missing table (fresh DBs, partial
migrations) and degrade to None.
"""
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Cache TTL — registry rows change rarely (admin operations); 30s keeps
# per-request lookups off the DB without meaningful staleness.
_TTL_SECONDS = 30
_cache_lock = threading.Lock()
_cache: Dict[str, Any] = {"ts": 0.0, "nodes": {}}

# The node id this box identifies as. Workers set WORKER_NODE_ID (e.g.
# 'aws-ent-1'); unset → 'shared' (the legacy single-worker pool).
NODE_ID = (os.getenv("WORKER_NODE_ID") or "shared").strip() or "shared"

DEFAULT_SHARED_ID = "shared"


def _table_exists(conn) -> bool:
    row = conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = 'worker_nodes'"
    ).fetchone()
    return bool(row)


def _load_nodes() -> Dict[str, Dict[str, Any]]:
    """Fetch all worker_nodes rows (cached). Missing table → empty dict."""
    with _cache_lock:
        now = time.monotonic()
        if now - _cache["ts"] < _TTL_SECONDS:
            return _cache["nodes"]
    try:
        from database_postgres import get_db

        nodes: Dict[str, Dict[str, Any]] = {}
        with get_db() as conn:
            if not _table_exists(conn):
                return nodes
            rows = conn.execute(
                "SELECT id, name, api_url, server_ip, region, is_shared, status, secret FROM worker_nodes"
            ).fetchall()
        for row in rows:
            d = row if isinstance(row, dict) else dict(zip(
                ("id", "name", "api_url", "server_ip", "region", "is_shared", "status", "secret"), row))
            nodes[str(d["id"])] = d
        with _cache_lock:
            _cache["ts"] = now
            _cache["nodes"] = nodes
        return nodes
    except Exception as exc:
        logger.warning("[WORKER-REGISTRY] load failed (degrading to env fallback): %s", exc)
        return {}


def invalidate_cache() -> None:
    """Drop the cache — call after admin mutations."""
    with _cache_lock:
        _cache["ts"] = 0.0
        _cache["nodes"] = {}


def get_node(node_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Active node row by id, or None."""
    if not node_id:
        return None
    node = _load_nodes().get(str(node_id))
    if node and str(node.get("status", "active")) == "active":
        return node
    return None


def list_nodes() -> Dict[str, Dict[str, Any]]:
    return dict(_load_nodes())


def legacy_worker_url() -> Optional[str]:
    """The pre-registry single-worker URL (env), for legacy fallback."""
    url = (os.getenv("WORKER_VPS_URL") or os.getenv("DREAMPILOT_WORKER_API_URL") or "").strip().rstrip("/")
    return url or None


def internal_secret_for_node(node_id: Optional[str]) -> Optional[str]:
    """The secret main uses for /internal/* calls to a node.

    Per-node secret when set (hardened fleet), else the legacy fleet-wide
    INTERNAL_API_SECRET. None when nothing is configured — matching the
    legacy no-secret behavior.
    """
    node = get_node(node_id)
    if node and node.get("secret"):
        return str(node["secret"])
    return os.getenv("INTERNAL_API_SECRET", "").strip() or None


def url_for_node(node_id: Optional[str]) -> Optional[str]:
    """API URL for a node id; None for NULL/unknown → caller uses legacy env."""
    node = get_node(node_id)
    return str(node["api_url"]).rstrip("/") if node else None


def resolve_for_user(user_id: Optional[int]) -> Optional[str]:
    """Node id bound to this user (active only). None → shared pool.

    This is the hard-isolation gate: a returned id means the user's runs
    MUST execute on that node only.
    """
    if not user_id:
        return None
    try:
        from database_postgres import get_db

        with get_db() as conn:
            if not _table_exists(conn):
                return None
            row = conn.execute(
                "SELECT dedicated_worker_id FROM users WHERE id = %s", (user_id,)
            ).fetchone()
        if not row:
            return None
        worker_id = row.get("dedicated_worker_id") if isinstance(row, dict) else row[0]
        # Only an ACTIVE node binds; drained/removed node → shared (safe default)
        return str(worker_id) if get_node(worker_id) else None
    except Exception as exc:
        logger.warning("[WORKER-REGISTRY] user resolve failed for %s: %s", user_id, exc)
        return None


def resolve_for_project(project_id: int) -> Optional[Dict[str, Any]]:
    """Active node row hosting this project's files. None → legacy env path."""
    try:
        from database_postgres import get_db

        with get_db() as conn:
            if not _table_exists(conn):
                return None
            row = conn.execute(
                "SELECT worker_id FROM projects WHERE id = %s", (project_id,)
            ).fetchone()
        if not row:
            return None
        worker_id = row.get("worker_id") if isinstance(row, dict) else row[0]
        return get_node(worker_id)
    except Exception as exc:
        logger.warning("[WORKER-REGISTRY] project resolve failed for %s: %s", project_id, exc)
        return None


def is_shared_node(node_id: Optional[str] = None) -> bool:
    """True when this box (or the given node) serves the shared pool."""
    nid = node_id or NODE_ID
    if nid == DEFAULT_SHARED_ID:
        return True
    node = _load_nodes().get(nid)
    return bool(node and node.get("is_shared"))


# ---------------------------------------------------------------------------
# Dedicated-worker pool (purchasable upsell)
# ---------------------------------------------------------------------------

def pool_summary() -> Dict[str, int]:
    """Available (active, non-shared, unassigned) workers per region."""
    try:
        from database_postgres import get_db

        with get_db() as conn:
            if not _table_exists(conn):
                return {}
            rows = conn.execute(
                """
                SELECT COALESCE(w.region, 'unspecified') AS region, COUNT(*) AS n
                FROM worker_nodes w
                WHERE w.status = 'active'
                  AND w.is_shared = FALSE
                  AND NOT EXISTS (
                      SELECT 1 FROM users u WHERE u.dedicated_worker_id = w.id
                  )
                GROUP BY 1
                """
            ).fetchall()
        out: Dict[str, int] = {}
        for row in rows:
            d = row if isinstance(row, dict) else dict(zip(("region", "n"), row))
            out[str(d["region"])] = int(d["n"] or 0)
        return out
    except Exception as exc:
        logger.warning("[WORKER-REGISTRY] pool summary failed: %s", exc)
        return {}


def get_user_dedication(user_id: int) -> Optional[Dict[str, Any]]:
    """The user's dedicated-worker binding, or None. Includes node + expiry."""
    try:
        from database_postgres import get_db

        with get_db() as conn:
            if not _table_exists(conn):
                return None
            row = conn.execute(
                """
                SELECT u.dedicated_worker_id, u.dedicated_until,
                       w.name AS worker_name, w.region, w.server_ip
                FROM users u
                LEFT JOIN worker_nodes w ON w.id = u.dedicated_worker_id
                WHERE u.id = %s
                """,
                (user_id,),
            ).fetchone()
        if not row:
            return None
        d = row if isinstance(row, dict) else dict(zip(
            ("dedicated_worker_id", "dedicated_until", "worker_name", "region", "server_ip"), row))
        if not d.get("dedicated_worker_id"):
            return None
        return d
    except Exception as exc:
        logger.warning("[WORKER-REGISTRY] dedication lookup failed for %s: %s", user_id, exc)
        return None


def claim_pool_worker(user_id: int, region: Optional[str] = None) -> Optional[str]:
    """Atomically bind an available pool worker to this user.

    Picks an active, non-shared, unassigned worker (region-matched when
    given, any region when None). Returns the node id or None when the
    pool is empty. SKIP LOCKED keeps concurrent purchases safe.
    """
    got = extend_or_claim_dedication(user_id, region=region, until=None)
    return got.get("node_id") if got else None


def extend_or_claim_dedication(
    user_id: int, *, region: Optional[str], until
) -> Optional[Dict[str, Any]]:
    """Renewal-safe dedication update in ONE transaction.

    - user already bound → extend dedicated_until (no re-claim, so a sweep
      racing the renewal webhook can never orphan a paid user onto a
      different worker)
    - unbound → claim from the pool (region-matched)

    Returns {"node_id": ..., "claimed": bool} or None when unbound and the
    pool is empty. `until` may be a datetime or SQL passthrough string.
    """
    try:
        from database_postgres import get_db

        with get_db() as conn:
            if not _table_exists(conn):
                return None
            row = conn.execute(
                "SELECT dedicated_worker_id FROM users WHERE id = %s FOR UPDATE",
                (user_id,),
            ).fetchone()
            if not row:
                conn.commit()
                return None
            current = row.get("dedicated_worker_id") if isinstance(row, dict) else row[0]
            if current:
                conn.execute(
                    "UPDATE users SET dedicated_until = %s WHERE id = %s AND dedicated_worker_id = %s",
                    (until, user_id, current),
                )
                conn.commit()
                return {"node_id": str(current), "claimed": False}
            row = conn.execute(
                """
                SELECT w.id FROM worker_nodes w
                WHERE w.status = 'active'
                  AND w.is_shared = FALSE
                  AND (%s::text IS NULL OR w.region = %s)
                  AND NOT EXISTS (
                      SELECT 1 FROM users u WHERE u.dedicated_worker_id = w.id
                  )
                ORDER BY (w.region = %s) DESC, w.created_at ASC
                LIMIT 1
                FOR UPDATE OF w SKIP LOCKED
                """,
                (region, region, region or ""),
            ).fetchone()
            if not row:
                conn.commit()
                return None
            node_id = row.get("id") if isinstance(row, dict) else row[0]
            conn.execute(
                "UPDATE users SET dedicated_worker_id = %s, dedicated_until = %s WHERE id = %s",
                (node_id, until, user_id),
            )
            conn.commit()
        invalidate_cache()
        logger.info("[WORKER-REGISTRY] user %s claimed pool worker %s (region=%s)", user_id, node_id, region)
        return {"node_id": str(node_id), "claimed": True}
    except Exception as exc:
        logger.error("[WORKER-REGISTRY] extend_or_claim failed for %s: %s", user_id, exc)
        return None


def _drain_if_orphaned(node_id: str) -> None:
    """Remove a node from the pool when its last tenant releases it.

    The node keeps serving its homed projects' file/chat routes (the files
    live on its disk), but it must NOT be sold to a new tenant until wiped
    — a fresh buyer must never inherit the previous tenant's data.
    """
    try:
        from database_postgres import get_db

        with get_db() as conn:
            row = conn.execute(
                """
                SELECT
                  EXISTS (SELECT 1 FROM users u WHERE u.dedicated_worker_id = %s) AS bound,
                  EXISTS (SELECT 1 FROM projects p WHERE p.worker_id = %s) AS homed
                """,
                (node_id, node_id),
            ).fetchone()
            if not row:
                conn.commit()
                return
            d = row if isinstance(row, dict) else dict(zip(("bound", "homed"), row))
            if not d.get("bound") and d.get("homed"):
                conn.execute(
                    "UPDATE worker_nodes SET status = 'drained' WHERE id = %s AND is_shared = FALSE",
                    (node_id,),
                )
                logger.info("[WORKER-REGISTRY] node %s drained (released with homed projects — wipe before re-pooling)", node_id)
            conn.commit()
        invalidate_cache()
    except Exception as exc:
        logger.warning("[WORKER-REGISTRY] drain check failed for %s: %s", node_id, exc)


def release_user_worker(user_id: int) -> Optional[str]:
    """Clear the user's dedicated binding (worker leaves the sellable pool
    if it homed projects — see _drain_if_orphaned)."""
    try:
        from database_postgres import get_db

        with get_db() as conn:
            row = conn.execute(
                "UPDATE users SET dedicated_worker_id = NULL, dedicated_until = NULL WHERE id = %s AND dedicated_worker_id IS NOT NULL RETURNING dedicated_worker_id",
                (user_id,),
            ).fetchone()
            conn.commit()
        released = (row.get("dedicated_worker_id") if isinstance(row, dict) else row[0]) if row else None
        if released:
            invalidate_cache()
            logger.info("[WORKER-REGISTRY] user %s released worker %s", user_id, released)
            _drain_if_orphaned(str(released))
        return str(released) if released else None
    except Exception as exc:
        logger.error("[WORKER-REGISTRY] release failed for %s: %s", user_id, exc)
        return None


def retry_pending_dedication_claims() -> int:
    """Re-try pool claims for PAID add-on subscribers who have no worker.

    Covers the pool-empty-at-charge-time case: the subscription is active
    and paid, but fulfillment parked it. Runs hourly from the billing cron;
    succeeds automatically once the pool is refilled.
    """
    try:
        from database_postgres import get_db

        with get_db() as conn:
            if not _table_exists(conn):
                return 0
            rows = conn.execute(
                """
                SELECT s.user_id, s.current_period_end
                FROM subscriptions s
                JOIN billing_plans p ON p.id = s.plan_id
                WHERE p.slug = 'dedicated-worker'
                  AND s.status = 'active'
                  AND s.current_period_end > NOW()
                  AND NOT EXISTS (
                      SELECT 1 FROM users u
                      WHERE u.id = s.user_id AND u.dedicated_worker_id IS NOT NULL
                  )
                """
            ).fetchall()
        claimed = 0
        for row in rows:
            d = row if isinstance(row, dict) else dict(zip(("user_id", "current_period_end"), row))
            result = extend_or_claim_dedication(int(d["user_id"]), region=None, until=d.get("current_period_end"))
            if result and result.get("claimed"):
                logger.info("[WORKER-REGISTRY] pending claim retry succeeded for user %s -> %s", d["user_id"], result["node_id"])
                claimed += 1
        return claimed
    except Exception as exc:
        logger.error("[WORKER-REGISTRY] pending claim retry failed: %s", exc)
        return 0


# Paid-term grace: Razorpay retries webhooks for hours; releasing at the
# exact term end would steal workers from users whose renewal is merely
# delayed. Release well past the grace instead.
DEDICATION_GRACE_HOURS = 48


def release_expired_dedications() -> int:
    """Return workers to the pool for users past dedicated_until + grace.

    Renewals extend dedicated_until inside the same transaction as the
    claim (extend_or_claim_dedication), so an expiry here means the
    subscription truly lapsed. Drains nodes with homed projects.
    """
    try:
        from database_postgres import get_db

        with get_db() as conn:
            if not _table_exists(conn):
                return 0
            cur = conn.execute(
                """
                UPDATE users SET dedicated_worker_id = NULL, dedicated_until = NULL
                WHERE dedicated_worker_id IS NOT NULL
                  AND dedicated_until IS NOT NULL
                  AND dedicated_until < NOW() - INTERVAL '48 hours'
                RETURNING id, dedicated_worker_id
                """
            )
            rows = cur.fetchall() if cur else []
            conn.commit()
        if rows:
            invalidate_cache()
            for r in rows:
                d = r if isinstance(r, dict) else dict(zip(("id", "worker"), r))
                logger.info("[WORKER-REGISTRY] expired dedication released: user %s -> %s", d.get("id"), d.get("dedicated_worker_id"))
                _drain_if_orphaned(str(d.get("dedicated_worker_id")))
        return len(rows)
    except Exception as exc:
        logger.error("[WORKER-REGISTRY] expiry sweep failed: %s", exc)
        return 0
