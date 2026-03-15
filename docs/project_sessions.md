# Project Sessions - Complete Reference

> [TOC](toc.md) | [SKILL.md](../.agents/skills/project-info/SKILL.md) | Updated: 2026-03-15

---

## API Endpoints

| Endpoint | Method | File | Lines | Description |
|----------|--------|------|-------|-------------|
| `/projects/{id}/sessions` | GET | `app.py` | 1882-1903 | List project sessions |
| `/projects/{id}/sessions` | POST | `app.py` | 1905-1945 | Create session |
| `/projects/{id}/sessions/{sid}` | DELETE | `app.py` | 1956-2020 | Delete session |
| `/sessions/{sid}` | DELETE | `app.py` | 1948-1954 | Delete session (alt) |
| `/sessions/{sid}/messages` | GET | `app.py` | 2019-2035 | Get session messages |
| `/sessions/details` | GET | `app.py` | 2302-2415 | Get session details |

---

## GET /projects/{id}/sessions

**File:** `app.py:1882-1903`

List all sessions for a project.

**Response:**
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

## POST /projects/{id}/sessions

**File:** `app.py:1905-1945`

Create a new session.

**Request:**
```json
{
  "label": "My Session"
}
```

**Response:**
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

## DELETE /projects/{id}/sessions/{sid}

**File:** `app.py:1957-1975`

Delete a session.

**Response:**
```json
{
  "success": true,
  "message": "Session deleted"
}
```

---

## GET /sessions/{sid}/messages

**File:** `app.py:2019-2035`

Get all messages in a session.

**Response:**
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

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `session_key` | string | Session key to look up |

**Response:**
```json
{
  "session": {...},
  "messages": [...],
  "project": {...}
}
```

---

## Related

- [Chat](chat.md)
- [Chat Stream](chat_stream.md)
