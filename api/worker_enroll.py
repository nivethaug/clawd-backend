#!/usr/bin/env python3
"""Worker self-enrollment — called by freshly spawned fleet workers.

POST /api/workers/enroll  (X-Enroll-Token: WORKER_ENROLL_TOKEN)

The golden-image worker calls this from cloud-init BEFORE starting its
stack. Main:
  1. validates the enrollment token (constant-time)
  2. registers the node in worker_nodes (auto_managed, its own per-node
     internal secret, provider instance reference passed by the caller)
  3. opens the master-Postgres firewall to the node's IP
  4. returns the complete worker.env (DB creds, platform keys, identity)

The token is the only credential a fresh instance holds; it grants nothing
beyond adding itself to the pool.
"""

import logging
import secrets as pysecrets
import subprocess
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("api.worker_enroll")

router = APIRouter()


class EnrollRequest(BaseModel):
    server_ip: str
    node_id: Optional[str] = None          # fleet assigns when omitted
    region: Optional[str] = "eu"
    provider: Optional[str] = "vultr"
    provider_instance_id: Optional[str] = None


@router.post("/api/workers/enroll")
async def enroll_worker(req: EnrollRequest, x_enroll_token: Optional[str] = Header(None)):
    token = (x_enroll_token or "").strip()
    expected = __import__("os").getenv("WORKER_ENROLL_TOKEN", "").strip()
    if not expected or not token or not pysecrets.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Invalid enrollment token")
    import os as _os
    import uuid as _uuid

    ip = req.server_ip.strip()
    if not ip or len(ip) > 45:
        raise HTTPException(status_code=400, detail="server_ip required")

    node_id = (req.node_id or "").strip() or f"auto-{_uuid.uuid4().hex[:8]}"
    node_secret = f"{node_id}-{_uuid.uuid4().hex}"

    from database_adapter import get_db
    from services.worker_registry import invalidate_cache

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO worker_nodes (id, name, api_url, server_ip, region, is_shared, status, secret,
                                      auto_managed, provider, provider_instance_id)
            VALUES (%s, %s, %s, %s, %s, FALSE, 'active', %s, TRUE, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                api_url = EXCLUDED.api_url,
                server_ip = EXCLUDED.server_ip,
                region = EXCLUDED.region,
                secret = EXCLUDED.secret,
                auto_managed = TRUE,
                provider = EXCLUDED.provider,
                provider_instance_id = EXCLUDED.provider_instance_id,
                status = 'active',
                updated_at = NOW()
            """,
            (node_id, f"Fleet worker {node_id}", f"http://{ip}:8003", ip,
             (req.region or "eu").strip().lower(), node_secret,
             (req.provider or "vultr").strip(), (req.provider_instance_id or "").strip() or None),
        )
        conn.commit()
    invalidate_cache()
    logger.info("[ENROLL] worker %s enrolled (ip=%s provider=%s)", node_id, ip, req.provider)

    # Open master Postgres to the new node (main runs as root under pm2)
    try:
        subprocess.run(
            ["ufw", "allow", "from", ip, "to", "any", "port", "5432",
             "comment", f"auto {node_id}"],
            check=True, timeout=15, capture_output=True,
        )
    except Exception as exc:
        logger.error("[ENROLL] ufw allow failed for %s: %s (worker will fail DB connects)", ip, exc)

    # Assemble the full worker.env from main's secrets (never logged/returned elsewhere)
    env = {}
    for line in open("/root/clawd-backend/.env"):
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v
    g = env.get
    worker_env = "\n".join([
        f"DB_HOST={g('DB_HOST', '195.200.14.37')}",
        "DB_PORT=5432",
        "DB_NAME=dreampilot",
        "DB_USER=clawd_worker",
        "DB_PASSWORD=" + env["DB_PASSWORD"],
        "USE_POSTGRES=true",
        f"WORKER_NODE_ID={node_id}",
        "EXECUTION_MODE=container",
        "INTERNAL_API_SECRET=" + g("INTERNAL_API_SECRET", ""),
        f"WORKER_INTERNAL_SECRET={node_secret}",
        "TRUST_PROXY_AUTH=1",
        "ZAI_API_KEY=" + g("ZAI_API_KEY", ""),
        "OPENROUTER_API_KEY=" + g("OPENROUTER_API_KEY", ""),
        f"SERVER_IP={ip}",
        "HOSTINGER_API_TOKEN=" + g("HOSTINGER_API_TOKEN", ""),
        f"DREAMPILOT_WORKER_API_URL=http://{ip}:8003",
        "",
    ])
    return {"node_id": node_id, "worker_env": worker_env}
