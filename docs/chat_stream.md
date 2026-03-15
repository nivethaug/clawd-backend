# Chat Stream API

> [TOC](toc.md) | [SKILL.md](../.agents/skills/project-info/SKILL.md) | Updated: 2026-03-15

---

## Endpoint

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/chat/stream` | POST | Streaming chat completion (SSE) |

---

## Stream Request

```
POST /chat/stream
```

**Request Body:**
```json
{
  "session_key": "abc123",
  "messages": [
    {"role": "user", "content": "Write a function"}
  ],
  "stream": true,
  "image": null
}
```

**Response:** Server-Sent Events (SSE)

```
data: {"content": "Here"}
data: {"content": " is"}
data: {"content": " the"}
data: {"content": " function"}
data: [DONE]
```

**File:** `app.py:950-1100`

---

## SSE Format

| Event | Description |
|-------|-------------|
| `data: {"content": "..."}` | Text chunk |
| `data: [DONE]` | Stream complete |
| `data: {"error": "..."}` | Error occurred |

---

## Handler

```python
# chat_handlers.py
async def generate_sse_stream(messages, session_key, image=None):
    """Generate SSE stream from AI model"""
    ...
```

---

## Related

- [Chat](chat.md)
- [AI Completion](ai_completion.md)
