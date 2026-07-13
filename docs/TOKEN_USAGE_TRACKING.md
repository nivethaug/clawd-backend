# Token Usage Tracking

> [TOC](toc.md) | Updated: 2026-07-14

## Purpose

Token usage tracking records AI consumption for user dashboards, project usage, billing reconciliation, and admin monitoring.

## Main Files

| File | Responsibility |
| --- | --- |
| `services/token_tracker.py` | Record and query token usage |
| `database_postgres.py` | `token_usage` table and migrations |
| `app.py` | Usage endpoints and chat/project wiring |

## Usage Types

Valid usage types:

```text
ai_chat, project_create, ai_completion
```

`record_usage()` skips records with missing or invalid `user_id` because `token_usage.user_id` has a foreign key to `users(id)`. Anonymous Prompt Assistant usage is estimated in `app.py` but skipped by the tracker when `user_id=0`.

## Table Shape

Important columns:

| Column | Description |
| --- | --- |
| `user_id` | User who consumed tokens |
| `project_id` | Optional project |
| `session_id` | Optional session |
| `usage_type` | `ai_chat`, `project_create`, or `ai_completion` |
| `description` | Human-readable event label |
| `input_tokens` | Prompt/input tokens |
| `output_tokens` | Completion/output tokens |
| `total_tokens` | Total tokens |
| `model` | Model name |
| `provider` | Provider name |
| `cost_usd` | Estimated USD cost |
| `operation` | Billing operation code |
| `credits_charged` | Credits charged |
| `duration_ms` | Request duration |

## Recording

Use `record_usage()` for direct recording:

```python
record_usage(
    user_id=1,
    usage_type="ai_chat",
    total_tokens=500,
    project_id=1624,
    session_id=165,
    model="claude-sonnet",
    provider="anthropic",
    operation="ADD_FEATURE",
    credits_charged=2,
)
```

Use `record_from_token_usage_json()` when handlers return token usage JSON. It accepts both snake_case and camelCase token fields.

## Current Wiring

| Path | Status |
| --- | --- |
| Streaming chat/edit | Records assistant message token JSON and `token_usage` row when user/project context exists |
| Non-streaming chat/edit | Records assistant message token JSON and `token_usage` row when user/project context exists |
| Telegram selected-session chat | Records handler token usage after session completion and charges the project owner |
| Website create | Records from `acp_frontend_editor_v2.py` after Claude agent calls |
| Telegram create | Records from `services/telegram/worker.py` after editor enhancement |
| Discord create | Records from `services/discord/worker.py` after editor enhancement |
| Scheduler create | Records from `services/scheduler/worker.py` after executor enhancement |
| Prompt Assistant | Estimates anonymous usage in route code, but tracker skips because there is no authenticated user |

## Query Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/auth/usage` | Current user's usage summary |
| GET | `/projects/{project_id}/usage` | Usage for one project |
| GET | `/admin/usage` | Platform usage summary, admin only |
| GET | `/admin/usage/logs` | Raw usage logs with filters, admin only |

### `/auth/usage`

Query params:

| Param | Default | Description |
| --- | --- | --- |
| `period` | `month` | `day`, `week`, `month`, or `all` |
| `usage_type` | null | Optional usage type filter |

### `/projects/{project_id}/usage`

Query params:

| Param | Default | Description |
| --- | --- | --- |
| `period` | `all` | `day`, `week`, `month`, or `all` |

The project must belong to the current user unless the caller is admin.

### `/admin/usage/logs`

Query params:

| Param | Default | Description |
| --- | --- | --- |
| `user_id` | null | Optional user filter |
| `project_id` | null | Optional project filter |
| `usage_type` | null | Optional usage type filter |
| `limit` | `50` | Clamped to max 200 |
| `offset` | `0` | Pagination offset |

## Related

- [billing.md](./billing.md)
- [chat_stream.md](./chat_stream.md)
- [telegram_session_chat.md](./telegram_session_chat.md)
