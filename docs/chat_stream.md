# Streaming Chat API

> [TOC](toc.md) | Updated: 2026-07-12

## Purpose

`POST /chat/stream` streams workspace chat responses over Server-Sent Events. It is the preferred path for project editing, image-assisted edits, and long-running ACP/Claude work because it keeps the connection alive while backend tools operate.

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

## ACP Streaming Flow

1. Validate session ownership.
2. Acquire the project/session lock.
3. Save the user message immediately, including `image` when present.
4. Reserve AI credits for ACP edit work when billing is enabled.
5. Initialize `ACPChatHandler` for the project.
6. If `mode=plan`, attach or create the active plan context.
7. If an image is present, decode it to `/tmp/acp_images` and append the file path to the prompt.
8. Load compact session context from the last messages.
9. Run the fast preprocessor. If it can answer directly, stream that answer.
10. Otherwise run unified streaming through Claude Code / ACP fallback.
11. Save the assistant response and any commit metadata.
12. Release/cleanup handler state and emit `[DONE]`.

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
  "session_key": "session-uuid"
}
```

Used after reloads to determine whether the UI should resume polling.

## Chunks

`GET /chat/chunks?session_key=session-uuid&after=0`

```json
{
  "chunks": ["I found", " the issue"],
  "total": 2,
  "active": true
}
```

Progress/tool/noise chunks are filtered so the UI receives clean assistant text.

## Operational Notes

- Streaming avoids proxy/gateway timeouts for image-assisted edits and long ACP runs.
- Client disconnects can still result in background save attempts through shared `StreamState`.
- Session locks prevent concurrent edits to the same project.
- Billing failures return `402` with insufficient-credit details.

## Related

- [chat.md](./chat.md)
- [session_locking.md](./session_locking.md)
- [TOKEN_USAGE_TRACKING.md](./TOKEN_USAGE_TRACKING.md)
