# Scheduler Architecture Refactor Plan

## Goal
Move scheduler from per-project DB to main `dreampilot` DB. Centralized execution. No per-project database needed for scheduler type.

## Architecture Change

```
BEFORE (per-project DB):
  Each scheduler project → own DB → own jobs table → own PM2 process

AFTER (centralized):
  Main dreampilot DB → scheduler_jobs table → ONE scheduler_worker.py (thread pool)
  Each project → only executor.py + api_client.py (no DB)
```

## Critical Rules

- [ ] Templates must NOT access DB directly
- [ ] Templates must NOT execute raw SQL
- [ ] Templates must NOT have DB credentials
- [ ] ALL job operations go through services/scheduler/ ONLY
- [ ] Scheduler worker and execution engine are NOT modified by templates

---

## PART 1: Database Schema

### 1. `database_postgres.py` — Add scheduler tables to init_schema()
- [ ] Add `scheduler_jobs` table:
  ```sql
  CREATE TABLE IF NOT EXISTS scheduler_jobs (
      id SERIAL PRIMARY KEY,
      project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
      job_type VARCHAR(20) CHECK (job_type IN ('interval', 'daily', 'once')),
      schedule_value VARCHAR(100) NOT NULL,
      task_type VARCHAR(50) NOT NULL,
      payload JSONB DEFAULT '{}',
      last_run TIMESTAMP,
      next_run TIMESTAMP,
      status VARCHAR(20) DEFAULT 'active',
      created_at TIMESTAMP DEFAULT NOW()
  )
  ```
- [ ] Add `scheduler_logs` table:
  ```sql
  CREATE TABLE IF NOT EXISTS scheduler_logs (
      id SERIAL PRIMARY KEY,
      job_id INTEGER REFERENCES scheduler_jobs(id) ON DELETE CASCADE,
      status VARCHAR(20) CHECK (status IN ('success', 'failed')),
      message TEXT,
      created_at TIMESTAMP DEFAULT NOW()
  )
  ```
- [ ] Add index: `idx_scheduler_jobs_due` on (project_id, status, next_run) WHERE status='active'
- [ ] Add index: `idx_scheduler_logs_job` on (job_id, created_at DESC)
- [ ] Add index: `idx_scheduler_jobs_next_run` on (next_run)

---

## PART 2: Core Services (services/scheduler/)

### 2. `services/scheduler/database.py` — DELETE
- [ ] Remove this file (tables now in database_postgres.py init_schema)

### 3. `services/scheduler/parser.py` — KEEP (already at core)
- [x] Pure logic, no DB dependency
- [x] Functions: calculate_next_run(), _parse_interval(), _parse_daily()

### 4. `services/scheduler/jobs.py` — CREATE NEW (uses main DB)
- [ ] Use `database_postgres.get_db()` for all DB access
- [ ] Table: `scheduler_jobs`
- [ ] **create_job(project_id, job_data)** — validate, compute next_run, insert
  - Validate: job_type, schedule_value, task_type, payload
  - Enforce: max 100 jobs per project
  - Compute next_run via parser.calculate_next_run()
- [ ] **update_job(job_id, updates)** — update schedule_value, payload, status; recalculate next_run
- [ ] **delete_job(job_id)** — safe delete, return bool
- [ ] **list_jobs(project_id)** — all jobs sorted by next_run
- [ ] **get_job(job_id)** — single job
- [ ] **get_due_jobs()** — JOIN projects to get project_path, WHERE status='active' AND next_run <= NOW()
- [ ] **update_job_run(job_id, next_run)** — set last_run, next_run; mark completed if once
- [ ] **pause_job(job_id)** — set status='paused'
- [ ] **resume_job(job_id)** — recalculate next_run, set status='active'
- [ ] **run_job_now(job_id)** — set next_run=NOW() for manual trigger
- [ ] **clear_jobs(project_id=None)** — clear project jobs or all; return count
- [ ] No VALID_TASK_TYPES restriction — executor validates task types, not core

### 5. `services/scheduler/logger.py` — CREATE NEW (uses main DB)
- [ ] Use `database_postgres.get_db()`
- [ ] Table: `scheduler_logs`
- [ ] **log_job(job_id, status, message)** — insert log record

### 6. `services/scheduler/scheduler.py` — CREATE NEW (centralized)
- [ ] ONE loop polls ALL due jobs from main DB (single query via get_due_jobs)
- [ ] ThreadPoolExecutor(max_workers=10) for parallel execution
- [ ] Each worker: execution_engine.execute_job(project, job)
- [ ] Update job timestamps via jobs.update_job_run()
- [ ] Log results via logger.log_job()
- [ ] Never crashes — outer try/catch for DB errors, inner per-job isolation
- [ ] Configurable: SCHEDULER_ENABLED, SCHEDULER_INTERVAL (env vars)

### 7. `services/scheduler/execution_engine.py` — KEEP (already exists)
- [x] No changes — importlib dynamic loader, cached per project_id

### 8. `services/scheduler/__init__.py` — UPDATE
- [ ] Export: create_job, list_jobs, delete_job, update_job, run_job_now

---

## PART 3: Template Cleanup (templates/scheduler-template/)

### 9. DELETE files (centralized now)
- [ ] DELETE `core/database.py` — no per-project DB
- [ ] DELETE `core/__init__.py` — no core package
- [ ] DELETE `scheduler/scheduler.py` — centralized
- [ ] DELETE `scheduler/jobs.py` — centralized
- [ ] DELETE `scheduler/logger.py` — centralized
- [ ] DELETE `scheduler/parser.py` — centralized
- [ ] DELETE `scheduler/execution_engine.py` — centralized

### 10. KEEP files (project-specific)
- [ ] KEEP `scheduler/executor.py` — AI modifies per project
- [ ] KEEP `scheduler/__init__.py` — package marker
- [ ] KEEP `services/api_client.py` — project-specific API calls
- [ ] KEEP `services/__init__.py` — package marker
- [ ] KEEP `config.py` — simplified (no DB vars)
- [ ] KEEP `main.py` — simplified (no DB, no scheduler thread)
- [ ] KEEP `requirements.txt` — simplified (no psycopg2)
- [ ] KEEP `.env.example` — simplified
- [ ] KEEP `llm/categories/` — AI categories catalog
- [ ] KEEP `agent/` — AI index + README

### 11. Template `config.py` — SIMPLIFY
- [ ] Remove: DATABASE_URL, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
- [ ] Keep: PROJECT_PATH, PROJECT_ID (executor context)
- [ ] Keep: task-specific tokens (TELEGRAM_BOT_TOKEN, DISCORD_BOT_TOKEN, SMTP_*)

### 12. Template `main.py` — SIMPLIFY
- [ ] Remove: DB init (init_db)
- [ ] Remove: scheduler thread start
- [ ] Keep: health endpoint only
- [ ] Becomes lightweight placeholder

### 13. Template `requirements.txt` — SIMPLIFY
- [ ] Remove: psycopg2-binary, fastapi, uvicorn, pydantic, python-dotenv
- [ ] Keep: requests (executor API calls)

### 14. Template `.env.example` — SIMPLIFY
- [ ] Remove: DB_* variables, PORT, SCHEDULER_ENABLED, SCHEDULER_INTERVAL
- [ ] Keep: PROJECT_ID, PROJECT_PATH, task-specific tokens

---

## Final Structure

```
services/scheduler/                     ← CORE (centralized, ONE PM2 process)
├── __init__.py                          ← exports: create_job, list_jobs, etc.
├── execution_engine.py                  ← importlib dynamic loader (cached)
├── scheduler.py                         ← ONE loop + thread pool
├── parser.py                            ← interval/daily/once parsing
├── jobs.py                              ← job CRUD + validation (main DB)
└── logger.py                            ← execution logs (main DB)

database_postgres.py                     ← scheduler_jobs + scheduler_logs tables added
                                          to init_schema()

templates/scheduler-template/            ← TEMPLATE (project-specific only)
├── config.py                            ← env vars (no DB credentials)
├── main.py                              ← thin entry point (health only)
├── requirements.txt                     ← requests only
├── .env.example                         ← PROJECT_ID, tokens only
├── scheduler/
│   ├── __init__.py
│   └── executor.py                      ← AI modifies this per project
├── services/
│   ├── __init__.py
│   └── api_client.py                    ← project-specific API calls
├── llm/categories/                      ← AI categories catalog (19 files)
└── agent/                               ← AI index + README
```

---

## Integration: How Templates Create Jobs

Templates and LLM agents use the job service — NOT direct SQL:

```python
from services.scheduler import create_job, list_jobs, delete_job

# LLM creates a job for project 10
create_job(
    project_id=10,
    job_data={
        "job_type": "interval",
        "schedule_value": "10m",
        "task_type": "telegram",
        "payload": {"chat_id": "123", "text": "BTC: {{btc_price}}", "fetch": ["btc_price"]}
    }
)
```

---

## End-to-End Flow (After Refactor)

```
1. User: "Create scheduler that emails BTC price every 10min"
2. LLM creates project (type_id=5) in main DB
   → project_id=10, project_path=/root/.../10_btc-alerts/
3. LLM calls create_job(project_id=10, job_data={...})
   → validates, computes next_run, INSERT INTO scheduler_jobs
4. scheduler_worker.py (ONE PM2 process, always running):
   a. Polls: get_due_jobs() — single query JOINs projects for project_path
   b. Thread pool (10 workers) picks up due jobs
   c. execution_engine.execute_job(project, job)
      → loads /root/.../10_btc-alerts/scheduler/executor.py (cached)
      → executor.execute_task(job) → sends email with BTC price
   d. update_job_run(job_id, next_run) — updates timestamps
   e. log_job(job_id, status, message) — logs result
5. 10 min later → same job picked up again (executor already cached)
```

## Performance Profile
- 1 process, 1 DB query per poll cycle
- Thread pool: 10 parallel workers
- Executor cache: loaded once per project, reused forever
- Scales: 1000 projects = same performance as 1 project

## DO NOT MODIFY
- execution_engine.py — stays as-is
- scheduler_worker.py logic — scheduler.py is new, not modifying existing
- existing project creation flow (telegram/discord/website pipelines)
