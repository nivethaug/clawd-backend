# Worker File Proxy (Option B)

> How project-scoped endpoints (download, export, logs, build/publish, files, commits, ...)
> work when projects are hosted on a separate worker VPS.
>
> Companion: [worker_vps_setup.md](./worker_vps_setup.md), [worker_scaling.md](./worker_scaling.md)

## The problem

When the project-creation pipeline runs on a worker VPS, the generated project files live on the
worker's disk. But the public API (`clawd-backend` on main) serves endpoints like
`/projects/{id}/download` and `/projects/{id}/github-export` that **read those files from the local
filesystem** (`os.path.isdir(project_path)`). On main, those paths don't exist →
`"Project directory not found"` for every worker-hosted project.

Duplicating the full API on the worker is the wrong fix: it doubles the attack surface, splits
frontend routing, and creates a permanent dual-hardening burden.

## The solution — internal reverse proxy

Main stays the **single public API host**. The worker runs the **same `app.py`** unchanged on a
**private port** (8003), firewalled to main's IP only. A middleware on main forwards
project-scoped requests to the worker when the project's files aren't local.

```
User → api.dreamagent.cloud (main)
         │
         ├─ middleware: is this project-scoped + files missing locally?
         │     ├─ NO  → handle locally (existing behavior, all non-project routes)
         │     └─ YES → forward to worker:8003 (Authorization header forwarded as-is)
         │              worker handles it (files are local there) → response streamed back
         │
         └─ response → user
```

**No code duplication.** Every endpoint works as-is on both boxes; the middleware just decides
where to run it.

## How "is this project on the worker" is decided

Per request, the middleware:

1. If `WORKER_VPS_URL` env is unset → no worker; pass through (backward compatible, no-op).
2. Parse `project_id` from the path (regex on `/projects/{id}`, `/apps/{id}`, `/plans/{id}`).
3. DB lookup of the project's `project_path`.
4. **Decisive test:** does `os.path.isdir(project_path)` succeed **locally**?
   - **Yes** → main-hosted (legacy or main-created) → handle locally.
   - **No** → worker-hosted → forward to the worker.

This means existing main-hosted projects keep working locally, and new worker-hosted projects are
proxied. **Zero cutover risk** — both coexist.

## Setup

### On the worker (one-time)

```bash
# 1. Start the internal API (serves the existing app on port 8003)
cd /root/clawd-backend
pm2 start start-worker-api.sh --name clawd-worker-api
pm2 save

# 2. Firewall port 8003 to the MAIN VPS IP ONLY (never public)
ufw allow from <MAIN_VPS_IP> to any port 8003 proto tcp

# 3. Verify it's up (from the main VPS, not locally — tests the firewall)
curl -s http://<WORKER_IP>:8003/docs -o /dev/null -w "%{http_code}\n"   # 200
```

### On the main VPS (one-time)

```bash
# Add WORKER_VPS_URL to the backend's env (the file start-backend.sh sources)
echo "" >> /root/clawd-backend/.env.postgres
echo "# Worker VPS internal API (Option B file proxy)" >> /root/clawd-backend/.env.postgres
echo "WORKER_VPS_URL=http://<WORKER_IP>:8003" >> /root/clawd-backend/.env.postgres

# Restart the backend so the middleware picks it up
pm2 restart clawd-backend
```

That's it. The middleware auto-detects the worker on next start.

## Security

- The worker's port 8003 is **firewalled to the main VPS IP only**. Attackers can't reach it.
- The proxy forwards the user's `Authorization: Bearer` header unchanged, so the worker's existing
  `get_user_id_from_token` + ownership checks (`_require_project_owner`) enforce per-user access.
  **No new auth surface** is introduced.
- The proxy strips hop-by-hop headers (connection, transfer-encoding, etc.) per HTTP spec.
- On worker-unreachable errors, the proxy returns a generic `502` (no internal topology leaked).

## What works through the proxy

All ~30 project-scoped, file-dependent endpoints, including:
- `GET /projects/{id}/download` (streaming ZIP — passed through via `httpx.stream`)
- `POST /projects/{id}/github-export`
- `GET /projects/{id}/logs` + `/logs/download`
- `POST /projects/{id}/editor/build-publish`
- `GET|PUT /projects/{id}/files/{path}`
- `POST /projects/{id}/commits` + rollback
- `POST /projects/{id}/publish/{frontend,backend}`
- env reveal, custom-domain verify, apps/actions, plans, etc.

## Rollback

Unset `WORKER_VPS_URL` on main → the middleware becomes a no-op → all requests handled locally.
Legacy projects work; worker projects return `"Project directory not found"` (the pre-proxy state,
no worse than today). Re-enable by setting the env var again.

## Tuning

| Env var | Default | Purpose |
|---|---|---|
| `WORKER_VPS_URL` | (unset) | Worker internal API base URL. Unset = no proxy. |
| `WORKER_PROXY_READ_TIMEOUT` | 600 | Seconds to wait for the worker on read (build/publish is slow). |
