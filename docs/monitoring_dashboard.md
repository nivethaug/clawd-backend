# VPS Monitoring Dashboard

Live, on-demand monitoring for both VPSs. **No daemon, no polling, no open
agent port** — the dashboard backend calls two existing admin-only FastAPI
endpoints when the admin clicks Refresh.

```
┌────────────────────────────────────────────────────────┐
│  Dashboard (DreamAgent project, hosted on WORKER)      │
│  React + Node backend  →  monitor.dreamagent.cloud     │
└────────┬──────────────────────────────────┬────────────┘
         │ HTTPS + admin Bearer (parallel)  │
         ▼                                  ▼
  ┌────────────────────┐           ┌──────────────────────┐
  │ WORKER             │           │ MAIN                 │
  │ localhost:8003/    │           │ api.dreamagent.cloud │
  │   admin/           │           │   /admin/            │
  │   system-metrics   │           │   system-metrics     │
  └────────────────────┘           └──────────────────────┘
```

## What was added

| File | Purpose |
|---|---|
| `services/system_metrics.py` | Read-only collector: CPU, mem, disk, net, Docker, Postgres, PM2, OOM, top procs |
| `app.py` → `GET /admin/system-metrics` | Admin-only route that calls the collector |

The endpoint and the collector are **identical on both VPSs** — they ship in
the same `app:app`. `DREAMAGENT_ROLE` env var (already set on worker via
`start-worker-api.sh`) tags the response as `worker` vs `main`.

## Response shape

See `services/system_metrics.py` → `collect()` return type. Top-level keys:

```
hostname, role, ts, uptime_h, cpu, memory, disk, network,
docker, postgres, pm2, oom_events, top_procs
```

Each subsection is wrapped so a single failure (e.g. Docker not installed)
returns `{"error": "..."}` for that subsection and the rest still works.

## Deploy on both VPSs

1. **Pull the code** on each VPS:

   ```bash
   cd ~/clawd-backend
   git pull          # or rsync from dev box
   ```

2. **Restart the FastAPI app** so the new route + module load:

   ```bash
   # Main
   pm2 restart clawd-backend --update-env

   # Worker (worker-api process)
   pm2 restart worker-api --update-env
   ```

3. **Verify** the endpoint is admin-gated and returns metrics:

   ```bash
   # On each VPS — replace $ADMIN_TOKEN with a real admin user's AUTH_TOKENS entry
   curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
        http://localhost:8000/admin/system-metrics | python -m json.tool | head -40
   ```

   You should see `hostname`, `cpu`, `memory`, etc. A non-admin token → `403`.
   A missing/invalid token → `401`.

4. **Confirm the worker-api port** (the dashboard hits worker via `localhost:8003`,
   not the public API). Verify worker-api is up:

   ```bash
   pm2 describe worker-api | grep -E "script|exec cwd|status"
   curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
        http://localhost:8003/admin/system-metrics | head -5
   ```

## Security model

- **Endpoint is admin-only.** `get_user_id_from_token` + `require_admin`
  inside the route — non-admins get `403`, missing token → `401`.
- **Worker-api on :8003 is firewalled** to localhost + main only. The dashboard
  (on worker) reaches it via `localhost:8003`.
- **Main API** is public but the route itself is admin-gated.
- **Dashboard backend** proxies both calls using its own admin token stored in
  env. The browser never sees any admin token — it only talks to the
  dashboard backend, which has its own admin login (JWT cookie).
- **HTTPS only** via Let's Encrypt on `monitor.dreamagent.cloud`.

## Build the dashboard project

This repo provides only the metrics source. The actual UI is a separate
DreamAgent project you'll create from the admin account:

1. New project → "VPS Monitor Dashboard" → frontend (React + Recharts) +
   backend (Node/Express or FastAPI).
2. Backend reads two env vars at boot:
   - `MAIN_METRICS_URL` = `https://api.dreamagent.cloud/admin/system-metrics`
   - `WORKER_METRICS_URL` = `http://localhost:8003/admin/system-metrics`
   - `METRICS_AUTH_TOKEN` = an admin token (from the admin user's
     `AUTH_TOKENS`)
   - Optional: `HOSTINGER_API_TOKEN` for bandwidth + backup status
3. Single endpoint: `GET /api/metrics` → fires both calls in parallel via
   `Promise.all`, returns `{main: {...}, worker: {...}, hostinger?: {...}}`.
   Called only when admin clicks "Refresh".
4. Frontend: two-column layout, one per VPS. Cards for CPU/RAM/Disk/Docker/
   Postgres/PM2. "Last refreshed" timestamp. Big Refresh button.

## Future (optional, not in v1)

- 7-day SQLite history on the dashboard backend (for trend charts)
- Telegram/Discord alert when OOM count > 0 or RAM > 90%
- Hostinger API integration for bandwidth quota + backup status
