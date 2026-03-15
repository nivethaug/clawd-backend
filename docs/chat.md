# Chat API

> [TOC](toc.md) | [SKILL.md](../.agents/skills/project-info/SKILL.md) | Updated: 2026-03-15

---

## Endpoint

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/chat` | POST | Chat completion (non-streaming) |

---

## Chat Request

```
POST /chat
```

**Request Body:**
```json
{
  "session_key": "abc123",
  "messages": [
    {"role": "user", "content": "Hello"}
  ],
  "stream": false,
  "image": null
}
```

**Response:**
```json
{
  "id": 1,
  "role": "assistant",
  "content": "Hello! How can I help you?",
  "created_at": "2026-03-15T10:00:00"
}
```

**File:** `app.py:800-950`

---

## Handler Functions

| Function | File | Lines |
|----------|------|-------|
| `generate_sse_stream()` | `chat_handlers.py` | 50-200 |
| `generate_sse_stream_with_db_save()` | `chat_handlers.py` | 200-350 |
| `handle_chat_with_image()` | `chat_handlers.py` | 350-450 |
| `handle_chat_text_only()` | `chat_handlers.py` | 450-550 |

---

## Models Used

| Model | Type | Description |
|-------|------|-------------|
| `zai/glm-4.6v` | IMAGE_MODEL | Vision model for image input |
| `agent:main` | TEXT_MODEL | Text completion model |

---

## Related

- [Chat Stream](chat_stream.md)
- [AI Completion](ai_completion.md)
- [Project Session](project_session.md)
