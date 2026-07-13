# Project Sessions

> [TOC](toc.md) | Updated: 2026-07-14

## Purpose

Sessions group chat messages and edit/plan conversations for a project. Session routes are authenticated and scoped to the project owner.

## Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/projects/{project_id}/sessions` | List non-archived sessions for a project |
| POST | `/projects/{project_id}/sessions` | Create a new session |
| DELETE | `/sessions/{session_id}` | Delete a session by ID |
| DELETE | `/projects/{project_id}/sessions/{session_id}` | Delete a session inside a project |
| GET | `/sessions/{session_id}/messages` | Return all messages for a session |
| GET | `/sessions/details` | Return details for a session key |

## Auth

All endpoints require `Authorization: Bearer <token>`.

- Project-scoped routes call `_require_project_owner()`.
- Session-scoped routes call `_require_session_owner()`.
- Message reads only return messages for sessions owned by the authenticated user.

## Create Session

```json
{
  "label": "Hero polish"
}
```

Response:

```json
{
  "id": 165,
  "project_id": 1624,
  "session_key": "08e68d65-2101-489b-be00-710746487e31",
  "label": "Hero polish",
  "archived": 0,
  "scope": null,
  "channel": "webchat",
  "agent_id": "main",
  "created_at": "2026-07-12 10:00:00",
  "last_used_at": null
}
```

`channel` and `agent_id` are currently created from backend defaults.

## Telegram Session Selection

Linked Telegram users can select an existing project session with `/sessions` or create one with `/newsession LABEL`. Once selected, normal Telegram messages are appended to the same `messages` table and routed through the same `acp_chat_handler.py` flow used by web session chat.

Telegram does not create a duplicate edit system per project type. The selected session's `project_type_id` controls the prompt builder inside `ACPChatHandler`:

- Website sessions use the website edit prompt.
- Telegram bot sessions use the Telegram bot edit prompt.
- Discord bot sessions use the Discord bot edit prompt.
- Scheduler sessions use the scheduler edit prompt.

See [telegram_session_chat.md](./telegram_session_chat.md) for the full command and lock behavior.

## Delete Session

Both delete routes remove:

- The session row
- Messages for that session
- Any active session lock held by that session

The project-scoped delete route also attempts to remove matching OpenClaw session metadata and JSONL transcript files.

Response:

```json
{
  "status": "deleted",
  "message": "Session deleted"
}
```

## Messages

`GET /sessions/{session_id}/messages` returns messages ordered oldest-first.

```json
[
  {
    "id": 1,
    "role": "user",
    "content": "Check this screenshot",
    "image": "data:image/webp;base64,...",
    "created_at": "2026-07-12 10:00:00",
    "commit_hash": null,
    "commit_status": null,
    "reverted_message_id": null
  }
]
```

Images are stored on user messages when uploaded. Assistant messages may include commit metadata when a chat edit produces a commit.

## Related

- [chat.md](./chat.md)
- [chat_stream.md](./chat_stream.md)
- [session_locking.md](./session_locking.md)
- [telegram_session_chat.md](./telegram_session_chat.md)
