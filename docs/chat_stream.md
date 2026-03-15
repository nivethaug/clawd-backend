# Chat Stream - Complete Reference

> [TOC](toc.md) | [SKILL.md](../.agents/skills/project-info/SKILL.md) | Updated: 2026-03-15

---

## API Endpoints

| Endpoint | Method | File | Lines | Description |
|----------|--------|------|-------|-------------|
| `/chat/stream` | POST | `app.py` | 2038-2081 | Streaming chat (SSE) |

---

## POST /chat/stream

**File:** `app.py:2038-2081`

Send a chat message and get a streaming response (Server-Sent Events).

**Request:**
```json
{
  "session_key": "abc123",
  "messages": [
    {"role": "user", "content": "Write a long story"}
  ],
  "stream": true,
  "image": null
}
```

**Request Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `session_key` | string | Session identifier |
| `messages` | array | Array of message objects |
| `stream` | bool | Set to `true` for streaming |
| `image` | string | Optional base64-encoded image |

**Response:**

Returns **Server-Sent Events (SSE)** stream:

```
data: {"content": "Once"}

data: {"content": " upon"}

data: {"content": " a"}

data: {"content": " time..."}

data: [DONE]
```

---

## Flow

| Step | Description |
|------|-------------|
| 1 | Validate session exists |
| 2 | Create SSE stream generator |
| 3 | Stream tokens as they're generated |
| 4 | Save complete message to database |
| 5 | Send `[DONE]` event |

---

## Client Example

```javascript
const response = await fetch('/chat/stream', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    session_key: 'abc123',
    messages: [{ role: 'user', content: 'Hello' }],
    stream: true
  })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  
  const chunk = decoder.decode(value);
  // Parse SSE data: lines starting with "data: "
}
```

---

## Related

- [Chat](chat.md)
- [AI Completion](ai_completion.md)
