# DreamAgent Backend Documentation

> Purpose: help maintainers and AI agents navigate the current backend quickly.
> Last updated: 2026-07-15

## Start Here

| Document | Use it for |
| --- | --- |
| [backend_api_reference.md](./backend_api_reference.md) | Current route inventory grouped by product area |
| [project_creation.md](./project_creation.md) | Project creation, clone, type-specific workers, and creation guards |
| [chat.md](./chat.md) | Chat request contract and non-streaming compatibility path |
| [chat_stream.md](./chat_stream.md) | Streaming chat, ACP edit flow, image handling, cancel/resume |
| [ai_completion.md](./ai_completion.md) | Prompt Assistant / DreamAgent Project AI prompt builder |
| [scheduler.md](./scheduler.md) | Scheduler project runtime and job REST API |
| [billing.md](./billing.md) | Billing, AI credits, LemonSqueezy, and billing admin routes |
| [project_sessions.md](./project_sessions.md) | Session CRUD and message retrieval |
| [session_locking.md](./session_locking.md) | Single active edit session per project |
| [telegram_session_chat.md](./telegram_session_chat.md) | Telegram bridge into project session chat |
| [discord_session_chat.md](./discord_session_chat.md) | Discord control bot bridge into project session chat |
| [slack_session_chat.md](./slack_session_chat.md) | Slack control bot bridge into project and session chat |
| [project_status.md](./project_status.md) | Project status and AI status endpoints |
| [publish_frontend.md](./publish_frontend.md) | Frontend build/publish flow |
| [publish_backend.md](./publish_backend.md) | Backend build/publish flow |
| [recent_activity.md](./recent_activity.md) | Activity feed APIs |
| [dashboard.md](./dashboard.md) | Home dashboard API |
| [DOMAIN_MIGRATION.md](./DOMAIN_MIGRATION.md) | Domain migration notes |
| [TOKEN_USAGE_TRACKING.md](./TOKEN_USAGE_TRACKING.md) | Token and usage tracking notes |
| [ADMIN_USER_MANAGEMENT.md](./ADMIN_USER_MANAGEMENT.md) | Admin user controls |

## Current Backend Entry Points

| Area | Main files |
| --- | --- |
| FastAPI app and core routes | `app.py` |
| AI workspace chat | `app.py`, `chat_handlers.py`, `acp_chat_handler.py`, `claude_code_agent.py` |
| Prompt Assistant | `completion_service.py`, `services/ai/openrouter_client.py` |
| AI chat assistant APIs | `api/ai_chat.py`, `api/ai_selection.py`, `api/ai_confirm.py`, `services/ai/*` |
| Project creation | `app.py`, `project_creation_worker.py`, `services/project_creation_runs.py`, `project_manager.py`, `fast_wrapper.py`, `infrastructure_manager.py` |
| Telegram projects | `services/telegram/*`, `api/telegram_webhook.py`, `templates/telegram-bot-template/*` |
| Telegram session chat | `api/telegram_webhook.py`, `utils/devops_session_context.py`, `acp_chat_handler.py` |
| Discord session chat | `api/discord_webhook.py`, `services/discord_client.py`, `services/external_session_chat.py` |
| Slack session chat | `api/slack_webhook.py`, `services/slack_client.py`, `services/external_session_chat.py` |
| Discord projects | `services/discord/*`, `templates/discord-bot-template/*` |
| Scheduler projects | `services/scheduler/*`, `api/scheduler_router.py`, `templates/scheduler-template/*` |
| Billing | `api/billing_router.py`, `services/billing_service.py`, `services/lemonsqueezy_service.py` |
| Validation | `api/validate_router.py` |
| Bot linking | `api/bot_link.py` |
| Database | `database_postgres.py`, `database_adapter.py`, `projects_schema.sql`, `migrations/*` |

## Auth Model

Most application routes expect an `Authorization: Bearer <token>` header. Project and session routes validate ownership with helpers in `app.py`:

- `_require_project_owner(project_id, authorization)`
- `_require_session_owner(session_id, authorization)`
- `_require_session_key_owner(session_key, authorization)`
- `_require_admin_from_authorization(authorization)`

Expected public or webhook-style routes are limited to auth bootstrap, stateless assistant, and service callbacks, such as `/auth/signup`, `/auth/login`, `/auth/google`, `/auth/verify-email`, `/auth/resend-verification`, `/ai/completion`, `/health`, `/webhooks/lemonsqueezy`, and Telegram webhook management endpoints.

## Project Type IDs

| ID | Type | Main runtime |
| --- | --- | --- |
| 1 | Website | Frontend + optional backend scaffold managed by PM2/nginx |
| 2 | Telegram Bot | `tg-bot-{project_id}` PM2 process |
| 3 | Discord Bot | `dc-bot-{project_id}` PM2 process |
| 5 | Scheduler | Central scheduler daemon plus per-project executor |

## Maintenance Notes

- When routes change, update [backend_api_reference.md](./backend_api_reference.md).
- When request/response behavior changes, update the feature-specific doc, not only this TOC.
- Durable Claude/session and project-creation work requires the PM2 workers `clawd-session-chat-worker` and `clawd-project-creation-worker`; deploys should reload `ecosystem.config.json`.
- Keep docs focused on current runtime behavior. Avoid preserving stale line numbers when code is moving quickly.
- The frontend app lives outside this repository; backend docs should describe API contracts, persistence, auth, workers, and operational behavior.
