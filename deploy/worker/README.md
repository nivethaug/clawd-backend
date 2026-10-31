# Dedicated Worker — Docker Installation

One image, four services, one command. Replaces the ~40-minute manual runbook.

## What runs

| Service | Role | Port |
|---|---|---|
| `worker-api` | same `app.py` as main — receives proxied file/chat/internal routes | 8003 (host) |
| `session-chat-worker` | claims queued chat runs from master Postgres | — |
| `project-creation-worker` | claims project-creation runs | — |
| `wrapper` | wrapper-v2 anthropic-compat proxy → z.ai / OpenRouter | 7861 (host) |

All services share the **host network** (project containers reach the wrapper
at `localhost:7861`; `:8003` binds directly for the main-VPS proxy) and the
**host Docker socket** (the platform creates per-user project containers on
the host daemon — same as the shared worker). `privileged: true` is required
for bwrap user-namespace sandboxes.

## Fresh-host install

```bash
# on the new host (Ubuntu 24.04):
MAIN_VPS=195.200.14.37 WORKER_NODE_ID=ent-2 bash bootstrap.sh
# edit deploy/worker/worker.env (DB password, keys, SERVER_IP)
# then rebuild/start:
docker compose up -d --build
```

Firewall (once):

```bash
ufw default deny incoming
ufw allow from 195.200.14.37 to any port 22
ufw allow from 195.200.14.37 to any port 8003
ufw allow 80,443/tcp
ufw enable
# and on main: ufw allow from <worker ip> to any port 5432
```

## Verify

```bash
curl -s http://127.0.0.1:7861/health                     # wrapper ok
docker compose logs session-chat-worker --tail 20        # "started ... node=ent-2", idle claims
docker compose logs project-creation-worker --tail 20
# from main:
curl -s http://<worker-ip>:8003/models | head -c 120     # proxied API reachable
```

## Register into the pool (on main)

```bash
curl -X POST https://api.dreamagent.cloud/api/admin/workers \
  -H "Authorization: Bearer <admin-token>" -H "Content-Type: application/json" \
  -d '{"id":"ent-2","name":"Dedicated EU #2","api_url":"http://<ip>:8003",
       "server_ip":"<ip>","region":"eu","is_shared":false,"status":"active"}'
```

The worker immediately appears in `regions_available` and the Billing-page
Dedicated card can sell it.

## Updating the stack

```bash
cd /opt/worker/clawd-backend && git pull origin container-migration
cd deploy/worker && docker compose build && docker compose up -d
```

The image bakes the backend code; wrapper-v2 lives at `/opt/wrapper` on the
host (bind-mounted) — update it with `git -C /opt/wrapper pull` (or rsync)
then `docker compose restart wrapper`.

## Scaling

- More creation throughput: `docker compose up -d --scale project-creation-worker=2`
- More workers (tenants): bootstrap another host with a new `WORKER_NODE_ID`,
  register it — the pool and claim filter handle the rest.

## Rollback

`docker compose down` stops the worker; runs it owned stay queued (hard
isolation) and execute when the stack returns.
