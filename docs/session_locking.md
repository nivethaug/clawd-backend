# Session Locking

> [TOC](toc.md) | Updated: 2026-07-14

## Purpose

Session locking prevents concurrent AI edits against the same project. A project can have only one active editing session at a time.

## Main Files

| File | Responsibility |
| --- | --- |
| `services/session_lock_service.py` | Acquire/release lock helpers |
| `app.py` | Lock endpoints and chat lock enforcement |

## Enforcement Points

Both `/chat` and `/chat/stream` acquire a lock before running ACP/code-edit work. Telegram selected-session chat also uses the same lock service before routing a message into `acp_chat_handler.py`.

If another session holds the project lock, web routes return `423`. Telegram returns a user-facing message that names the active lock holder and asks the user to complete/release that session first.

Example:

```json
{
  "detail": {
    "error": "Another session is active for this project",
    "active_session_id": 165
  }
}
```

## Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/projects/{project_id}/active-session` | Return active lock/session info |
| DELETE | `/projects/{project_id}/lock` | Force release project lock |
| POST | `/sessions/{session_id}/release-lock` | Release lock held by a session |

All endpoints require auth and validate project/session ownership.

## Delete Behavior

Deleting a session releases the lock if that session holds it.

## Telegram Behavior

Telegram session chat follows the same one-active-edit-session rule:

- Selecting or creating a Telegram project session is blocked when another session owns the project lock.
- Selecting the session that already owns the lock is allowed.
- `/clearsession` clears Telegram context only and does not release the lock.
- `/complete` releases the selected session lock through `SessionLockService`.
- Switching the active project clears the selected session context.

## Related

- [chat.md](./chat.md)
- [chat_stream.md](./chat_stream.md)
- [project_sessions.md](./project_sessions.md)
- [telegram_session_chat.md](./telegram_session_chat.md)
