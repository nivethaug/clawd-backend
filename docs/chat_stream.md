# Chat Stream - Complete Reference

> [TOC](toc.md) | Updated: 2026-03-22

---

## API Endpoint

| Endpoint | Method | File | Lines | Description |
|----------|--------|------|-------|-------------|
| `/chat/stream` | POST | `app.py` | 2213-2632 | Streaming chat (SSE) |

---

## POST /chat/stream

Send a chat message and get a streaming response (Server-Sent Events).

### Request

```json
{
  "session_key": "abc123",
  "messages": [
    {"role": "user", "content": "Write a long story"}
  ],
  "stream": true,
  "image": null,
  "acp_mode": true
}
```

### Request Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `session_key` | string | required | Session identifier |
| `messages` | array | required | Array of message objects |
| `stream` | bool | false | Set to `true` for streaming |
| `image` | string | null | Optional base64-encoded image |
| `acp_mode` | bool | true | Enable ACP mode for frontend editing |

### Response

Returns **Server-Sent Events (SSE)** stream:

```
data: {"choices": [{"delta": {"content": "Once"}}]}

data: {"choices": [{"delta": {"content": " upon"}}]}

data: {"choices": [{"delta": {"content": " a time..."}}]}

data: [DONE]
```

### Error Response

```
data: {"error": "Error message here"}

data: [DONE]
```

---

## Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    POST /chat/stream                            │
└─────────────────────────────────────────────────────────────────┘
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
│    • INSERT INTO messages (session_id, role, content)           │
│    • COMMIT immediately                                         │
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
│     • Query last 4 messages from database                       │
│     • Replace base64 images with placeholder text               │
│     • Format as: "ROLE: content"                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ A4. PREPROCESSOR CHECK                                          │
│     • check_preprocessor(user_content, project_name, path)      │
│     • Fast LLM decides if ACPX is needed                        │
│     • If direct_response: return immediately (skip ACPX)        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (if preprocessor didn't handle)
┌─────────────────────────────────────────────────────────────────┐
│ A5. UNIFIED STREAMING (ClaudeCodeAgent or ACPX fallback)        │
│     • handler.run_chat_streaming_unified(content, context)      │
│     • Yields chunks in real-time                                │
│     • Each chunk wrapped as SSE event                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ A6. SAVE ASSISTANT MESSAGE                                      │
│     • INSERT INTO messages (session_id, 'assistant', content)   │
│     • UPDATE sessions SET last_used_at = CURRENT_TIMESTAMP      │
│     • COMMIT                                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ A7. CLEANUP                                                      │
│     • Delete temp image file if exists                          │
│     • Yield "data: [DONE]\n\n"                                  │
└─────────────────────────────────────────────────────────────────┘
```

### ACP Mode: Client Disconnect Handling

```
┌─────────────────────────────────────────────────────────────────┐
│ CLIENT DISCONNECTED (asyncio.CancelledError)                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ SPAWN BACKGROUND TASK: wait_and_save()                          │
│   • Poll every 5 seconds for up to 10 minutes                   │
│   • Check handler._last_query_chunks for real content           │
│   • Check handler._last_query_response for direct response      │
│   • Save to database when content available                     │
│   • Fallback: save partial content on timeout                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Non-ACP Mode Flow (acp_mode=false)

```
┌─────────────────────────────────────────────────────────────────┐
│ N1. INJECT SYSTEM CONTEXT                                       │
│     • ContextInjector.inject_system_context()                   │
│     • Adds project metadata to messages                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ N2. CALL OPENCLAW API                                           │
│     • POST to CLAWDBOT_BASE_URL/v1/chat/completions             │
│     • model: "agent:main"                                       │
│     • stream: false (non-streaming request)                     │
│     • timeout: 120 seconds                                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ N3. SAVE RESPONSE                                               │
│     • Save to StreamState.content                               │
│     • save_stream_to_db(state)                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ N4. RETURN AS SSE STREAM                                        │
│     • Single event with full content                            │
│     • Yield "data: [DONE]\n\n"                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Database Operations

### User Message Save (Step 2)

```sql
INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)
-- Commits immediately to ensure persistence
```

### Assistant Message Save (ACP Mode - Step A6)

```sql
INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?);
UPDATE sessions SET last_used_at = CURRENT_TIMESTAMP WHERE id = ?;
-- Commits after streaming completes
```

### Context Load (Step A3)

```sql
SELECT role, content, image FROM messages 
WHERE session_id = ? 
ORDER BY created_at DESC LIMIT 4
```

---

## Response Headers

```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

---

## Client Example

```javascript
const response = await fetch('/chat/stream', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    session_key: 'abc123',
    messages: [{ role: 'user', content: 'Hello' }],
    stream: true,
    acp_mode: true
  })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  
  const chunk = decoder.decode(value);
  const lines = chunk.split('\n');
  
  for (const line of lines) {
    if (line.startsWith('data: ')) {
      const data = line.slice(6);
      if (data === '[DONE]') break;
      
      const parsed = JSON.parse(data);
      const content = parsed.choices?.[0]?.delta?.content || '';
      console.log(content);
    }
  }
}
```

---

## Error Handling

| Error Type | Response |
|------------|----------|
| Session not found | `404 {"detail": "Session not found"}` |
| No user message | `400 {"detail": "No user message provided"}` |
| ACP handler failed | SSE stream with `{"error": "..."}` |
| OpenClaw API error | SSE stream with `{"error": "..."}` |
| Streaming exception | SSE stream with `{"error": "..."}` |

---

## Key Differences: /chat/stream vs /chat

| Feature | /chat/stream | /chat |
|---------|--------------|-------|
| Response format | SSE stream | JSON object |
| Real-time output | Yes | No |
| Client disconnect | Background save | N/A |
| ACP mode | Streaming chunks | Single response |
| Timeout | 900s (ACP) / 120s (non-ACP) | 300s |

---

## Related

- [Chat (Non-Streaming)](chat.md)
- [AI Completion](ai_completion.md)
- [Project Sessions](project_sessions.md)
- [Message Persistence Guarantee](message-persistence-guarantee.md)
