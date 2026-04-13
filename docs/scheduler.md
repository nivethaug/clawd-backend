# Scheduler System

> **Purpose:** Centralized job scheduling daemon + REST API for automated task execution
> Last updated: 2026-04-13

---

## Overview

The scheduler is a centralized polling daemon that executes scheduled jobs across ALL scheduler-type projects. It polls the database for due jobs, executes them in parallel via `ThreadPoolExecutor`, and logs results.

**Key design:**
- ONE daemon process manages ALL scheduler projects
- Each project has its own `executor.py` loaded dynamically (cached in memory)
- Jobs are stored centrally in `scheduler_jobs` table (FK to `projects`)
- The daemon is **NOT auto-started** — see [Activation](#activation) section

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  PM2: clawd-backend (FastAPI on :8002)              │
│  ├── POST /projects (type_id=5) → creates project   │
│  │   → run_scheduler_pipeline() in background thread │
│  ├── /api/scheduler/* → CRUD jobs via REST API      │
│  └── Chat → LLM calls job_manager.create(...)       │
└─────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────┐
│  PM2: clawd-scheduler (daemon thread)               │
│  ├── Every 10s: SELECT due jobs from DB             │
│  ├── ThreadPoolExecutor (10 workers)                │
│  └── For each job:                                  │
│      ├── execution_engine._load_executor()          │
│      │   → {project_path}/scheduler/executor.py     │
│      ├── executor.execute_task(job)                 │
│      ├── update_job_run() → next_run timestamp      │
│      └── log_job() → scheduler_logs table           │
└─────────────────────────────────────────────────────┘
```

---

## REST API Endpoints

All endpoints are prefixed with `/api/scheduler`.

| Endpoint | Method | File:Lines | Description |
|----------|--------|------------|-------------|
| `/api/scheduler/projects/{project_id}/jobs` | POST | `api/scheduler_router.py:96-120` | Create a new job |
| `/api/scheduler/projects/{project_id}/jobs` | GET | `api/scheduler_router.py:123-132` | List all jobs for project |
| `/api/scheduler/projects/{project_id}/jobs` | DELETE | `api/scheduler_router.py:181-185` | Clear all project jobs |
| `/api/scheduler/jobs/{job_id}` | GET | `api/scheduler_router.py:135-140` | Get single job |
| `/api/scheduler/jobs/{job_id}` | PUT | `api/scheduler_router.py:143-165` | Update job |
| `/api/scheduler/jobs/{job_id}` | DELETE | `api/scheduler_router.py:168-175` | Delete job + logs |
| `/api/scheduler/jobs/{job_id}/pause` | POST | `api/scheduler_router.py:178-187` | Pause active job |
| `/api/scheduler/jobs/{job_id}/resume` | POST | `api/scheduler_router.py:190-196` | Resume paused job |
| `/api/scheduler/jobs/{job_id}/run` | POST | `api/scheduler_router.py:199-205` | Trigger immediate execution |
| `/api/scheduler/jobs/{job_id}/logs` | GET | `api/scheduler_router.py:215-230` | Get execution logs |

### Request Bodies

**Create Job** (`POST /projects/{project_id}/jobs`):
```json
{
  "job_type": "interval",
  "schedule_value": "5m",
  "task_type": "telegram",
  "payload": {"chat_id": "123", "text": "Hello", "fetch": ["btc_price"]}
}
```

**Update Job** (`PUT /jobs/{job_id}`):
```json
{
  "schedule_value": "10m",
  "payload": {"updated": true},
  "status": "active"
}
```

---

## Schedule Formats

Defined in `services/scheduler/parser.py`.

| Type | Format | Example | Behavior |
|------|--------|---------|----------|
| `interval` | `{N}{s\|m\|h\|d}` | `"5m"`, `"1h"`, `"30s"`, `"2d"` | Runs every N units |
| `daily` | `daily:{HH:MM}` | `"daily:09:00"`, `"daily:14:30"` | Runs once per day at specified time |
| `once` | `"once"` | `"once"` | Runs once, then `next_run` set to `NULL` |

---

## Database Tables

Auto-created by `database_postgres.py:init_schema()` via `CREATE TABLE IF NOT EXISTS`.

### `scheduler_jobs`

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PK | Job ID |
| `project_id` | INTEGER FK → projects(id) | Owning project |
| `job_type` | VARCHAR(20) | `interval`, `daily`, `once` |
| `schedule_value` | VARCHAR(100) | Schedule definition |
| `task_type` | VARCHAR(50) | Free-form: `telegram`, `btc_email`, `weather_alert`, etc. |
| `payload` | JSONB | Task-specific configuration |
| `last_run` | TIMESTAMP | Last execution time |
| `next_run` | TIMESTAMP | Next scheduled execution |
| `status` | VARCHAR(20) | `active`, `paused`, `completed` |
| `created_at` | TIMESTAMP | Creation time |

**Indexes:** `(status, next_run)` WHERE active, `(project_id, status)`

### `scheduler_logs`

| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PK | Log ID |
| `job_id` | INTEGER FK → scheduler_jobs(id) | Related job |
| `status` | VARCHAR(20) | `success` or `failed` |
| `message` | TEXT | Result or error message |
| `created_at` | TIMESTAMP | Log time |

**Index:** `(job_id, created_at DESC)`

---

## Project Creation Pipeline

When a project with `type_id=5` (scheduler) is created via `POST /projects`:

1. **Copy template** → `services/scheduler/template.py:copy_scheduler_template()`
2. **Inject .env** → `services/scheduler/env_injector.py:inject_scheduler_env()` (telegram_bot_token, discord_webhook, smtp, etc.)
3. **AI enhance executor.py** → `services/scheduler/editor.py:SchedulerEditor` (Claude writes task handlers based on description)
4. **Save project.json** → writes project config
5. **Mark ready** → updates project status

Pipeline runs in a background thread (`app.py:918-921`).

---

## Activation

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SCHEDULER_ENABLED` | `true` | Set `false` to stop polling loop |
| `SCHEDULER_INTERVAL` | `10` | Poll interval in seconds |
| `SCHEDULER_MAX_WORKERS` | `10` | Max parallel job execution threads |
| `USE_POSTGRES` | `true` | Must be `true` (scheduler uses `database_postgres`) |

### Option A: Daemon Thread (simplest)

Add to `app.py`:
```python
import threading
from services.scheduler.scheduler import run_scheduler

@app.on_event("startup")
async def start_scheduler_daemon():
    t = threading.Thread(target=run_scheduler, daemon=True)
    t.start()
```

### Option B: Separate PM2 Process (recommended)

Add to `ecosystem.backend.json`:
```json
{
  "name": "clawd-scheduler",
  "script": "/root/clawd-backend/venv/bin/python",
  "args": "-c \"from services.scheduler.scheduler import run_scheduler; run_scheduler()\"",
  "cwd": "/root/clawd-backend",
  "instances": 1,
  "exec_mode": "fork",
  "autorestart": true,
  "env": {
    "PYTHONUNBUFFERED": "1",
    "SCHEDULER_ENABLED": "true",
    "SCHEDULER_INTERVAL": "10",
    "SCHEDULER_MAX_WORKERS": "10"
  }
}
```

Then: `pm2 reload ecosystem.backend.json`

---

## Verification

```bash
# Check PM2 status
pm2 list   # Should show "clawd-scheduler" with status "online"

# Check logs
pm2 logs clawd-scheduler   # Should see "Scheduler started (interval=10s, workers=10)"

# Check DB for due jobs
psql -d dreampilot -c "SELECT id, task_type, next_run, status FROM scheduler_jobs WHERE status='active';"

# Check recent execution logs
psql -d dreampilot -c "SELECT * FROM scheduler_logs ORDER BY created_at DESC LIMIT 10;"
```

---

## Key Files

| File | Purpose |
|------|---------|
| `services/scheduler/scheduler.py` | Main polling loop (daemon) |
| `services/scheduler/execution_engine.py` | Dynamic executor loading with import cache |
| `services/scheduler/jobs.py` | CRUD for `scheduler_jobs` table |
| `services/scheduler/worker.py` | Project creation pipeline (4 steps) |
| `services/scheduler/parser.py` | Parses schedule values (`5m`, `daily:09:00`, `once`) |
| `services/scheduler/logger.py` | Writes to `scheduler_logs` table |
| `services/scheduler/editor.py` | Claude AI enhances `executor.py` during creation |
| `services/scheduler/template.py` | Template copying for new projects |
| `services/scheduler/env_injector.py` | Environment variable injection |
| `services/scheduler/validator.py` | Project validation |
| `services/scheduler/__init__.py` | Public API re-exports |
| `api/scheduler_router.py` | REST API endpoints (prefix: `/api/scheduler`) |
| `database_postgres.py:398-441` | Table schemas (auto-created) |
| `app.py:368-370` | Router registration |
| `app.py:905-921` | Scheduler project creation branch |
