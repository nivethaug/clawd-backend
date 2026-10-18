# Plan: Large Text → File Attachment (like Claude Code / Cursor)

**Status:** Planned, not yet implemented
**Date:** 2026-10-19
**Context:** Session 453 sent a 98K-char design reference that crashed the agent (ARG_MAX), led to the stdin workaround, and still bloats every prompt. This plan eliminates the root cause.

## How other tools do it
Claude Code and Cursor detect large pastes (>10KB), save them as temp files, and tell the agent "read [path] with the Read tool." The agent reads from disk — the prompt stays small, the agent sees the full content once.

## Design

### Backend (core — app.py, both /chat/stream and /chat endpoints)

After receiving `user_content`, before building the prompt:

```
if len(user_content) > 10,000 chars:
    1. Save full text → <project>/chat-uploads/reference-{uuid8}.md
    2. Build the agent prompt with a file pointer:
       "Your full input is at: {container_path}
        Read it with your Read tool NOW, before responding.
        Summary: {user_content[:500]}..."
    3. DB stores the FULL text (user sees what they sent in the chat UI)
    4. Agent reads the file from disk → full context, small prompt
```

### New helper — `_persist_large_text(user_content, project_path, session_id)`
Following the image attachment pattern (app.py persist_chat_image_reference):
- Write to `<project>/chat-uploads/reference-{uuid8}.md`
- Convert host path → container path via `services/container_storage.to_container_path`
- Return `{container_path, host_path}`
- No cleanup (reference may be re-read in later turns)

### New prompt builder — `_append_large_text_instruction(user_content, file_ref)`
Following `append_chat_image_instruction` (app.py):
- Keep first 500 chars inline (agent gets immediate context)
- Append `<LARGE_TEXT_ATTACHED>` block with path + Read instruction
- Agent prompt = short summary + "Read the file for the complete input"

### Integration point — `/chat/stream` (where `user_content` is extracted)
```python
TEXT_FILE_THRESHOLD = int(os.getenv("CHAT_TEXT_FILE_THRESHOLD", "10000"))
if len(user_content) > TEXT_FILE_THRESHOLD and handler.project_path:
    file_ref = _persist_large_text(user_content, str(handler.project_path), session_id)
    if file_ref:
        acp_user_content = _append_large_text_instruction(user_content, file_ref)
        # user_content (full) still saved to DB for the UI
```

### Frontend (SessionChat.tsx — minimal UX addition)
- Show a subtle hint when textarea > 10K chars: "Will be sent as a file reference"
- No behavior change — backend handles the conversion transparently
- Chat UI still displays the full text (from DB)

## What this solves

| Scenario | Before | After |
|---|---|---|
| 98K design reference sent | 98K inline prompt via stdin | ~500 char prompt + agent reads file |
| "continue" after reference | Context budget trims old but current message still huge | Reference is on disk, prompt stays small |
| Agent re-reads for detail | Must re-parse from inline prompt | Can re-Read the file anytime |
| Token cost per turn | 98K+ prompt tokens every turn | ~2K prompt tokens + one Read tool call |
| ARG_MAX crash risk | Mitigated by stdin fallback | Eliminated (prompt never exceeds threshold) |

## What already exists (reused, not rebuilt)
- `persist_chat_image_reference` pattern for workspace persistence → clone for text
- `append_chat_image_instruction` pattern for prompt replacement → clone for text
- Agent's Read tool (unrestricted, workspace-scoped) — already reads files
- `services/container_storage.to_container_path` — already handles host→container mapping
- `chat-uploads/` directory — already exists in projects (image attachments use it)
- Session context budget (`_load_session_context_budgeted`) — already deployed, trims old messages to 30K

## Files to touch (when implementing)

1. **`app.py`** — two new helpers:
   - `_persist_large_text(user_content, project_path, session_id)` near line 449
   - `_append_large_text_instruction(user_content, file_ref)` near line 857
   - Integration in `/chat/stream` at ~line 9553 and `/chat` at ~line 10733

2. **`src/pages/SessionChat.tsx`** (optional, cosmetic):
   - Char counter in `PremiumPromptInput`
   - Show "File reference" badge when > 10K chars

## Deploy (when implementing)
- Backend: push → main pull + `pm2 restart clawd-backend` → worker pull + `pm2 restart clawd-worker-api`
- Frontend (if adding hint): build + deploy to `/root/clawd-ui/dist`

## Related already-deployed mitigations (keep them)
- stdin prompt path for >96KB (`claude_code_agent.py`) — safety net
- docker exec `-i` flag (`services/container_manager.py`) — stdin forwarding
- Session context budget 30K (`_load_session_context_budgeted`) — trims old messages
