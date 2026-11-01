"""Auto-fleet: spawn dedicated workers ON DEMAND, destroy when idle.

Zero idle cost model — a worker exists only while demand exists:
  - demand = paid add-on/enterprise subscribers parked with no worker
            + admins who requested on-demand activation (dedicated_pending)
  - pool empty + demand > 0  → Vultr instance from the GOLDEN SNAPSHOT
  - golden image self-enrolls (POST /api/workers/enroll) with its own
    per-node secret; enrollment returns the full worker.env → docker compose up
  - release/expiry drains a node; drained auto nodes with no demand are
    DESTROYED via the Vultr API and the row removed

Provider: Vultr (hourly billing makes spawn/destroy economical).
Golden snapshot: env VULTR_SNAPSHOT_ID (baked from a manually bootstrapped
worker — code + image + claude configs + template + wrapper).
"""
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

VULTR_API = "https://api.vultr.com/v2"
LOOP_SECONDS = 60
DESTROY_IDLE_MINUTES = 15
# One spawn at a time per demand gap (never balloon the fleet)
_pending_spawn_until = 0.0
_lock = threading.Lock()


def _vultr(method: str, path: str, body: Optional[dict] = None) -> Optional[dict]:
    key = os.getenv("VULTR_API_KEY", "").strip()
    if not key:
        return None
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{VULTR_API}{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        logger.error("[FLEET] Vultr %s %s -> %s: %s", method, path, e.code, e.read()[:200])
        return None
    except Exception as exc:
        logger.error("[FLEET] Vultr %s %s failed: %s", method, path, exc)
        return None


def _ssh_run(ip: str, cmd: str, timeout: int = 60, stdin_text: Optional[str] = None):
    """Run a command on the spawned worker as root (main's baked SSH key)."""
    import subprocess
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
         "-o", "ConnectTimeout=10", f"root@{ip}", cmd],
        input=stdin_text, capture_output=True, text=True, timeout=timeout,
    )


def _enroll_via_api(ip: str) -> Optional[dict]:
    """Call main's own enrollment endpoint for this IP. Returns node_id + worker_env."""
    token = os.getenv("WORKER_ENROLL_TOKEN", "").strip()
    if not token:
        return None
    body = json.dumps({"server_ip": ip}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8002/api/workers/enroll", data=body, method="POST",
        headers={"Content-Type": "application/json", "X-Enroll-Token": token},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception as exc:
        logger.error("[FLEET] enroll call failed for %s: %s", ip, exc)
        return None


def _provision_instance(instance_id: str) -> None:
    """Wait for the spawned instance to accept SSH, then enroll + restart its
    stack with fresh identity. Golden-image cloud-init is NOT relied upon
    (snapshot cloud-init skips runcmd — verified live)."""
    deadline = time.time() + 720  # 12 min max
    ip = None
    while time.time() < deadline:
        res = _vultr("GET", f"/instances/{instance_id}")
        inst = (res or {}).get("instance") or {}
        cand = inst.get("main_ip")
        if cand and cand != "0.0.0.0" and inst.get("status") == "active":
            try:
                if _ssh_run(cand, "echo ok", timeout=20).returncode == 0:
                    ip = cand
                    break
            except Exception:
                pass
        time.sleep(20)
    if not ip:
        logger.error("[FLEET] instance %s never became SSHable — leaving for destroy sweep", instance_id)
        return

    enrolled = _enroll_via_api(ip)
    if not enrolled:
        logger.error("[FLEET] enrollment failed for %s — leaving for destroy sweep", ip)
        return

    # User containers bind /srv/cache (npm/pip cache) — must exist on host
    _ssh_run(ip, "mkdir -p /srv/cache && chmod 777 /srv/cache", timeout=30)
    r = _ssh_run(
        ip, "cat > /opt/worker/clawd-backend/deploy/worker/worker.env",
        timeout=30, stdin_text=enrolled["worker_env"],
    )
    if r.returncode != 0:
        logger.error("[FLEET] env push failed for %s: %s", ip, r.stderr[:200])
        return
    r = _ssh_run(
        ip,
        "cd /opt/worker/clawd-backend/deploy/worker && docker compose up -d --force-recreate",
        timeout=300,
    )
    if r.returncode != 0:
        logger.error("[FLEET] stack restart failed for %s: %s", ip, r.stderr[:200])
        return
    logger.info("[FLEET] worker %s provisioned at %s (node=%s)", instance_id, ip, enrolled.get("node_id"))


def _spawn_worker() -> Optional[str]:
    """Create a Vultr instance from the golden snapshot. Returns instance id."""
    snapshot_id = os.getenv("VULTR_SNAPSHOT_ID", "").strip()
    plan = os.getenv("VULTR_SPAWN_PLAN", "vc2-2c-4gb").strip()
    region = os.getenv("VULTR_SPAWN_REGION", "cdg").strip()
    enroll = os.getenv("WORKER_ENROLL_TOKEN", "").strip()
    api_base = os.getenv("PUBLIC_API_BASE", "https://api.dreamagent.cloud").strip()
    if not snapshot_id:
        logger.error("[FLEET] VULTR_SNAPSHOT_ID unset — cannot auto-spawn (provision manually)")
        return None
    if not enroll:
        logger.error("[FLEET] WORKER_ENROLL_TOKEN unset — golden image cannot enroll")
        return None

    # cloud-init: the snapshot has docker + the stack; fetch env from main and start.
    user_data = f"""#cloud-config
runcmd:
  - sleep 10
  - IP=$(curl -s -m 5 http://169.254.169.254/v1/instance/ipv4 || curl -s -m 10 http://api.ipify.org)
  - curl -s -m 30 -X POST {api_base}/api/workers/enroll -H 'Content-Type: application/json' -H 'X-Enroll-Token: {enroll}' -d '{{"server_ip":"'$IP'"}}' -o /tmp/enroll.json
  - python3 -c "import json;d=json.load(open('/tmp/enroll.json'));open('/opt/worker/clawd-backend/deploy/worker/worker.env','w').write(d['worker_env'])"
  - cd /opt/worker/clawd-backend/deploy/worker && docker compose up -d
"""
    res = _vultr("POST", "/instances", {
        "region": region, "plan": plan, "snapshot_id": snapshot_id,
        "user_data": __import__("base64").b64encode(user_data.encode()).decode(),
        "hostname": "ent-auto", "label": "ent-auto (fleet)",
        "enable_ipv6": True, "tags": ["dreamagent", "auto-worker"],
    })
    inst = (res or {}).get("instance") or {}
    iid = inst.get("id")
    if iid:
        logger.info("[FLEET] spawned Vultr instance %s (plan=%s region=%s)", iid, plan, region)
        # Provision in the background: wait SSH → enroll → push env → restart
        threading.Thread(target=_provision_instance, args=(iid,), daemon=True).start()
    return iid


def _demand_count() -> int:
    """Users waiting for a dedicated worker: parked paid subs + pending admins."""
    from database_adapter import get_db

    with get_db() as conn:
        row = conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM users u
                 WHERE u.dedicated_worker_id IS NULL AND u.dedicated_pending) +
              (SELECT COUNT(*) FROM subscriptions s
                 JOIN billing_plans p ON p.id = s.plan_id
                 WHERE p.slug IN ('dedicated-worker', 'enterprise')
                   AND s.status = 'active' AND s.current_period_end > NOW()
                   AND NOT EXISTS (SELECT 1 FROM users u
                                    WHERE u.id = s.user_id
                                      AND u.dedicated_worker_id IS NOT NULL)) AS n
            """
        ).fetchone()
    d = row if isinstance(row, dict) else dict(zip(("n",), row or (0,)))
    return int(d.get("n") or 0)


def _free_pool_count() -> int:
    from services.worker_registry import pool_summary

    return sum(pool_summary().values())


def _destroy_idle_auto_nodes() -> int:
    """Auto-managed nodes with no tenant AND no homed projects, idle >15 min.

    Zero-idle-cost invariant: the free pool for AUTO nodes is always empty —
    demand spawns, release reaps. (Manually registered nodes are never
    touched.) Nodes that homed projects are skipped here — they stay drained
    until wiped/re-registered by an operator.
    """
    from database_adapter import get_db
    from services.worker_registry import invalidate_cache

    destroyed = 0
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, provider_instance_id FROM worker_nodes
            WHERE auto_managed
              AND updated_at < NOW() - INTERVAL '15 minutes'
              AND NOT EXISTS (SELECT 1 FROM users u WHERE u.dedicated_worker_id = worker_nodes.id)
              AND NOT EXISTS (SELECT 1 FROM projects p WHERE p.worker_id = worker_nodes.id)
            """
        ).fetchall()
        for r in rows or []:
            d = r if isinstance(r, dict) else dict(zip(("id", "provider_instance_id"), r))
            iid = d.get("provider_instance_id")
            if iid:
                _vultr("DELETE", f"/instances/{iid}")
            conn.execute("DELETE FROM worker_nodes WHERE id = %s", (d["id"],))
            destroyed += 1
            logger.info("[FLEET] destroyed idle auto node %s (instance %s)", d["id"], iid)
        conn.commit()
    if destroyed:
        invalidate_cache()
    return destroyed


def _existing_auto_instances() -> int:
    """Active/pending Vultr instances tagged auto-worker (any of them may be
    mid-enrollment). Prevents runaway respawns when enrollment is slow/fails."""
    res = _vultr("GET", "/instances?tag=auto-worker")
    insts = (res or {}).get("instances") or []
    return sum(1 for i in insts if i.get("status") in ("active", "pending", "installing"))


def fleet_tick() -> None:
    """One pass: destroy idle auto nodes, spawn when demand exceeds pool."""
    global _pending_spawn_until
    try:
        _destroy_idle_auto_nodes()
    except Exception as exc:
        logger.error("[FLEET] destroy sweep failed: %s", exc)

    if not os.getenv("VULTR_API_KEY"):
        return  # fleet automation disabled without provider creds

    try:
        demand = _demand_count()
        free = _free_pool_count()
        if demand > 0 and free == 0:
            with _lock:
                # rate-limit spawns to one per 5 min (enroll takes ~2-3 min)
                if time.time() < _pending_spawn_until:
                    return
                _pending_spawn_until = time.time() + 300
            # NEVER stack instances: if one is already booting/enrolling, wait
            # for it (or its destroy sweep) instead of spawning another.
            if _existing_auto_instances() > 0:
                logger.info("[FLEET] demand=%d but an auto instance is mid-flight — waiting", demand)
                return
            logger.info("[FLEET] demand=%d pool=0 — spawning dedicated worker", demand)
            _spawn_worker()
        elif demand > 0 and free > 0:
            # A worker exists but nobody claimed it yet — activate now
            from services.worker_registry import retry_pending_dedication_claims
            retry_pending_dedication_claims()
    except Exception as exc:
        logger.error("[FLEET] tick failed: %s", exc)


def _loop() -> None:
    logger.info("[FLEET] started (tick=%ss)", LOOP_SECONDS)
    time.sleep(30)
    while True:
        fleet_tick()
        time.sleep(LOOP_SECONDS)


_started = False


def start_fleet_manager() -> None:
    """Start the fleet daemon thread (idempotent)."""
    global _started
    if _started or not os.getenv("VULTR_API_KEY"):
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="fleet-manager").start()
