# Session Locking

> [TOC](toc.md) | Updated: 2026-07-12

## Purpose

Session locking prevents concurrent AI edits against the same project. A project can have only one active editing session at a time.

## Main Files

| File | Responsibility |
| --- | --- |
| `services/session_lock_service.py` | Acquire/release lock helpers |
| `app.py` | Lock endpoints and chat lock enforcement |

## Enforcement Points

Both `/chat` and `/chat/stream` acquire a lock before running ACP/code-edit work. If another session holds the project lock, the backend returns `423`.

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

## Related

- [chat.md](./chat.md)
- [chat_stream.md](./chat_stream.md)
- [project_sessions.md](./project_sessions.md)
