#!/usr/bin/env python3
"""Dedicated Worker add-on — user-facing endpoints.

Mounted at: /api/billing/dedicated.

The add-on is a Razorpay subscription to the 'dedicated-worker' pseudo-plan
(is_addon=true — never replaces the user's main plan). Purchase goes through
the EXISTING /api/billing/razorpay/subscription endpoint (plan_slug
'dedicated-worker', optional region); this router exposes status + cancel.

Isolation engine: services/worker_registry.py + the claim/stamp/proxy routing
shipped with the worker_nodes registry.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from utils.auth_helpers import get_user_id_from_token

logger = logging.getLogger("api.dedicated")

router = APIRouter()

ADDON_SLUG = "dedicated-worker"


@router.get("/status")
async def dedicated_status(authorization: Optional[str] = Header(None)):
    """Current dedication + region availability + price (for the upgrade card)."""
    user_id = get_user_id_from_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    from services import worker_registry
    from services.plan_cache import get_plan

    dedication = worker_registry.get_user_dedication(user_id)
    plan = get_plan(ADDON_SLUG) or {}
    return {
        "active": bool(dedication and dedication.get("dedicated_worker_id")),
        "worker": {
            "id": dedication.get("dedicated_worker_id"),
            "name": dedication.get("worker_name"),
            "region": dedication.get("region"),
        } if dedication else None,
        "dedicated_until": dedication.get("dedicated_until") if dedication else None,
        "regions_available": worker_registry.pool_summary(),
        "price_monthly_cents": plan.get("price_monthly_cents"),
    }


@router.get("/health")
async def dedicated_worker_health(authorization: Optional[str] = Header(None)):
    """Enterprise user: real-time health of THEIR dedicated worker (only).

    Shows RAM, storage, CPU, uptime, Docker containers, and OOM events for
    the worker assigned to this user. No access to other workers or main.
    """
    user_id = get_user_id_from_token(authorization)

    from services import worker_registry

    dedication = worker_registry.get_user_dedication(user_id)
    if not dedication or not dedication.get("dedicated_worker_id"):
        raise HTTPException(status_code=404, detail="No dedicated worker active")

    node = worker_registry.get_node(dedication["dedicated_worker_id"])
    if not node:
        raise HTTPException(status_code=503, detail="Dedicated worker is not responding")

    ip = node.get("server_ip") or ""
    if not ip:
        raise HTTPException(status_code=503, detail="Worker has no IP registered")

    # Fetch stats via SSH from the worker
    import subprocess as sp

    try:
        result = sp.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", f"root@{ip}",
             "free -m | awk 'NR==2{print $2,$3,$7}'; "
             "df -h / | awk 'NR==2{print $2,$3,$5}' | tr ' ' '|'; "
             "cat /proc/loadavg | awk '{print $1,$2,$3}'; "
             "nproc; "
             "cat /proc/uptime | awk '{print $1}'; "
             "dmesg 2>/dev/null | grep -c 'Out of memory' || echo 0; "
             "docker stats --no-stream --format '{{.Name}}|{{.MemUsage}}|{{.CPUPerc}}' 2>/dev/null | head -20"],
            capture_output=True, text=True, timeout=20,
        )
        lines = result.stdout.strip().split("\n")
        if len(lines) < 7 or result.returncode != 0:
            raise HTTPException(status_code=503, detail="Worker health check failed")

        # Parse: mem_total|mem_used|mem_available
        mem_parts = lines[0].split()
        total_mb, used_mb, avail_mb = int(mem_parts[0]), int(mem_parts[1]), int(mem_parts[2])

        # Parse: disk_total|disk_used|disk_pct
        disk_parts = lines[1].split("|")
        disk_total = disk_parts[0].replace("G", "").replace(",", ".")
        disk_used = disk_parts[1].replace("G", "").replace(",", ".")
        disk_pct = float(disk_parts[2].replace("%", "").replace(",", "."))

        # Parse: load1 load5 load15
        load_parts = lines[2].split()
        load1 = float(load_parts[0])
        cores = int(lines[3])

        # Uptime
        uptime_sec = float(lines[4])
        days = int(uptime_sec // 86400)
        hours = int((uptime_sec % 86400) // 3600)

        # OOM
        oom = int(lines[5].strip() or 0)

        # Docker containers (remaining lines)
        containers = []
        for line in lines[6:]:
            if "|" in line:
                parts = line.split("|")
                if len(parts) >= 3:
                    containers.append({
                        "name": parts[0].strip(),
                        "memory": parts[1].strip(),
                        "cpu": parts[2].strip(),
                    })

        return {
            "worker": {
                "id": node["id"],
                "name": node.get("name", node["id"]),
                "ip": ip,
                "region": node.get("region"),
                "status": node.get("status"),
            },
            "memory": {
                "total_mb": total_mb,
                "used_mb": used_mb,
                "available_mb": avail_mb,
                "usage_pct": round(100 * used_mb / total_mb, 1) if total_mb else 0,
            },
            "storage": {
                "total_gb": float(disk_total),
                "used_gb": float(disk_used),
                "usage_pct": disk_pct,
            },
            "cpu": {
                "cores": cores,
                "load_1m": load1,
                "load_pct": round(100 * load1 / cores, 1) if cores else 0,
            },
            "uptime": {"days": days, "hours": hours},
            "oom_events": oom,
            "docker": containers,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Worker unreachable: {str(exc)[:100]}")


@router.post("/admin-activate")
async def dedicated_admin_activate(authorization: Optional[str] = Header(None)):
    """Admin bypass: claim a pool worker WITHOUT payment.

    Admin-grant semantics — no subscription, dedicated_until=NULL (never
    swept). Release via the admin bind endpoint (worker_id null) or the
    card's Cancel button (which falls back to release for admins).
    """
    user_id = get_user_id_from_token(authorization)
    from app import require_admin
    require_admin(user_id)

    from database_adapter import get_db
    from services import worker_registry

    if worker_registry.get_user_dedication(user_id):
        raise HTTPException(status_code=409, detail="Dedicated worker already active for this account")
    node_id = worker_registry.claim_pool_worker(user_id, None)
    if not node_id:
        # Pool empty → on-demand: mark pending (the claim sweep activates the
        # moment a worker enrolls) and wake the fleet manager to spawn one.
        from database_postgres import get_db as _gdb

        with _gdb() as conn:
            conn.execute(
                "UPDATE users SET dedicated_pending = TRUE WHERE id = %s",
                (user_id,),
            )
            conn.commit()
        try:
            from services.fleet_manager import fleet_tick
            import threading
            threading.Thread(target=fleet_tick, daemon=True).start()
        except Exception:
            pass
        return {
            "success": True,
            "spawning": True,
            "message": "No idle workers — spawning a dedicated worker now (~3-5 min). The card activates automatically when it's ready.",
        }
    return {"success": True, "worker_id": node_id, "message": f"Admin-activated dedicated worker '{node_id}' (no charge)"}


@router.post("/cancel")
async def dedicated_cancel(authorization: Optional[str] = Header(None)):
    """Cancel the dedicated-worker subscription at Razorpay.

    The worker stays bound until dedicated_until (paid term end); the billing
    cron then returns it to the pool. The user's main plan is untouched.
    """
    user_id = get_user_id_from_token(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    from database_adapter import get_db
    from services import razorpay_service

    with get_db() as conn:
        row = conn.execute(
            """SELECT s.external_subscription_id
               FROM subscriptions s
               JOIN billing_plans p ON p.id = s.plan_id
               WHERE s.user_id = %s AND s.provider = 'razorpay'
                 AND p.slug = %s AND s.status = 'active'
               ORDER BY s.updated_at DESC LIMIT 1""",
            (user_id, ADDON_SLUG),
        ).fetchone()

    # No Razorpay subscription: admin-granted (or already lapsed) dedication —
    # release the worker immediately for admins instead of a dead-end 404.
    if not row:
        from app import _is_admin_user
        if _is_admin_user(user_id):
            from services import worker_registry
            released = worker_registry.release_user_worker(user_id)
            if released:
                return {"success": True, "message": f"Dedicated worker '{released}' released (admin grant)."}
        raise HTTPException(status_code=404, detail="No active dedicated-worker subscription")
    sub_id = (dict(row) if not isinstance(row, dict) else row)["external_subscription_id"]

    try:
        razorpay_service.cancel_subscription(sub_id)
    except Exception as exc:
        # Provider cancel FAILED: do NOT flip local state — a locally
        # cancelled row would be resurrected by the next subscription.charged
        # webhook while Razorpay keeps billing. Surface the error instead.
        logger.error("[DEDICATED] Razorpay cancel failed for %s: %s", sub_id, exc)
        raise HTTPException(
            status_code=502,
            detail="Could not cancel at the payment provider — nothing changed. Please retry or contact support.",
        )
    razorpay_service.cancel_razorpay_subscription_locally(sub_id, "cancelled")
    return {"success": True, "message": "Dedicated worker cancelled — active until the end of the paid term."}
