# ACP Chat Mode - Frontend Editing via Chat

## Overview

ACP Chat Mode allows users to edit frontend source files through natural language conversation. When `acp_mode=True` is sent in a chat request, the system routes to `claude-acp` which has file system tools to read/write/edit source code.

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌──────────────┐     ┌────────────┐
│   Client    │────▶│   app.py    │────▶│ acp_chat_    │────▶│  ACPX      │
│  (frontend) │     │ /chat/stream│     │ handler.py   │     │  claude    │
└─────────────┘     └─────────────┘     └──────────────┘     └────────────┘
       │                  │                    │                    │
       │                  │                    │                    │
       │                  ▼                    ▼                    ▼
       │           ┌─────────────┐     ┌──────────────┐     ┌────────────┐
       │           │  Database   │     │   Project    │     │  File      │
       │           │  (history)  │     │   src/       │     │  Edits     │
       │           └─────────────┘     └──────────────┘     └────────────┘
       │                  │
       └──────────────────┘
         (messages saved)
```

## Flow

1. **Client Request**: POST `/api/chat/stream` with `acp_mode: true`
2. **Save User Message**: Insert user message to `messages` table (with image base64)
3. **Get Project Info**: Fetch `project_path` and `project_type` from database
4. **Build Context**: Get conversation history from `messages` table
   - **Image Handling**: Replace base64 with `[Image was attached in previous message]`
5. **Handle Current Image**: Save to `/tmp/acp_images/` and pass PATH to ACPX (not base64)
6. **Run ACPX**: Execute `acpx --format quiet claude exec "<prompt>"`
7. **ACPX Actions**: Claude reads files, edits code, runs build verification
8. **Return Response**: Stream ACPX output back to client
9. **Cleanup**: Remove temp image file, kill orphan processes
10. **Save Assistant Message**: Insert Claude's response to `messages` table

## Key Components

### 1. `acp_chat_handler.py` (CORRECT - Already Exists)

```python
class ACPChatHandler:
    - run_acpx_chat()      # Executes ACPX subprocess
    - _build_chat_prompt() # Builds prompt with context + rules
    - kill_orphan_processes()  # Cleanup
```

**Features:**
- ✅ Spawns ACPX subprocess (can edit files)
- ✅ 5-minute timeout with watchdog
- ✅ Orphan process cleanup
- ✅ Project-specific prompts
- ✅ Conversation context injection

### 2. `acp_chat.py` (WRONG - My Mistake)

This file was incorrectly implemented with direct Claude API - **should be deleted or replaced**.

Direct API can only chat, **cannot edit files**.

## Request Format

```json
POST /api/chat/stream
{
  "session_key": "abc123",
  "content": "Add a login button to the navbar",
  "acp_mode": true,
  "stream": true
}
```

## Response Format

SSE stream with Claude's response:
```
data: {"choices": [{"delta": {"content": "I'll add a login button..."}}]}
data: {"choices": [{"delta": {"content": " more text..."}}]}
data: [DONE]
```

## What Claude-ACP Can Do

| Action | Allowed? | Notes |
|--------|----------|-------|
| Read any file | ✅ | Full project access |
| Edit `src/pages/*` | ✅ | Page components |
| Edit `src/components/*` | ✅ | Custom components |
| Edit `src/layout/*` | ✅ | Layout files |
| Edit `src/features/*` | ✅ | Feature modules |
| Create new files | ✅ | In allowed paths |
| Run `npm run build` | ✅ | Verify changes |
| Edit `package.json` | ❌ | Forbidden |
| Edit `src/components/ui/*` | ❌ | Use, don't modify |
| Run `npm install` | ❌ | Forbidden |

## Database Schema

### `messages` table
```sql
CREATE TABLE messages (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id),
    role TEXT,  -- 'user' or 'assistant'
    content TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### `sessions` table
```sql
CREATE TABLE sessions (
    id SERIAL PRIMARY KEY,
    session_key TEXT UNIQUE,
    project_id INTEGER REFERENCES projects(id),
    last_used_at TIMESTAMP
);
```

## Process Lifecycle

```
┌─────────────────────────────────────────────────────────┐
│                    ACPX Process                          │
├─────────────────────────────────────────────────────────┤
│  1. Request received                                     │
│  2. Spawn: acpx --format quiet claude exec "<prompt>"   │
│  3. Claude reads files, makes edits, verifies            │
│  4. Response returned                                    │
│  5. Process terminates (or killed on timeout)            │
│  6. Orphan cleanup runs (if needed)                      │
└─────────────────────────────────────────────────────────┘
```

## Action Required

1. ✅ **Update** `app.py` to use `acp_chat_handler.py` - DONE
2. ✅ **Kill orphan processes** after ACPX responds - DONE (via `handler.kill_orphan_processes()`)
3. ✅ **Save assistant message** to database - DONE
4. ✅ **Image handling** for ACP mode - DONE
   - Current message: Save to `/tmp/acp_images/`, pass PATH to ACPX
   - Old messages: Replace base64 with `[Image was attached in previous message]`
5. ⚠️ **Delete/archive** `acp_chat.py` - optional cleanup

## Image Handling for ACP Mode

ACPX cannot process base64 images directly. Images are handled as follows:

### Current Message with Image
```
1. Client sends: { "content": "...", "image": "<base64>", "acp_mode": true }
2. Backend saves image to: /tmp/acp_images/{session_id}_{uuid}.png
3. ACPX receives: "User message\n\n[Image attached: /tmp/acp_images/xxx.png]"
4. After response: Temp file deleted
```

### Previous Messages with Images
```
Database stores: content + image (base64)
Context sent to ACPX: "USER: message content\n\n[Image was attached in previous message]"
```

This prevents:
- Bloated context with repeated base64 strings
- Token waste on historical images
- ACPX confusion from raw base64

## Comparison

| Aspect | `acp_chat_handler.py` | `acp_chat.py` (wrong) |
|--------|----------------------|----------------------|
| File editing | ✅ Yes (via ACPX) | ❌ No (API only) |
| Subprocess | ✅ ACPX spawn | ❌ HTTP request |
| Tools access | ✅ Full file system | ❌ None |
| Use case | Frontend editing | Chat only |

## Files Involved

```
clawd-backend/
├── app.py                    # Main FastAPI app (needs update)
├── acp_chat_handler.py       # CORRECT handler (use this)
├── acp_chat.py               # WRONG (delete or replace)
├── database_adapter.py       # DB access
└── ACP_CHAT_MODE.md          # This file
```
