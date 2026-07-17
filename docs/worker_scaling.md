# Worker Scaling — Parallel Request Handling

> How to make the worker tier handle concurrent users: multiple project creations, parallel session
> edits, and graceful growth as load increases. Grounded in the actual code (verified safe for
> multi-instance), not theoretical.

---

## Current state (single-instance, serial)

Both workers run as **one instance each**, polling the queue every 2s (`POLL_SECONDS`):

```
User A creates → claimed by worker (runs ~5 min) → User B creates → QUEUED (waits)
                                                          User C creates → QUEUED (waits)
```

`FOR UPDATE SKIP LOCKED` (`session_chat_runs.py:239`, `project_creation_runs.py:193`) means a single
worker claims one run at a time and the rest wait. This is **correct but serial** — it never fails,
but concurrent users wait in line.

---

## Why multiple instances is safe (verified)

The code was designed for horizontal scaling:

| Concern | How it's handled | Evidence |
|---|---|---|
| Double-claiming the same run | `SELECT ... FOR UPDATE SKIP LOCKED` | `session_chat_runs.py:239` |
| Instance identity | `worker_id() = f"{hostname}:{pid}"` — unique per process | `session_chat_runs.py:552` |
| Heartbeat / stale recovery | Updated during execution; 20-min stale → `interrupted` → re-claimable | `session_chat_runs.py:270,311` |
| Shared mutable state | **None** — no module-level globals; all state is DB-backed | verified |
| Billing / credit charge | Per-run, atomic, DB-transactional | `billing_service` |
| Project locks | DB-backed (`SessionLockService`) — one active edit per project | `session_locking.md` |

So you can start N instances of each worker (on one VPS or across VPSes) and they share the queue
safely. The only limit is the machine's CPU/RAM.

---

## The capacity math (do this first)

Before choosing how many instances, measure the box. **On the worker VPS:**

```bash
free -h     # total RAM (each claude run peaks ~1-2GB; each PM2 backend ~50-90MB)
nproc       # CPU cores (claude is CPU-bound during generation)
df -h /     # disk (each project ~200-500MB with node_modules)
```

### Rule of thumb for instance count

- **Each project-creation run** peaks at ~1-2GB RAM (claude subprocess + node build). Leave headroom.
- **Each running deployed project** holds ~50-90MB (PM2 backend process) for as long as it's deployed.
- **CPU**: claude generation saturates a core during ACPX (~5 min). More instances than cores = no speedup, just contention.

Example on a **4-core / 8GB** box:
- Project-creation workers: **2-3 instances** (2-3 concurrent creations, ~4-6GB peak — leaves room for deployed projects)
- Session-chat workers: **3-4 instances** (edits are lighter than creations)
- Deployed projects budget: ~2GB / 90MB ≈ 20-25 running backends before RAM pressure

**Your numbers will differ.** Run `free -h` and `nproc`, then size accordingly.

---

## Plan — scaling in three stages

### Stage 1: Multiple instances on ONE VPS (lowest effort)

Start 2-3 instances of each worker with PM2. No code change, no new VPS.

```bash
# Project-creation: start 3 instances (claim different runs in parallel)
for i in 1 2 3; do
  pm2 start project_creation_worker.py \
    --name "clawd-project-creation-worker-$i" \
    --interpreter /root/clawd-backend/venv/bin/python3.12
done

# Session-chat: start 3 instances
for i in 1 2 3; do
  pm2 start session_chat_worker.py \
    --name "clawd-session-chat-worker-$i" \
    --interpreter /root/clawd-backend/venv/bin/python3.12
done

pm2 save
```

Each gets a unique `worker_id` (hostname + its own pid), so `FOR UPDATE SKIP LOCKED` distributes
runs across them. **3 users creating simultaneously now all run in parallel** (~5 min each, instead
of one waiting ~15 min).

> ⚠️ **Watch RAM.** 3 concurrent creations peak at ~3-6GB. If `free -h` shows you're below ~1GB free
> during a burst, drop to 2 instances. OOM kills are worse than queue waits.

> ⚠️ **Each claude subprocess shares the same `:7861` proxy.** The wrapper-v2 proxy must handle
> concurrent requests — it's async FastAPI/uvicorn, so it does, but watch its logs under load. If it
> bottlenecks, run a second proxy instance on `:7862` and split workers between them via
> `ANTHROPIC_BASE_URL`.

### Stage 2: Separate creation from serving (when deployed projects grow)

Deployed projects accumulate RAM (~50-90MB each, forever). At ~50-100 deployed projects, the box is
RAM-bound just from serving. Split:

- **Worker VPS A** — creation + editing workers + claude + proxy (bursty, CPU-heavy)
- **Worker VPS B** (or main) — hosting deployed project PM2 processes + nginx (steady, low-CPU)

Both read the same master DB. Creation writes project files; the serving VPS runs them. This matches
the original `worker_vps_migration.md` Phase 6 (file storage strategy).

### Stage 3: Multiple worker VPSes (when one box can't hold the creation load)

For high creation concurrency, run N worker VPSes, all polling the same queue:

- Each VPS runs 2-3 worker instances
- `SKIP LOCKED` distributes work across all of them
- `worker_id = hostname:pid` identifies which VPS claimed each run
- Postgres (master, on main) is the single source of truth — no cross-VPS state

Add a `worker_nodes` table (noted in the migration doc's "Future Improvements") to track health,
capacity, and drain state per VPS.

---

## Tuning knobs (env vars, no code change)

| Env var | Default | Effect |
|---|---|---|
| `PROJECT_CREATION_WORKER_POLL_SECONDS` | 2 | How fast a free worker claims the next run. Lower = faster pickup, more DB load. |
| `SESSION_CHAT_WORKER_POLL_SECONDS` | 2 | Same, for session edits |
| `PROJECT_CREATION_RUN_STALE_MINUTES` | 20 | When a dead worker's run becomes re-claimable. Lower = faster recovery, more re-runs. |
| `SESSION_CHAT_RUN_STALE_MINUTES` | 20 | Same, for session edits |
| `PROJECT_CREATION_FAST_TIMEOUT` | 3600 | Max time for fast_wrapper (scaffold) |
| `PROJECT_CREATION_OPENCLAW_TIMEOUT` | 1800 | Max time for claude/openclaw generation |

---

## What to monitor under parallel load

```bash
# Queue depth (how many runs are waiting — the real "are users waiting?" signal)
docker exec dreampilot-postgres psql -U admin -d dreampilot -c \
  "SELECT status, count(*) FROM project_creation_runs WHERE status IN ('queued','running') GROUP BY status;"

# Per-worker load (which instance is busy)
docker exec dreampilot-postgres psql -U admin -d dreampilot -c \
  "SELECT worker_id, count(*) FROM project_creation_runs WHERE status='running' GROUP BY worker_id;"

# RAM pressure (the failure mode)
free -h && pm2 monit

# Stale runs (workers that died mid-run)
docker exec dreampilot-postgres psql -U admin -d dreampilot -c \
  "SELECT count(*) FROM project_creation_runs WHERE status='running' AND heartbeat_at < NOW() - INTERVAL '20 minutes';"
```

---

## Recommended starting point

For launch with modest concurrent users:

1. **Confirm capacity** — `free -h` + `nproc` on the worker
2. **Start 2 instances each** of project-creation + session-chat workers (Stage 1)
3. **Monitor queue depth** for a week of real traffic
4. **Scale up** to 3-4 instances only if the queue depth consistently grows (users waiting > 5 min)
5. **Split creation from serving** (Stage 2) once deployed-project RAM becomes the constraint

Don't over-provision instances on day one — each idle instance still holds RAM and polls the DB every
2s. Start at 2, let real load tell you when to grow.
