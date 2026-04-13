# Chat Stream - Complete Reference

> [TOC](toc.md) | Updated: 2026-03-22

---

## API Endpoints

| Endpoint | Method | File | Description |
|----------|--------|------|-------------|
| `/chat/stream` | POST | `app.py` | Streaming chat (SSE) |
| `/chat/cancel` | POST | `app.py` | Cancel running query (kills Claude process) |
| `/chat/status` | GET | `app.py` | Check if query is running (for reload detection) |
| `/chat/chunks` | GET | `app.py` | Poll accumulated response chunks (for resume after reload) |

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

## Cancel & Status API

### Active Handler Registry

When a streaming chat starts, the handler is registered in a global dict:

```python
active_handlers: Dict[str, ACPChatHandler] = {}  # session_key -> handler
```

- **Added** when streaming begins (`/chat/stream` step A5)
- **Kept** if client disconnects but query still running (for reload detection)
- **Removed** when query completes or is cancelled
- **Delayed cleanup** after 10 minutes for abandoned queries

### POST /chat/cancel

Cancel a running query. Kills the Claude subprocess immediately.

**Request:**

```json
{
  "session_key": "abc123"
}
```

**Response:**

```json
{"success": true, "message": "Query cancelled"}
```

**How it works:**

```
┌─────────────────────────────────────────────────────────────────┐
│ POST /chat/cancel                                               │
│   1. Look up handler in active_handlers by session_key          │
│   2. handler.cancel_query()                                     │
│      ├─ agent.cancel() → os.killpg(pid, SIGKILL)               │
│      │   (kills entire process group: parent + children)        │
│      ├─ _query_complete.set() (unblock background save)        │
│      └─ _active_agent = None                                    │
│   3. Remove handler from active_handlers                        │
└─────────────────────────────────────────────────────────────────┘
```

**Process group kill:** The Claude CLI subprocess is created with `start_new_session=True`, putting it in its own process group. `cancel()` uses `os.killpg()` to kill the entire group (parent CLI + child inference workers), not just the parent process.

### GET /chat/status

Check if a query is running. Used by frontend on page reload.

**Request:**

```
GET /chat/status?session_key=abc123
```

**Response (active):**

```json
{"active": true, "session_key": "abc123"}
```

**Response (inactive):**

```json
{"active": false, "session_key": "abc123"}
```

### GET /chat/chunks

Poll for accumulated response chunks. Used by frontend to resume streaming after page reload.

**Request:**

```
GET /chat/chunks?session_key=abc123&after=0
```

| Param | Type | Description |
|-------|------|-------------|
| `session_key` | string | Session identifier |
| `after` | int | Chunk index to start from (default 0) |

**Response:**

```json
{
  "chunks": ["Once upon", " a time", "..."],
  "total": 15,
  "active": true
}
```

| Field | Type | Description |
|-------|------|-------------|
| `chunks` | string[] | New chunks since `after` index (noise filtered) |
| `total` | int | Total chunks accumulated |
| `active` | bool | Whether query is still running |

**Filtering:** Chunks prefixed with `PROGRESS:`, `TOOL:`, or containing JSON/telemetry are excluded. Only clean text content is returned.

---

## Reload Detection Flow

When the user reloads the page during an active query:

```
┌─────────────────────────────────────────────────────────────────┐
│ PAGE RELOAD                                                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. Frontend: checkBackgroundQuery()                             │
│    • GET /chat/status?session_key=abc123                        │
│    • If active: show loading state + Stop button                │
│    • Add placeholder assistant message (isStreaming: true)      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ (if active)
┌─────────────────────────────────────────────────────────────────┐
│ 2. Frontend: Poll for chunks every 15 seconds                   │
│    • GET /chat/chunks?session_key=abc123&after=N                │
│    • Append new chunks to streaming message                     │
│    • When active=false: reload full messages from DB            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Stop Button Flow (Frontend)

```
┌─────────────────────────────────────────────────────────────────┐
│ USER CLICKS STOP BUTTON                                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. Abort SSE connection                                         │
│    • abortControllerRef.current.abort()                         │
│    • Breaks the EventSource/fetch stream                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. Cancel backend query                                         │
│    • POST /chat/cancel { session_key }                          │
│    • Kills Claude process group on server                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. Update UI state                                              │
│    • Mark streaming messages as complete (isStreaming: false)   │
│    • Set isLoading = false                                      │
│    • Re-enable chat input                                       │
│    • Stop button → Send button                                  │
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
| Cancel: no active query | `200 {"success": false, "message": "No active query found"}` |
| Cancel: handler error | `200 {"success": false, "message": "Error cancelling: ..."}` |
| Cancel: success | `200 {"success": true, "message": "Query cancelled"}` |

---

## Key Differences: /chat/stream vs /chat

| Feature | /chat/stream | /chat |
|---------|--------------|-------|
| Response format | SSE stream | JSON object |
| Real-time output | Yes | No |
| Client disconnect | Background save | N/A |
| Cancel support | POST /chat/cancel | N/A |
| Reload detection | GET /chat/status + /chat/chunks | N/A |
| ACP mode | Streaming chunks | Single response |
| Timeout | 1800s (ACP) / 120s (non-ACP) | 300s |

---

## Related

- [Chat (Non-Streaming)](chat.md)
- [AI Completion](ai_completion.md)
- [Project Sessions](project_sessions.md)
- [Message Persistence Guarantee](message-persistence-guarantee.md)
