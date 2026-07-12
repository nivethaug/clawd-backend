# Project Creation

> [TOC](toc.md) | Updated: 2026-07-12

## Purpose

Project creation is the authenticated API flow that creates websites, Telegram bots, Discord bots, and scheduler projects. The API inserts the project record first, creates the project folder with git metadata, and then starts the correct type-specific worker.

## Main Files

| File | Responsibility |
| --- | --- |
| `app.py` | `/projects`, clone, delete/update/status/session/file routes |
| `project_manager.py` | Project folder creation and git initialization |
| `claude_code_worker.py` | Website generation worker |
| `fast_wrapper.py` | Fast website scaffold |
| `infrastructure_manager.py` | Website backend/frontend/database/nginx/PM2 infrastructure |
| `services/telegram/worker.py` | Telegram project pipeline |
| `services/discord/worker.py` | Discord project pipeline |
| `services/scheduler/worker.py` | Scheduler project pipeline |

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

1. Insert project with `status='creating'`.
2. Create project folder and initialize git.
3. Copy/scaffold frontend and backend base.
4. Run AI generation/editing worker.
5. Build frontend/backend as needed.
6. Configure PM2, nginx, DNS/domain, and verification.
7. Mark project ready or error.

Intermediate website statuses such as `building`, `deploying`, `verifying`, `provisioning`, and `ai_provisioning` are considered part of creation for UI and API locking.

## Telegram Bot Projects

Telegram projects use `type_id=2` and require `bot_token`.

Runtime:

- PM2 process: `tg-bot-{project_id}`
- Template: `templates/telegram-bot-template`
- Worker: `services/telegram/worker.py`
- Webhook API: `api/telegram_webhook.py`

Pipeline summary:

1. Validate Telegram token.
2. Copy template.
3. Inject environment.
4. Install dependencies.
5. Start PM2 bot process.
6. Configure webhook routing.
7. Run AI enhancement.
8. Restart/publish and verify.

## Discord Bot Projects

Discord projects use `type_id=3` and require `bot_token`.

Runtime:

- PM2 process: `dc-bot-{project_id}`
- Template: `templates/discord-bot-template`
- Worker: `services/discord/worker.py`
- Discord uses the gateway/WebSocket model, not Telegram-style webhooks.

Pipeline summary:

1. Validate Discord bot token.
2. Copy template.
3. Inject environment.
4. Install dependencies.
5. Start PM2 process.
6. Configure health endpoint routing.
7. Run AI enhancement.
8. Restart/publish and verify.

## Scheduler Projects

Scheduler projects use `type_id=5`.

Runtime:

- No per-project PM2 process.
- Jobs live in central `scheduler_jobs`.
- The centralized scheduler daemon executes per-project `scheduler/executor.py`.

Pipeline summary:

1. Copy scheduler template.
2. Inject environment and notification channels.
3. AI-enhance `executor.py`.
4. Validate and mark ready.

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
