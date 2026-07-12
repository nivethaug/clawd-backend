# Recent Activity API

> [TOC](toc.md) | Updated: 2026-07-12

## Purpose

Recent Activity APIs return projects ordered by latest session message, plus session/message counts and active lock state.

All endpoints require `Authorization: Bearer <token>`.

## Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/projects/recent-activity` | Paginated activity list with optional preview |
| GET | `/projects/recent-activity/simple` | Lightweight activity list without preview |
| GET | `/projects/{project_id}/activity` | Detailed activity for one project |

## GET `/projects/recent-activity`

Query params:

| Param | Default | Description |
| --- | --- | --- |
| `limit` | `20` | Clamped to 1-100 |
| `offset` | `0` | Pagination offset |
| `include_preview` | `true` | Include `last_message_preview` |

Response:

```json
{
  "items": [
    {
      "project_id": 1624,
      "project_name": "check",
      "project_description": "VPS health dashboard",
      "project_status": "ready",
      "domain": "check.dreamagent.cloud",
      "last_activity": "2026-07-12T10:00:00Z",
      "total_messages": 8,
      "total_sessions": 2,
      "last_message_preview": "Fix spacing in the screenshot",
      "last_session_id": 165,
      "last_session_label": "Hero polish",
      "active_session_id": null
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

The optimized query uses PostgreSQL `DISTINCT ON`, joins sessions/messages, and truncates previews to 100 characters.

## GET `/projects/recent-activity/simple`

Query params:

| Param | Default | Description |
| --- | --- | --- |
| `limit` | `20` | Clamped to 1-100 |

Response:

```json
{
  "items": [
    {
      "project_id": 1624,
      "project_name": "check",
      "project_status": "ready",
      "active_session_id": null,
      "last_activity": "2026-07-12T10:00:00Z",
      "total_sessions": 2,
      "total_messages": 8
    }
  ],
  "count": 1
}
```

## GET `/projects/{project_id}/activity`

Query params:

| Param | Default | Description |
| --- | --- | --- |
| `message_limit` | `10` | Clamped to 1-50 |

Response:

```json
{
  "project_id": 1624,
  "project_name": "check",
  "description": "VPS health dashboard",
  "status": "ready",
  "domain": "check.dreamagent.cloud",
  "active_session_id": null,
  "last_activity": "2026-07-12T10:00:00Z",
  "total_sessions": 2,
  "total_messages": 8,
  "recent_messages": [
    {
      "id": 123,
      "session_id": 165,
      "session_label": "Hero polish",
      "role": "assistant",
      "content": "Done.",
      "created_at": "2026-07-12T10:00:00Z"
    }
  ]
}
```

## Indexes

`recent_activity_service.py` creates safe `IF NOT EXISTS` indexes for:

- `messages(session_id, created_at DESC)`
- `sessions(project_id)`
- `projects(user_id)`
- `messages(session_id, role, created_at DESC)`

## Related

- [dashboard.md](./dashboard.md)
- [session_locking.md](./session_locking.md)
