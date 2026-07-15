# Project Creation

> [TOC](toc.md) | Updated: 2026-07-15

## Purpose

Project creation is the authenticated API flow that creates websites, Telegram bots, Discord bots, and scheduler projects.

Creation is now durable. `POST /projects` validates the request, inserts the project with `status='creating'`, and queues a `project_creation_runs` row. The separate PM2 process `clawd-project-creation-worker` claims that run and performs the expensive work: billing, folder creation, GitHub setup, template selection, AI generation, build/publish, and final status updates.

This prevents projects from being stranded in `creating` when only the FastAPI backend restarts.

## Main Files

| File | Responsibility |
| --- | --- |
| `app.py` | `/projects`, clone, delete/update/status/session/file routes |
| `project_creation_worker.py` | Durable PM2 worker that claims queued creation runs |
| `services/project_creation_runs.py` | DB-backed project creation queue, run state, chunks, billing/recovery helpers |
| `project_manager.py` | Project folder creation and git initialization |
| `claude_code_worker.py` | Legacy inline/background website worker, kept as fallback when durable creation is disabled |
| `fast_wrapper.py` | Fast website scaffold |
| `infrastructure_manager.py` | Website backend/frontend/database/nginx/PM2 infrastructure |
| `services/telegram/worker.py` | Telegram project pipeline |
| `services/discord/worker.py` | Discord project pipeline |
| `services/scheduler/worker.py` | Scheduler project pipeline |

## Durable Worker Process

Production PM2 should run both the API and the durable project worker:

```bash
pm2 status clawd-backend
pm2 status clawd-project-creation-worker
```

The worker is defined in `ecosystem.config.json`:

```text
clawd-project-creation-worker -> project_creation_worker.py
```

After pulling deploy changes, reload PM2 with:

```bash
pm2 startOrReload ecosystem.config.json --update-env
pm2 save
```

Durable creation is enabled by default. To temporarily fall back to the older inline/background behavior, set:

```bash
PROJECT_CREATION_DURABLE_RUNS=false
```

## Endpoints

| Endpoint | Method | Description |
| --- | --- | --- |
| `/projects` | GET | List authenticated user's projects |
| `/projects` | POST | Create a project |
| `/projects/{project_id}/clone` | POST | Clone an existing project into a new project |
| `/projects/{project_id}` | PUT | Update project metadata |
| `/projects/{project_id}` | DELETE | Delete project and cleanup infrastructure |
| `/project-types` | GET | List configured project types |
| `/template-registry` | GET | Return template registry |
| `/templates/select` | POST | Select a template |

See [backend_api_reference.md](./backend_api_reference.md) for the full current route inventory.

## Auth and Ownership

`GET /projects` and `POST /projects` derive `user_id` from the `Authorization` header. The request body `user_id` is retained for compatibility but is not trusted.

Project-specific routes require the authenticated user to own the project, enforced by `_require_project_owner()`.

## Concurrent Creation Guard

Only one project creation can be in progress per user. `POST /projects` checks for the user's newest project in one of these statuses:

```text
creating, scaffolded, initializing, building, deploying, verifying,
provisioning, infrastructure_provisioning, ai_provisioning
```

If one exists, the API returns:

```json
{
  "detail": "Project creation is already in progress for 'project-name' (creating). Please wait until it finishes before creating another project."
}
```

with status `409`.

The guard still reads project status from `projects`. Queued/running durable creation keeps the project in `creating`, so the UI and API continue to block additional project creation for that user until the worker completes or fails the run.

## Durable Creation Lifecycle

High-level flow:

1. `POST /projects` authenticates the user and validates limits, domain, project type, bot tokens, and create-time environment variables.
2. The API inserts `projects.status='creating'`.
3. The API inserts a matching `project_creation_runs` row with `status='queued'` and prompt-safe payload metadata.
4. The API returns the normal `ProjectResponse` immediately.
5. `clawd-project-creation-worker` claims the oldest queued run with row locking.
6. The worker charges project creation credits.
7. The worker creates the project folder and initializes git.
8. The worker creates/attaches GitHub remote when available.
9. The worker selects the website template when needed.
10. The worker runs the type-specific pipeline.
11. The worker records project creation usage and marks the run `completed`.
12. The project moves to `ready` or the type-specific final status.

Durable run state is stored in:

| Table | Purpose |
| --- | --- |
| `project_creation_runs` | Run ownership, status, payload, worker id, heartbeat, charge metadata, error |
| `project_creation_chunks` | Durable creation logs/progress emitted by the worker |

The API does not need an in-memory thread or process handle to know creation state. It only needs the project row and durable run rows.

## Restart Behavior

| Event | Expected behavior |
| --- | --- |
| `clawd-backend` restarts while creation is running | Creation continues because `clawd-project-creation-worker` owns the work. The UI keeps polling project status from DB. |
| Browser refresh while creation is running | Project remains visible as `creating`; actions stay locked until status changes. |
| Worker restarts before claiming a queued run | New worker claims the queued run and starts normally. |
| Worker is killed while Claude/build subprocess is running | The subprocess cannot be resumed. On worker startup, stale running rows are marked `interrupted`/`failed`, reserved creation credits are refunded when charge metadata exists, and the project is unlocked by moving out of `creating`. |
| Billing fails before creation starts | Run fails, project is marked `failed`, and no folder pipeline starts. |
| Folder/pipeline fails after billing | Worker marks the run failed, marks the project `failed`, and refunds the recorded creation charge. |

This means the durable model covers the previous backend-only restart failure. It does not pretend to resume a killed Claude subprocess if the worker process itself dies mid-run; instead it fails cleanly and prevents a permanent `creating` lock.

## Request

```json
{
  "name": "dragon-sanctuary",
  "domain": "dragon-sanctuary",
  "description": "Cinematic dragon sanctuary website",
  "typeId": 1,
  "template_id": "blank-template"
}
```

## Request Fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `name` | string | yes | Project name |
| `domain` | string | no | Subdomain prefix. Auto-generated if omitted. |
| `description` | string | no | Prompt/project description |
| `typeId` / `type_id` | integer | no | Project type. Defaults to website if omitted. |
| `template_id` | string | no | Optional website template ID |
| `bot_token` | string | type-specific | Telegram or Discord bot token |
| `telegram_bot_token` | string | scheduler optional | Scheduler Telegram channel token |
| `telegram_chat_id` | string | scheduler optional | Scheduler Telegram chat target |
| `discord_webhook_url` | string | scheduler optional | Scheduler Discord notification target |
| `email_to` | string | scheduler optional | Scheduler email notification target |
| `api_endpoint` | string | scheduler optional | Scheduler default API endpoint |

## Response

```json
{
  "id": 1625,
  "user_id": 1,
  "name": "dragon-sanctuary",
  "domain": "dragon-sanctuary-a1b2c3",
  "description": "Cinematic dragon sanctuary website",
  "project_path": "/root/clawd-projects/1625-dragon-sanctuary",
  "type_id": 1,
  "status": "creating",
  "claude_code_session_name": null,
  "template_id": "blank-template",
  "frontend": null,
  "created_at": "2026-07-12 10:00:00"
}
```

## Domain Handling

- If `domain` is omitted, the backend sanitizes the project name and appends a random suffix.
- If `domain` is supplied, it must be 3-50 lowercase letters/numbers/hyphens, start with a letter, and be globally unique.
- Domain/repo sanitization is delegated to the GitHub service helper.

## Website Projects

Website projects use `type_id=1`.

High-level flow:

1. Durable worker claims the queued project creation run.
2. Charge project creation credits.
3. Create project folder and initialize git.
4. Run `fast_wrapper.py` for template/base scaffold.
5. Write create-time environment variables into `backend/.env` when provided.
6. Run `openclaw_wrapper.py` for AI generation and infrastructure provisioning.
7. Build frontend/backend as needed.
8. Configure PM2, nginx, DNS/domain, and verification.
9. Mark project ready or failed.

Intermediate website statuses such as `building`, `deploying`, `verifying`, `provisioning`, and `ai_provisioning` are considered part of creation for UI and API locking.

## Telegram Bot Projects

Telegram projects use `type_id=2` and require `bot_token`.

Runtime:

- PM2 process: `tg-bot-{project_id}`
- Template: `templates/telegram-bot-template`
- Worker: `services/telegram/worker.py`
- Webhook API: `api/telegram_webhook.py`

Pipeline summary:

1. Durable worker claims the queued project creation run.
2. Charge project creation credits.
3. Create project folder and initialize git.
4. Validate Telegram token.
5. Copy template.
6. Inject environment.
7. Install dependencies.
8. Start PM2 bot process.
9. Configure webhook routing.
10. Run AI enhancement.
11. Restart/publish and verify.

## Discord Bot Projects

Discord projects use `type_id=3` and require `bot_token`.

Runtime:

- PM2 process: `dc-bot-{project_id}`
- Template: `templates/discord-bot-template`
- Worker: `services/discord/worker.py`
- Discord uses the gateway/WebSocket model, not Telegram-style webhooks.

Pipeline summary:

1. Durable worker claims the queued project creation run.
2. Charge project creation credits.
3. Create project folder and initialize git.
4. Validate Discord bot token.
5. Copy template.
6. Inject environment.
7. Install dependencies.
8. Start PM2 process.
9. Configure health endpoint routing.
10. Run AI enhancement.
11. Restart/publish and verify.

## Scheduler Projects

Scheduler projects use `type_id=5`.

Runtime:

- No per-project PM2 process.
- Jobs live in central `scheduler_jobs`.
- The centralized scheduler daemon executes per-project `scheduler/executor.py`.

Pipeline summary:

1. Durable worker claims the queued project creation run.
2. Charge project creation credits.
3. Create project folder and initialize git.
4. Copy scheduler template.
5. Inject environment and notification channels.
6. AI-enhance `executor.py`.
7. Validate and mark ready.

## Operational Checks

Useful commands:

```bash
pm2 logs clawd-project-creation-worker --lines 100
pm2 restart clawd-project-creation-worker --update-env
```

Inspect queued/running creation runs:

```sql
SELECT id, project_id, user_id, type_id, status, worker_id, created_at, started_at, heartbeat_at, error
FROM project_creation_runs
ORDER BY created_at DESC
LIMIT 20;
```

Inspect durable creation logs for a project:

```sql
SELECT c.seq, c.chunk_type, c.content, c.created_at
FROM project_creation_chunks c
JOIN project_creation_runs r ON r.id = c.run_id
WHERE r.project_id = <PROJECT_ID>
ORDER BY c.seq ASC;
```

If a deployment accidentally starts only `clawd-backend` and not the worker, new projects will remain `creating` with a queued run. Start/reload PM2 with `ecosystem.config.json` to let the worker claim them.

See [scheduler.md](./scheduler.md) for job operations.

## Clone

`POST /projects/{project_id}/clone` creates a new project from an existing project. Non-website clones may require fresh bot tokens or scheduler channel settings. The new project follows the same creation guard and ownership requirements as normal project creation.

## Deletion and Cleanup

Project deletion removes database records and attempts infrastructure cleanup.

| Project type | Cleanup behavior |
| --- | --- |
| Website | PM2, nginx, SSL, DNS, database/user, project directory |
| Telegram | `tg-bot-{project_id}`, webhook infra, nginx/SSL/DNS, directory |
| Discord | `dc-bot-{project_id}`, nginx/SSL/DNS, directory |
| Scheduler | Scheduler jobs/logs and project directory |

## Related

- [backend_api_reference.md](./backend_api_reference.md)
- [project_status.md](./project_status.md)
- [publish_frontend.md](./publish_frontend.md)
- [publish_backend.md](./publish_backend.md)
- [scheduler.md](./scheduler.md)
