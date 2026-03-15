# Project Sessions API

> [TOC](toc.md) | Updated: 2026-03-15

---

## Endpoints

| Endpoint | Method | File | Lines |
|----------|--------|------|-------|
| `/projects/{project_id}/sessions` | GET | `app.py` | 1882-1900 |
| `/projects/{project_id}/sessions` | POST | `app.py` | 1903-1945 |
| `/projects/{project_id}/sessions/{session_id}` | DELETE | `app.py` | 1957-1975 |
| `/sessions/{session_id}` | DELETE | `app.py` | 1948-1955 |
| `/sessions/{session_id}/messages` | GET | `app.py` | 2019-2035 |
| `/sessions/details` | GET | `app.py` | 2302-2415 |

---

## GET /projects/{project_id}/sessions

**File:** `app.py:1882-1900`

List all sessions for a project.

### Response

```json
[
  {
    "id": 1,
    "project_id": 123,
    "session_key": "abc123",
    "label": "Main Chat",
    "archived": 0,
    "channel": "webchat",
    "agent_id": "main",
    "created_at": "2026-03-15T10:00:00"
  }
]
```

---

## POST /projects/{project_id}/sessions

**File:** `app.py:1903-1945`

Create a new session.

### Request Body

```json
{
  "label": "My Session"
}
```

### Response

```json
{
  "id": 2,
  "project_id": 123,
  "session_key": "xyz789",
  "label": "My Session",
  "created_at": "2026-03-15T10:05:00"
}
```

---

## DELETE /projects/{project_id}/sessions/{session_id}

**File:** `app.py:1957-1975`

Delete a session.

### Response

```json
{
  "success": true,
  "message": "Session deleted"
}
```

---

## GET /sessions/{session_id}/messages

**File:** `app.py:2019-2035`

Get all messages in a session.

### Response

```json
[
  {
    "id": 1,
    "role": "user",
    "content": "Hello",
    "created_at": "2026-03-15T10:00:00"
  },
  {
    "id": 2,
    "role": "assistant",
    "content": "Hi there!",
    "created_at": "2026-03-15T10:00:05"
  }
]
```

---

## GET /sessions/details

**File:** `app.py:2302-2415`

Get detailed session information.

### Query Parameters

| Param | Type | Description |
|-------|------|-------------|
| `session_key` | string | Session key to look up |

### Response

```json
{
  "session": {...},
  "messages": [...],
  "project": {...}
}
```

---

## Related

- [Chat API](chat.md)
- [Chat Stream API](chat_stream.md)
