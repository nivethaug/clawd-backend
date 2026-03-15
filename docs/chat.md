# Chat - Complete Reference

> [TOC](toc.md) | [SKILL.md](../.agents/skills/project-info/SKILL.md) | Updated: 2026-03-15

---

## API Endpoints

| Endpoint | Method | File | Lines | Description |
|----------|--------|------|-------|-------------|
| `/chat` | POST | `app.py` | 2081-2155 | Chat completion (non-streaming) |

---

## POST /chat

**File:** `app.py:2081-2155`

Send a chat message and get a response (non-streaming).

**Request:**
```json
{
  "session_key": "abc123",
  "messages": [
    {"role": "user", "content": "Hello, how are you?"}
  ],
  "stream": false,
  "image": null
}
```

**Request Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `session_key` | string | Session identifier |
| `messages` | array | Array of message objects |
| `stream` | bool | Set to `false` for non-streaming |
| `image` | string | Optional base64-encoded image |

**Response:**
```json
{
  "id": 123,
  "role": "assistant",
  "content": "I'm doing well, thank you for asking!",
  "created_at": "2026-03-15T10:00:05"
}
```

---

## Flow

| Step | Description |
|------|-------------|
| 1 | Validate session exists |
| 2 | Check for image in request |
| 3 | If image: use `handle_chat_with_image()` |
| 4 | If text only: use `handle_chat_text_only()` |
| 5 | Save message to database |
| 6 | Return response |

---

## Related

- [Chat Stream](chat_stream.md)
- [AI Completion](ai_completion.md)
- [Project Sessions](project_sessions.md)
