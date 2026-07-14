# Session Locking

> [TOC](toc.md) | Updated: 2026-07-14

## Purpose

Session locking prevents concurrent AI edits against the same project. A project can have only one active editing session at a time.

## Main Files

| File | Responsibility |
| --- | --- |
| `services/session_lock_service.py` | Acquire/release project locks and per-session processing flags |
| `app.py` | Lock endpoints, web chat lock enforcement, cancel/status processing cleanup |
| `api/telegram_webhook.py` | Telegram selected-session lock and processing enforcement |
| `api/discord_webhook.py` | Discord selected-session lock and processing enforcement |
| `api/slack_webhook.py` | Slack selected-session lock and processing enforcement |

## Enforcement Points

Both `/chat` and `/chat/stream` acquire a lock before running ACP/code-edit work. Telegram, Discord, and Slack selected-session chat also use the same lock service before routing a message into `acp_chat_handler.py`.

If another session holds the project lock, web routes return `423`. Telegram, Discord, and Slack return a user-facing message that names the active lock holder and asks the user to complete/release that session first.

Example:

```json
{
  "detail": {
    "error": "Another session is active for this project",
    "active_session_id": 165
  }
}
```

## Same-Session Processing Guard

The project lock is intentionally re-entrant for the same session, because users must be able to continue the active editing session. A second guard prevents duplicate messages inside that same session while one edit is already running.

`sessions` stores:

| Column | Purpose |
| --- | --- |
| `processing` | Whether a message is currently running for the session |
| `processing_started_at` | Start time used for stale recovery |
| `processing_channel` | `webchat`, `telegram`, `discord`, `slack`, or another caller label |

Web ACP chat returns `409 session_message_in_progress` when the same session is already processing. Telegram, Discord, and Slack reply with a "Still working..." message and action buttons instead of starting another background task.

The processing flag is cleared when:

- web streaming completes normally
- web background save completes after disconnect
- web Stop/cancel is called
- Telegram, Discord, or Slack selected-session chat finishes
- the flag is detected as stale by `SessionLockService.acquire_processing()`

## Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/projects/{project_id}/active-session` | Return active lock/session info |
| DELETE | `/projects/{project_id}/lock` | Force release project lock |
| POST | `/sessions/{session_id}/release-lock` | Release lock held by a session |

All endpoints require auth and validate project/session ownership.

## Delete Behavior

Deleting a session releases the lock if that session holds it.

## External Bot Behavior

Telegram, Discord, and Slack session chat follow the same one-active-edit-session rule:

- Selecting or creating a project session is blocked when another session owns the project lock.
- Selecting the session that already owns the lock is allowed.
- Sending another message while the same session is processing is blocked by the per-session processing guard.
- `/clearsession` clears bot context only and does not release the lock.
- `/complete` releases the selected session lock through `SessionLockService`.
- Switching the active project clears the selected session context.

## Related

- [chat.md](./chat.md)
- [chat_stream.md](./chat_stream.md)
- [project_sessions.md](./project_sessions.md)
- [telegram_session_chat.md](./telegram_session_chat.md)
- [discord_session_chat.md](./discord_session_chat.md)
- [slack_session_chat.md](./slack_session_chat.md)
