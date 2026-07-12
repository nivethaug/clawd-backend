# Scheduler System

> [TOC](toc.md) | Updated: 2026-07-12

## Purpose

Scheduler projects are lightweight automation projects. A central backend scheduler daemon polls due jobs from the database and executes each job through the owning project's `scheduler/executor.py`.

## Main Files

| File | Responsibility |
| --- | --- |
| `api/scheduler_router.py` | Job and log REST API |
| `services/scheduler/scheduler.py` | Central polling loop |
| `services/scheduler/jobs.py` | Scheduler job CRUD |
| `services/scheduler/execution_engine.py` | Dynamic executor loading and execution |
| `services/scheduler/logger.py` | Execution log persistence |
| `services/scheduler/parser.py` | Schedule parsing |
| `services/scheduler/worker.py` | Scheduler project creation pipeline |
| `templates/scheduler-template/*` | Generated project template |

## REST API

All endpoints are prefixed with `/api/scheduler` and require authentication.

| Endpoint | Method | Description |
| --- | --- | --- |
| `/projects/{project_id}/jobs` | POST | Create job |
| `/projects/{project_id}/jobs` | GET | List jobs for a project |
| `/projects/{project_id}/jobs` | DELETE | Clear all jobs for a project |
| `/jobs/{job_id}` | GET | Get one job |
| `/jobs/{job_id}` | PUT | Update job |
| `/jobs/{job_id}` | DELETE | Delete job |
| `/jobs/{job_id}/pause` | POST | Pause job |
| `/jobs/{job_id}/resume` | POST | Resume job |
| `/jobs/{job_id}/run` | POST | Trigger immediate run |
| `/jobs/{job_id}/logs` | GET | Logs for one job |
| `/projects/{project_id}/logs` | GET | Logs for all jobs in one project |

## Create Job

```json
{
  "job_type": "interval",
  "schedule_value": "5m",
  "task_type": "telegram",
  "payload": {
    "chat_id": "123",
    "text": "Send the BTC price"
  }
}
```

## Update Job

```json
{
  "schedule_value": "10m",
  "payload": {"text": "Updated message"},
  "status": "active"
}
```

## Schedule Formats

| Type | Format | Example | Behavior |
| --- | --- | --- | --- |
| `interval` | `{N}s`, `{N}m`, `{N}h`, `{N}d` | `5m` | Runs every interval |
| `daily` | `daily:HH:MM` | `daily:09:00` | Runs daily at time |
| `once` | `once` | `once` | Runs once then completes |

## Pause and Resume

Pause/resume is handled at the job level:

- Pausing sets the job status to `paused`, so the central scheduler skips it.
- Resuming sets the job status back to `active` and recalculates the next due run.
- Scheduler projects do not have a dedicated PM2 app to pause per project; the daemon stays online and filters jobs by status/project.

For a project-level pause UX, pause all jobs for that project instead of stopping the scheduler daemon.

## Logs

Logs are stored in `scheduler_logs` and linked to `scheduler_jobs`. Use `/api/scheduler/projects/{project_id}/logs` when the UI needs logs for a specific scheduler project. This avoids mixing jobs across projects.

## Database Tables

| Table | Purpose |
| --- | --- |
| `scheduler_jobs` | Job definitions, schedule, status, payload, last/next run |
| `scheduler_logs` | Per-run success/failure log entries |

## Runtime

Recommended production runtime is a separate PM2 process:

```json
{
  "name": "clawd-scheduler",
  "script": "/root/clawd-backend/venv/bin/python",
  "args": "-c \"from services.scheduler.scheduler import run_scheduler; run_scheduler()\"",
  "cwd": "/root/clawd-backend",
  "instances": 1,
  "exec_mode": "fork",
  "autorestart": true
}
```

Environment variables:

| Variable | Default | Description |
| --- | --- | --- |
| `SCHEDULER_ENABLED` | `true` | Enables polling loop |
| `SCHEDULER_INTERVAL` | `10` | Poll interval in seconds |
| `SCHEDULER_MAX_WORKERS` | `10` | Parallel job workers |

## Related

- [project_creation.md](./project_creation.md)
- [backend_api_reference.md](./backend_api_reference.md)
