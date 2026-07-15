# Streaming Chat API

> [TOC](toc.md) | Updated: 2026-07-15

## Purpose

`POST /chat/stream` is the web session chat entry point for project editing, image-assisted edits, and long-running ACP/Claude work.

Session chat execution is now durable. The API validates the request, saves the user message, creates a `session_chat_runs` row, and returns/streams chunks that are persisted in `session_chat_chunks`. The separate PM2 process `clawd-session-chat-worker` owns the Claude/ACP execution, billing finalization, commit creation, and processing-lock release.

This means a FastAPI backend restart no longer loses the running edit or its chunks. The frontend can reconnect through `/chat/status` and `/chat/chunks` while the worker continues the edit.

## Endpoints

| Endpoint | Method | Description |
| --- | --- | --- |
| `/chat/stream` | POST | Stream assistant response as SSE |
| `/chat/cancel` | POST | Cancel active chat work for a session |
| `/chat/status` | GET | Check whether a session has active background work |
| `/chat/chunks` | GET | Poll accumulated chunks after reload |

## Auth

All endpoints require `Authorization: Bearer <token>` and validate session ownership.

## Request

```json
{
  "session_key": "session-uuid",
  "messages": [
    {"role": "user", "content": "Check this screenshot and fix the spacing"}
  ],
  "stream": true,
  "image": "data:image/webp;base64,UklGR...",
  "acp_mode": true,
  "mode": "dream"
}
```

## SSE Response

```text
data: {"choices":[{"delta":{"content":"I found the spacing issue..."}}]}

data: {"type":"commit","commitHash":"abc123","commitStatus":"success","filesChanged":2}

data: [DONE]
```

The frontend parser should accept regular OpenAI-style `choices[].delta.content` chunks and DreamAgent metadata events such as commit information.

## Durable Worker Process

Production PM2 should run both the API and the durable session worker:

```bash
pm2 status clawd-backend
pm2 status clawd-session-chat-worker
```

The worker is defined in `ecosystem.config.json`:

```text
clawd-session-chat-worker -> session_chat_worker.py
```

After pulling deploy changes, reload PM2 with:

```bash
pm2 startOrReload ecosystem.config.json --update-env
pm2 save
```

Useful logs:

```bash
pm2 logs clawd-session-chat-worker --lines 100
```

## ACP Streaming Flow

1. Validate session ownership.
2. Acquire the project/session lock and per-session processing flag.
3. Save the user message immediately, including `image` when present.
4. Reserve AI credits for ACP edit work when billing is enabled.
5. Insert `session_chat_runs.status='queued'`.
6. Return/stream from DB-backed chunks while the worker processes the run.
7. `clawd-session-chat-worker` claims the queued run with row locking.
8. The worker initializes `ACPChatHandler` for the project.
9. If `mode=plan`, attach or create the active plan context.
10. If an image is present, decode it to `/tmp/acp_images`, run the vision preprocessor when configured, and append the saved file path/analysis to the prompt.
11. Load compact session context from the last messages.
12. Run unified streaming through Claude Code / ACP fallback.
13. Persist chunks to `session_chat_chunks`.
14. Save the assistant response and any commit metadata.
15. Record token usage, charge/refund reserved credits, auto-commit/push if writes occurred.
16. Mark the run terminal and release the processing flag.

## Durable Run State

| Table | Purpose |
| --- | --- |
| `session_chat_runs` | One queued/running/completed edit run, including session/project/user/channel, mode, billing metadata, heartbeat, error, token usage, and write status |
| `session_chat_chunks` | Ordered durable stream chunks for reconnect and UI polling |

Run statuses:

```text
queued, running, cancel_requested, completed, failed, cancelled, interrupted
```

`sessions.processing` remains the quick lock gate, but the run rows are the source of truth for reconnect and cleanup.

## Image Attachments

The model used by the workspace chat is not treated as a vision model. Images are saved as local files so ACP/MCP tooling can inspect them by path.

Supported data URL MIME types:

| MIME | Extension |
| --- | --- |
| `image/jpeg` | `.jpg` |
| `image/jpg` | `.jpg` |
| `image/png` | `.png` |
| `image/webp` | `.webp` |
| `image/gif` | `.gif` |

If decoding fails, the prompt notes that an image was attached but could not be saved.

## Cancel

`POST /chat/cancel`

```json
{
  "session_key": "session-uuid"
}
```

Cancels active handler work for the session. The frontend should also abort the local fetch/SSE reader.

## Status

`GET /chat/status?session_key=session-uuid`

```json
{
  "active": true,
  "session_key": "session-uuid",
  "run_id": 42,
  "status": "running",
  "recovered": true
}
```

Used after reloads to determine whether the UI should resume polling. When a run is active after an API restart, the UI can show a reconnected/running state and continue polling chunks from the last seen index.

## Chunks

`GET /chat/chunks?session_key=session-uuid&after=0`

```json
{
  "chunks": ["I found", " the issue"],
  "total": 2,
  "active": true,
  "run_id": 42,
  "status": "running"
}
```

Progress/tool/noise chunks are filtered so the UI receives clean assistant text.

## Restart Behavior

| Event | Expected behavior |
| --- | --- |
| `clawd-backend` restarts while an edit is running | The edit continues because `clawd-session-chat-worker` owns the Claude process. The UI reconnects through `/chat/status` and `/chat/chunks`. |
| Browser refresh while edit is running | The session remains locked/processing; UI resumes chunk polling. |
| Telegram/Discord/Slack selected-session edit is running | The same durable worker path is used; transport waits for the final result or reports that the run is still active. |
| Worker restarts before claiming a queued run | New worker claims the queued row and starts normally. |
| Worker is killed while Claude is running | The Claude subprocess cannot be resumed. On worker startup, stale running rows are marked `interrupted`, reserved credits are refunded where possible, and processing is released. |
| Cancel is requested | The run moves to `cancel_requested`; the worker stops when it observes cancellation and marks the run `cancelled`. |

## Operational Notes

- Streaming avoids proxy/gateway timeouts for image-assisted edits and long ACP runs.
- Client disconnects no longer lose persisted chunks because chunks are stored in `session_chat_chunks`.
- Session locks prevent concurrent edits to the same project.
- Billing failures return `402` with insufficient-credit details.
- If `/chat/status` shows an active run but no chunks are moving, check `pm2 logs clawd-session-chat-worker --lines 100`.
- If only `clawd-backend` is running and the worker is missing, new edits stay queued/processing until `clawd-session-chat-worker` starts.

Inspect active runs:

```sql
SELECT id, session_id, project_id, channel, status, worker_id, created_at, started_at, heartbeat_at, error
FROM session_chat_runs
ORDER BY created_at DESC
LIMIT 20;
```

Inspect chunks:

```sql
SELECT seq, chunk_type, content, created_at
FROM session_chat_chunks
WHERE run_id = <RUN_ID>
ORDER BY seq ASC;
```

## Related

- [chat.md](./chat.md)
- [session_locking.md](./session_locking.md)
- [TOKEN_USAGE_TRACKING.md](./TOKEN_USAGE_TRACKING.md)
