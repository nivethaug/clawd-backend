# Backend API Reference

> [TOC](toc.md) | Updated: 2026-07-12

## Purpose

This document is the current route inventory for the DreamAgent backend. It is grouped by product area instead of exact line numbers because `app.py` changes frequently.

Unless noted as public/webhook/anonymous, routes require `Authorization: Bearer <token>` and validate ownership or admin access in the route handler.

## Core Projects

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/projects` | List authenticated user's projects |
| POST | `/projects` | Create project; blocks if the user already has a creation in progress |
| POST | `/projects/{project_id}/clone` | Clone an existing project |
| PUT | `/projects/{project_id}` | Update project metadata |
| DELETE | `/projects/{project_id}` | Delete project and cleanup infrastructure |
| GET | `/project-types` | List project types |
| POST | `/templates/select` | Select a project template |
| GET | `/template-registry` | Return template registry |

## Project Publish, Status, and Runtime

| Method | Endpoint | Description |
| --- | --- | --- |
| POST | `/projects/{project_id}/publish/frontend` | Build/publish frontend |
| POST | `/projects/{project_id}/publish/backend` | Build/publish backend |
| GET | `/projects/{project_id}/status` | Project status |
| GET | `/projects/{project_id}/ai-status` | AI/pipeline status |
| GET | `/projects/{project_id}/claude-session` | Claude session metadata |
| GET | `/apps` | List running app/runtime state |
| POST | `/apps/{project_id}/action` | PM2 action such as pause/resume for supported project types |

## Sessions and Chat

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/projects/{project_id}/sessions` | List project sessions |
| POST | `/projects/{project_id}/sessions` | Create session |
| DELETE | `/sessions/{session_id}` | Archive/delete session |
| DELETE | `/projects/{project_id}/sessions/{session_id}` | Archive/delete session scoped by project |
| GET | `/sessions/{session_id}/messages` | List session messages |
| GET | `/sessions/details` | Expanded session details |
| GET | `/projects/{project_id}/active-session` | Active lock/session for a project |
| DELETE | `/projects/{project_id}/lock` | Clear project lock |
| POST | `/sessions/{session_id}/release-lock` | Release session lock |
| POST | `/chat` | Chat request; delegates to stream when `stream=true` |
| POST | `/chat/stream` | Streaming chat over SSE |
| POST | `/chat/cancel` | Cancel active chat work |
| GET | `/chat/status` | Active chat status by session key |
| GET | `/chat/chunks` | Poll accumulated chunks after reload |

## Files, Plans, Commits, and Logs

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/plans/{project_id}` | List project plans |
| GET | `/plans/{project_id}/{plan_id}/content` | Get plan content |
| GET | `/projects/{project_id}/files` | List files |
| GET | `/projects/{project_id}/files/{file_path:path}` | Read file |
| PUT | `/projects/{project_id}/files/{file_path:path}` | Save file |
| GET | `/projects/{project_id}/logs` | PM2/project logs |
| GET | `/projects/{project_id}/logs/download` | Download logs |
| POST | `/projects/{project_id}/commits` | Create git commit for project changes |
| GET | `/projects/{project_id}/commits` | List commits |
| GET | `/projects/{project_id}/commits/{message_id}` | Commit metadata for message |
| GET | `/projects/{project_id}/commits/log/{log_id}` | Commit log details |
| GET | `/projects/{project_id}/commits/log/{log_id}/diff` | Commit diff |
| POST | `/projects/{project_id}/commits/{message_id}/rollback` | Roll back by message |
| POST | `/projects/{project_id}/commits/log/{log_id}/rollback` | Roll back by commit log |

## Environment Variables and Domains

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/projects/{project_id}/env` | List project environment variables |
| PUT | `/projects/{project_id}/env` | Update environment variables |
| POST | `/projects/{project_id}/env/reveal` | Reveal secret value |
| GET | `/projects/{project_id}/custom-domain` | Get domain config |
| POST | `/projects/{project_id}/custom-domain` | Add custom domain |
| POST | `/projects/{project_id}/custom-domain/verify` | Verify custom domain |
| DELETE | `/projects/{project_id}/custom-domain` | Remove custom domain |
| GET | `/debug/custom-domain/{project_id}` | Domain debug data |
| GET | `/admin/env-registry` | Admin env registry list |
| POST | `/admin/env-registry` | Admin create registry entry |
| PUT | `/admin/env-registry/{entry_id}` | Admin update registry entry |
| DELETE | `/admin/env-registry/{entry_id}` | Admin delete registry entry |

## Auth, GitHub, and Usage

| Method | Endpoint | Description |
| --- | --- | --- |
| POST | `/auth/signup` | Public signup |
| POST | `/auth/login` | Public login |
| POST | `/auth/logout` | Logout |
| POST | `/auth/google` | Google auth |
| POST | `/auth/verify-email` | Verify email |
| POST | `/auth/resend-verification` | Resend verification |
| GET | `/auth/me` | Current user |
| GET | `/auth/github/url` | GitHub OAuth URL |
| GET | `/auth/github/callback` | GitHub OAuth callback |
| GET | `/auth/github/status` | GitHub connection status |
| DELETE | `/auth/github/disconnect` | Disconnect GitHub |
| POST | `/projects/{project_id}/github-export` | Export project to GitHub |
| GET | `/projects/{project_id}/download` | Download project zip |
| GET | `/auth/limits` | Current user's tier limits |
| GET | `/auth/usage` | Current user's usage summary |
| GET | `/projects/{project_id}/usage` | Project usage summary |

## Gallery and Templates

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/gallery` | Public gallery list |
| POST | `/gallery/upload-thumbnail` | Upload thumbnail |
| GET | `/gallery/my-published` | User's published gallery projects |
| GET | `/gallery/{gallery_id}` | Gallery detail |
| POST | `/projects/{project_id}/publish-to-gallery` | Publish project to gallery |
| PUT | `/gallery/{gallery_id}` | Update gallery item |
| DELETE | `/gallery/{gallery_id}` | Delete gallery item |
| GET | `/projects/{project_id}/gallery-status` | Gallery publish status |
| GET | `/templates` | Public templates |
| GET | `/templates/my-templates` | User/admin templates |
| GET | `/templates/{template_id}` | Template detail |
| POST | `/projects/{project_id}/mark-as-template` | Mark project as template |
| PUT | `/templates/{template_id}` | Update template |
| DELETE | `/templates/{template_id}` | Delete template |
| GET | `/projects/{project_id}/template-status` | Template status |

## Scheduler

Prefix: `/api/scheduler`

| Method | Endpoint | Description |
| --- | --- | --- |
| POST | `/projects/{project_id}/jobs` | Create scheduler job |
| GET | `/projects/{project_id}/jobs` | List project jobs |
| DELETE | `/projects/{project_id}/jobs` | Clear project jobs |
| GET | `/jobs/{job_id}` | Get job |
| PUT | `/jobs/{job_id}` | Update job |
| DELETE | `/jobs/{job_id}` | Delete job |
| POST | `/jobs/{job_id}/pause` | Pause job |
| POST | `/jobs/{job_id}/resume` | Resume job |
| POST | `/jobs/{job_id}/run` | Run job now |
| GET | `/jobs/{job_id}/logs` | Job logs |
| GET | `/projects/{project_id}/logs` | Project scheduler logs |

## Billing

Prefix: `/api/billing`

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/plans` | Billing plans |
| GET | `/summary` | User billing summary |
| GET | `/balances` | Credit balances |
| GET | `/transactions` | Credit transactions |
| GET | `/credit-packs` | Credit pack catalog |
| POST | `/checkout/plan/{plan_slug}` | Create plan checkout |
| POST | `/checkout/credits` | Create credit checkout |
| GET | `/admin/users` | Admin billing users |
| GET | `/admin/users/{user_id}` | Admin user billing detail |
| POST | `/admin/assign-plan` | Admin assign plan |
| POST | `/admin/add-credits` | Admin add credits |
| GET | `/admin/operations` | Admin operation pricing |
| PUT | `/admin/operations/{op_code}` | Admin update operation pricing |
| GET | `/admin/config` | Admin billing config |
| PUT | `/admin/config` | Admin update billing config |
| POST | `/admin/reset-monthly` | Admin monthly reset |
| GET | `/admin/stats` | Admin billing stats |

Webhook:

| Method | Endpoint | Description |
| --- | --- | --- |
| POST | `/webhooks/lemonsqueezy` | LemonSqueezy webhook |

## Prompt Assistant and AI Helpers

| Method | Endpoint | Description |
| --- | --- | --- |
| POST | `/ai/completion` | Anonymous stateless Prompt Assistant conversation and final Project AI prompt |
| POST | `/api/ai/chat` | AI chat assistant |
| GET | `/api/ai/messages` | AI chat message history |
| GET | `/api/ai/active-project` | AI active project |
| DELETE | `/api/ai/messages` | Clear AI messages |
| POST | `/api/ai/selection` | AI selection action |
| POST | `/api/ai/confirm` | AI confirmation action |
| POST | `/api/validate/credentials` | Validate credentials |
| POST | `/api/validate/api-call` | Validate API call |

## Bot Link and Telegram Webhooks

Prefix: `/api/bot`

| Method | Endpoint | Description |
| --- | --- | --- |
| POST | `/link/generate` | Generate bot link code |
| GET | `/link/status` | Get bot link status |
| DELETE | `/link` | Remove bot link |

Telegram webhook routes:

| Method | Endpoint | Description |
| --- | --- | --- |
| POST | `/bot/telegram/webhook` | Telegram webhook receiver |
| POST | `/bot/telegram/setwebhook` | Configure Telegram webhook and refresh Telegram default commands |
| DELETE | `/bot/telegram/webhook` | Delete Telegram webhook |

The set/delete webhook routes intentionally remain unauthenticated for current operational compatibility.

Telegram supports slash commands, inline action buttons, and natural aliases for project/session operations. See [telegram_session_chat.md](./telegram_session_chat.md) for the current command list and selected-session behavior.

Discord control bot routes:

| Method | Endpoint | Description |
| --- | --- | --- |
| POST | `/bot/discord/interactions` | Discord Interactions receiver |
| POST | `/bot/discord/register-commands` | Register Discord slash commands |
| DELETE | `/bot/discord/commands` | Remove Discord slash commands |

Discord supports slash commands, buttons, account linking, project/session operations, billing, and selected-session `/chat` using the same ACP session path as web and Telegram. See [discord_session_chat.md](./discord_session_chat.md).

## Dashboard, Activity, and Admin

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/dashboard/home` | Home dashboard data |
| GET | `/projects/recent-activity` | Recent activity |
| GET | `/projects/recent-activity/simple` | Simple recent activity |
| GET | `/projects/{project_id}/activity` | Project activity details |
| GET | `/admin/users` | Admin user list |
| PUT | `/admin/users/{target_user_id}` | Admin update user |
| POST | `/admin/users/{target_user_id}/reset-limits` | Admin reset user limits |
| GET | `/admin/stats` | Admin stats |
| GET | `/admin/tiers` | Admin tier config |
| PUT | `/admin/tiers/{tier_name}` | Admin update tier |
| GET | `/admin/users/{target_user_id}/limits` | Admin user limits |
| PUT | `/admin/users/{target_user_id}/limits` | Admin update user limits |
| GET | `/admin/usage` | Admin usage summary |
| GET | `/admin/usage/logs` | Admin usage logs |
| GET | `/admin/nginx/orphans` | Admin orphan nginx configs |
| DELETE | `/admin/nginx/orphans/{config_name}` | Admin remove orphan nginx config |

## System

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/health` | Health check |
| POST | `/test` | Diagnostic test route |

## Public / Anonymous Route Summary

Current unauthenticated routes include:

- Auth bootstrap: `/auth/signup`, `/auth/login`, `/auth/google`, `/auth/verify-email`, `/auth/resend-verification`
- Stateless Prompt Assistant: `/ai/completion`
- Public catalog routes where intended: `/gallery`, `/gallery/{gallery_id}`, `/templates`, `/templates/{template_id}`
- Service callbacks: `/webhooks/lemonsqueezy`, `/bot/telegram/webhook`
- Discord Interactions callback: `/bot/discord/interactions`
- Telegram webhook operations retained for compatibility: `/bot/telegram/setwebhook`, `DELETE /bot/telegram/webhook`
- System health/diagnostics: `/health`, `/test`

## Notes for Maintainers

- Keep this file updated whenever route decorators are added, removed, or renamed.
- For detailed request/response examples, use the feature-specific docs linked from [toc.md](./toc.md).
- If an endpoint changes auth behavior, update both this file and the relevant feature doc.
