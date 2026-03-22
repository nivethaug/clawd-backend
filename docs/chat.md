# Chat - Complete Reference

> [TOC](toc.md) | Updated: 2026-03-22

---

## API Endpoint

| Endpoint | Method | File | Lines | Description |
|----------|--------|------|-------|-------------|
| `/chat` | POST | `app.py` | 2635-2836 | Chat completion (non-streaming) |

---

## POST /chat

Send a chat message and get a complete response (non-streaming).

### Request

```json
{
  "session_key": "abc123",
  "messages": [
    {"role": "user", "content": "Hello, how are you?"}
  ],
  "stream": false,
  "image": null,
  "acp_mode": true
}
```

### Request Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `session_key` | string | required | Session identifier |
| `messages` | array | required | Array of message objects |
| `stream` | bool | false | Set to `false` for non-streaming |
| `image` | string | null | Optional base64-encoded image |
| `acp_mode` | bool | true | Enable ACP mode for frontend editing |

### Response

```json
{
  "id": 0,
  "role": "assistant",
  "content": "I'm doing well, thank you for asking!",
  "created_at": "2026-03-22T10:00:05"
}
```

### Error Response

```json
{
  "id": 0,
  "role": "assistant",
  "content": "Error: Unable to process request. Please try again. (Details: ...)",
  "created_at": "2026-03-22T10:00:05"
}
```

---

## Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         POST /chat                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │ stream=true?    │
                    └─────────────────┘
                     │              │
                    YES             NO
                     │              │
                     ▼              ▼
    ┌────────────────────────┐  ┌────────────────────────┐
    │ Delegate to /chat/stream│  │ Continue non-streaming│
    └────────────────────────┘  └────────────────────────┘
                                              │
                                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. VALIDATE SESSION                                             │
│    • Query: SELECT * FROM sessions WHERE session_key = ?        │
│    • Return 404 if not found                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. SAVE USER MESSAGE                                            │
│    • If image: INSERT with image field                          │
│    • Else: INSERT without image                                 │
│    • COMMIT immediately (guarantees persistence)                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │  acp_mode=true? │
                    └─────────────────┘
                     │              │
                    YES             NO
                     │              │
                     ▼              ▼
    ┌────────────────────────┐  ┌────────────────────────┐
    │    ACP MODE FLOW       │  │  NON-ACP MODE FLOW     │
    └────────────────────────┘  └────────────────────────┘
```

---

## ACP Mode Flow (acp_mode=true)

```
┌─────────────────────────────────────────────────────────────────┐
│ A1. INITIALIZE ACP HANDLER                                      │
│     • get_acp_chat_handler(session_key)                         │
│     • Validates project path exists                             │
│     • Returns error if project not found                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ A2. HANDLE IMAGE (if present)                                   │
│     • Decode base64 image                                       │
│     • Save to /tmp/acp_images/{session_id}_{uuid}.png           │
│     • Append image path to user content                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ A3. LOAD SESSION CONTEXT                                        │
│     • Query last 10 messages from database                      │
│     • Replace base64 images with placeholder text               │
│     • Format as: "ROLE: content"                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ A4. RUN ACPX (SYNCHRONOUS)                                      │
│     • handler.run_acpx_chat(user_content, session_context)      │
│     • timeout: 300 seconds                                      │
│     • Returns: {success, response, status, error}               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ A5. KILL ORPHAN PROCESSES                                       │
│     • handler.kill_orphan_processes()                           │
│     • Cleanup any lingering ACPX node processes                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ A6. CLEANUP TEMP FILES                                          │
│     • Delete temp image file if exists                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ A7. SAVE ASSISTANT MESSAGE                                      │
│     • INSERT INTO messages (session_id, 'assistant', content)   │
│     • UPDATE sessions SET last_used_at = CURRENT_TIMESTAMP      │
│     • COMMIT                                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ A8. RETURN ChatResponse                                         │
│     • id: 0                                                     │
│     • role: "assistant"                                         │
│     • content: assistant_content                                │
│     • created_at: ISO timestamp                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Non-ACP Mode Flow (acp_mode=false)

```
┌─────────────────────────────────────────────────────────────────┐
│ N1. CHECK FOR IMAGE                                             │
│     • If image: handle_chat_with_image()                        │
│     • If text only: handle_chat_text_only()                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ N2. CALL AI SERVICE                                             │
│     • GroqService or Clawdbot API                               │
│     • Returns assistant content                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ N3. SAVE ASSISTANT MESSAGE                                      │
│     • INSERT INTO messages (session_id, 'assistant', content)   │
│     • UPDATE sessions SET last_used_at = CURRENT_TIMESTAMP      │
│     • COMMIT (GUARANTEED even on error)                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ N4. RETURN ChatResponse                                         │
│     • id: 0                                                     │
│     • role: "assistant"                                         │
│     • content: assistant_content (or error message)             │
│     • created_at: ISO timestamp                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Database Operations

### User Message Save (Step 2)

```sql
-- With image
INSERT INTO messages (session_id, role, content, image) VALUES (?, ?, ?, ?);

-- Without image
INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?);

-- Commits immediately to guarantee persistence
```

### Context Load (ACP Mode - Step A3)

```sql
SELECT role, content, image FROM messages 
WHERE session_id = ? 
ORDER BY created_at DESC LIMIT 10
```

### Assistant Message Save (Step A7/N3)

```sql
INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?);
UPDATE sessions SET last_used_at = CURRENT_TIMESTAMP WHERE id = ?;
-- Commits after response received
```

---

## Response Model

```python
class ChatResponse(BaseModel):
    id: int                    # Always 0 (no DB ID returned)
    role: str                  # "assistant"
    content: str               # Full response text
    created_at: str            # ISO 8601 timestamp
```

---

## Error Handling

| Error Type | Behavior |
|------------|----------|
| Session not found | `404 {"detail": "Session not found"}` |
| No user message | `400 {"detail": "No user message provided"}` |
| ACP handler failed | Returns error message as content |
| AI service error | Returns error message as content |
| Any exception | Catches, saves error to DB, returns as content |

### Error Message Format

```json
{
  "id": 0,
  "role": "assistant",
  "content": "Error: Unable to process request. Please try again. (Details: connection timeout)",
  "created_at": "2026-03-22T10:00:05"
}
```

---

## Key Differences: /chat vs /chat/stream

| Feature | /chat | /chat/stream |
|---------|-------|--------------|
| Response format | JSON object | SSE stream |
| Real-time output | No | Yes |
| Client disconnect | N/A | Background save |
| ACP mode | Synchronous (300s) | Streaming (900s) |
| Context messages | 10 | 4 |
| Returns on error | Error in content | SSE error event |

---

## Client Example

```javascript
const response = await fetch('/chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    session_key: 'abc123',
    messages: [{ role: 'user', content: 'Hello' }],
    stream: false,
    acp_mode: true
  })
});

const data = await response.json();
console.log(data.content);
// Output: "I'm doing well, thank you for asking!"
```

---

## Related

- [Chat Stream](chat_stream.md)
- [AI Completion](ai_completion.md)
- [Project Sessions](project_sessions.md)
- [Message Persistence Guarantee](message-persistence-guarantee.md)
