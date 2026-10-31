#!/usr/bin/env python3
"""Worker Nodes Admin Router — manage the dedicated-worker registry.

Mounted at: /api/admin/workers (prefix added in app.py).

Endpoints:
  GET  /                     — list nodes + per-node queue depth
  POST /                     — register/update a node (upsert by id)
  POST /users/{user_id}/dedicated-worker — bind a user to a node (or clear)

Auth: `_require_admin` on every route, matching api/support/admin_router.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from utils.auth_helpers import get_user_id_from_token

logger = logging.getLogger("api.workers_admin")

router = APIRouter()

_ALLOWED_STATUSES = {"active", "drained"}


def _require_admin(authorization: Optional[str]) -> int:
    user_id = get_user_id_from_token(authorization)
    from app import require_admin  # lazy — avoid circular import
    require_admin(user_id)
    return user_id


class WorkerNodeRequest(BaseModel):
    id: str
    name: str
    api_url: str
    server_ip: Optional[str] = None
    region: Optional[str] = None
    is_shared: bool = False
    status: str = "active"
    # Per-worker internal-API secret. Also set as WORKER_INTERNAL_SECRET in
    # that worker's env — it accepts this OR the fleet-wide secret.
    secret: Optional[str] = None


class DedicatedWorkerRequest(BaseModel):
    worker_id: Optional[str] = None  # None/null clears the binding


@router.get("/")
async def list_worker_nodes(authorization: Optional[str] = Header(None)):
    _require_admin(authorization)
    from database_postgres import get_db
    from services.worker_registry import list_nodes, invalidate_cache

    invalidate_cache()
    nodes = list_nodes()
    queue: dict = {}
    try:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT assigned_worker_id, status, COUNT(*) AS n
                FROM (
                    SELECT assigned_worker_id, status FROM session_chat_runs
                    UNION ALL
                    SELECT assigned_worker_id, status FROM project_creation_runs
                ) all_runs
                WHERE status IN ('queued', 'running')
                GROUP BY assigned_worker_id, status
                """
            ).fetchall()
        for row in rows:
            d = row if isinstance(row, dict) else dict(zip(("assigned_worker_id", "status", "n"), row))
            key = str(d.get("assigned_worker_id") or "shared")
            queue.setdefault(key, {})[str(d.get("status"))] = int(d.get("n") or 0)
    except Exception as exc:
        logger.warning("[WORKERS-ADMIN] queue counts failed: %s", exc)

    return {
        "nodes": [
            {
                **{k: v for k, v in node.items() if k != "secret"},
                "secret_set": bool(node.get("secret")),
                "queue": queue.get(str(node["id"]), {}),
            }
            for node in nodes.values()
        ],
        "shared_queue": queue.get("shared", {}),
    }


@router.post("/")
async def upsert_worker_node(req: WorkerNodeRequest, authorization: Optional[str] = Header(None)):
    admin_id = _require_admin(authorization)
    from database_postgres import get_db
    from services.worker_registry import invalidate_cache

    node_id = req.id.strip()
    if not node_id or "/" in node_id or " " in node_id:
        raise HTTPException(status_code=400, detail="Invalid node id (letters/digits/dash/dot only)")
    if req.status not in _ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(_ALLOWED_STATUSES)}")
    if node_id == "shared" and not req.is_shared:
        raise HTTPException(status_code=400, detail="Node 'shared' must keep is_shared=true")

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO worker_nodes (id, name, api_url, server_ip, region, is_shared, status, secret)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                api_url = EXCLUDED.api_url,
                server_ip = EXCLUDED.server_ip,
                region = EXCLUDED.region,
                is_shared = EXCLUDED.is_shared,
                status = EXCLUDED.status,
                secret = COALESCE(EXCLUDED.secret, worker_nodes.secret)
            """,
            (node_id, req.name.strip(), req.api_url.strip().rstrip("/"),
             (req.server_ip or "").strip() or None,
             (req.region or "").strip().lower() or None,
             req.is_shared, req.status,
             (req.secret or "").strip() or None),
        )
        conn.commit()
    invalidate_cache()
    logger.info("[WORKERS-ADMIN] admin %s upserted node %s -> %s (%s, region=%s, secret=%s)",
                admin_id, node_id, req.api_url, req.status, req.region or "-",
                "set" if req.secret else "kept")
    return {"success": True, "node": {"id": node_id, "api_url": req.api_url.strip().rstrip("/"), "status": req.status, "region": req.region or None}}


@router.post("/users/{user_id}/dedicated-worker")
async def assign_dedicated_worker(
    user_id: int,
    req: DedicatedWorkerRequest,
    authorization: Optional[str] = Header(None),
):
    admin_id = _require_admin(authorization)
    from database_postgres import get_db
    from services.worker_registry import get_node

    worker_id = (req.worker_id or "").strip() or None
    if worker_id and not get_node(worker_id):
        raise HTTPException(status_code=404, detail=f"Worker node '{worker_id}' not found or not active")

    from services import worker_registry

    with get_db() as conn:
        row = conn.execute("SELECT id FROM users WHERE id = %s", (user_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"User {user_id} not found")
        if worker_id:
            # Same claim invariant as pool purchases: one tenant per node,
            # enforced under a node-row lock so a concurrent pool claim
            # cannot double-bind.
            conn.execute("SELECT id FROM worker_nodes WHERE id = %s FOR UPDATE", (worker_id,))
            taken = conn.execute(
                "SELECT id FROM users WHERE dedicated_worker_id = %s AND id <> %s",
                (worker_id, user_id),
            ).fetchone()
            if taken:
                conn.commit()
                raise HTTPException(status_code=409, detail=f"Node '{worker_id}' is already bound to another user")
            # Admin grants have NO paid term: dedicated_until=NULL means the
            # expiry sweep never touches them (sweep requires NOT NULL).
            conn.execute(
                "UPDATE users SET dedicated_worker_id = %s, dedicated_until = NULL WHERE id = %s",
                (worker_id, user_id),
            )
        else:
            conn.execute(
                "UPDATE users SET dedicated_worker_id = NULL, dedicated_until = NULL WHERE id = %s",
                (user_id,),
            )
        conn.commit()
    worker_registry.invalidate_cache()
    if not worker_id:
        # Release through the registry so a homed node gets drained
        worker_registry.release_user_worker(user_id)
    logger.info("[WORKERS-ADMIN] admin %s set user %s dedicated_worker=%s", admin_id, user_id, worker_id or "(cleared)")
    return {"success": True, "user_id": user_id, "dedicated_worker_id": worker_id}
