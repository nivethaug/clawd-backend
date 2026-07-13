# AI Chat System

> [TOC](toc.md) | Updated: 2026-07-14

## Purpose

The AI Chat system is the tool-driven DevOps assistant exposed under `/api/ai/*`. It can answer project questions and execute safe project operations through registered Python tools.

This is separate from workspace edit chat (`/chat`, `/chat/stream`) and separate from Prompt Assistant (`/ai/completion`).

Telegram can bridge from DevOps chat into a selected project session. Once a Telegram project session is selected, normal Telegram messages bypass general DevOps tool chat and route to the same project session edit handler used by web session chat.

## Main Files

| File | Responsibility |
| --- | --- |
| `api/ai_chat.py` | Main chat endpoint, system prompt, orchestration |
| `api/ai_selection.py` | Handles project/tool selection responses |
| `api/ai_confirm.py` | Handles confirmation for destructive actions |
| `services/ai/glm_client.py` | GLM tool-calling client |
| `services/ai/tool_registry.py` | Tool schemas and confirmation policy |
| `services/ai/tool_executor.py` | Direct Python execution of tools |
| `services/ai/project_resolver.py` | Project ID/domain/name resolution |
| `utils/ai_session_manager.py` | Session state and active project tracking |
| `utils/devops_session_context.py` | Active project-session context shared with Telegram |
| `utils/ai_response_formatter.py` | Response shape helpers |

## Provider

`services/ai/glm_client.py` uses:

| Env var | Default |
| --- | --- |
| `Z_AI_API_BASE` | `https://api.z.ai/api/coding/paas/v4` |
| `Z_AI_MODEL` | `glm-4.7-flashx` |
| `Z_AI_API_KEY` | required |

## Endpoints

Prefix: `/api/ai`

| Method | Endpoint | Description |
| --- | --- | --- |
| POST | `/chat` | Main natural-language DevOps chat |
| GET | `/messages` | Message history |
| GET | `/active-project` | Active project context |
| DELETE | `/messages` | Clear message history |
| POST | `/selection` | Continue after selection UI |
| POST | `/confirm` | Continue after confirmation UI |

## POST `/api/ai/chat`

Request:

```json
{
  "session_id": "user-session-uuid",
  "message": "Show logs for panda",
  "active_project": "panda-6wdjoy"
}
```

`active_project` can be a project domain or ID. Domain strings are preferred in tool arguments.

Response types:

| Type | Meaning |
| --- | --- |
| `text` | Natural language answer, no tool execution |
| `execution` | Tool executed successfully or partially |
| `selection` | User must choose a project/tool option |
| `confirmation` | User must confirm a destructive/bulk action |
| `error` | Assistant/tool failure |

## Tool Categories

Auto-executed tools include:

- `start_project`
- `stop_project`
- `restart_project`
- `list_projects`
- `project_status`
- `get_logs`
- `set_active_project`
- `get_active_project`
- `clear_active_project`
- `get_project_info`
- Scheduler read/update/run helpers where safe

Confirmation-required tools include destructive or broad actions such as delete/uninstall and scheduler delete/clear operations.

## Scheduler Awareness

When the active project is a scheduler, the assistant can list, create, update, pause, resume, run, and inspect jobs through scheduler-specific tools. It should not advertise unrelated website/bot features for scheduler projects.

## Telegram Project Sessions

Telegram project session commands are handled by `api/telegram_webhook.py`, not by the web Chat UI. The DevOps context can store one selected project session for the linked user. While that session is active, Telegram messages continue in that session until `/complete`, `/clearsession`, or project switch.

This preserves the same project lock rules as web session chat and avoids running a separate duplicate editor pipeline for Telegram.

## Related

- [ai_chat_architecture.md](./ai_chat_architecture.md)
- [backend_api_reference.md](./backend_api_reference.md)
- [scheduler.md](./scheduler.md)
- [telegram_session_chat.md](./telegram_session_chat.md)
