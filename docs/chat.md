# Chat API

> [TOC](toc.md) | Updated: 2026-07-12

## Purpose

`/chat` is the workspace chat endpoint used by project sessions. It supports Dream mode and Plan mode, optional ACP editing, and image attachments.

The frontend should prefer streaming for long-running edit work. When `stream=true`, `/chat` delegates to `/chat/stream`.

## Main Files

| File | Responsibility |
| --- | --- |
| `app.py` | `/chat`, `/chat/stream`, cancellation/status/chunk endpoints, models |
| `chat_handlers.py` | Shared stream state and database persistence |
| `acp_chat_handler.py` | Project-aware ACP/Claude edit handler |
| `claude_code_agent.py` | Claude Code execution backend |
| `acp_preprocessor.py` | Fast preprocessor that can answer without code edits |

## Auth

All session chat routes require `Authorization: Bearer <token>`. Ownership is enforced by session key through `_require_session_key_owner()`.

## Request

```json
{
  "session_key": "session-uuid",
  "messages": [
    {"role": "user", "content": "Make the hero more premium"}
  ],
  "stream": true,
  "image": null,
  "acp_mode": true,
  "mode": "dream"
}
```

## Request Fields

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `session_key` | string | required | Session identifier |
| `messages` | array | required | User/assistant messages; the last user message is processed |
| `stream` | boolean | `false` | If true, `/chat` delegates to `/chat/stream` |
| `image` | string/null | `null` | Optional browser data URL or base64 image payload |
| `acp_mode` | boolean | `true` | Enables project-aware code editing |
| `mode` | string | `dream` | `dream` or `plan` |

## Non-Streaming Response

```json
{
  "id": 0,
  "role": "assistant",
  "content": "Done. I updated the hero section...",
  "created_at": "2026-07-12T10:00:00"
}
```

## Current Behavior

- Validates the session exists and belongs to the authenticated user.
- Acquires a project/session lock before running code edits.
- Saves the user message immediately.
- Saves attached image payload on the user message.
- In ACP mode, image payloads are decoded and written to `/tmp/acp_images/{session_id}_{uuid}.{ext}`.
- The image file path is appended to the prompt so MCP/ACP tools can read it. The LLM is not expected to have direct vision support.
- Uses recent messages as compact context and replaces historical base64 images with placeholders.
- Saves the assistant response and updates session usage timestamps.

## Image Handling

Uploaded images may arrive as browser data URLs such as:

```text
data:image/webp;base64,UklGR...
```

`decode_chat_image_payload()` strips the data URL header, validates base64, and preserves a useful extension for JPEG, PNG, WebP, or GIF. The frontend compresses chat images before upload, and image messages should use streaming to avoid gateway timeouts while ACP works.

## Errors

| Status | Cause |
| --- | --- |
| 400 | No user message provided |
| 401 | Missing or invalid auth token |
| 403 | Session does not belong to the user |
| 404 | Session not found |
| 423 | Another session is active for the same project |
| 402 | Insufficient AI credits for ACP edit work |

## Related

- [chat_stream.md](./chat_stream.md)
- [project_sessions.md](./project_sessions.md)
- [session_locking.md](./session_locking.md)
- [message-persistence-guarantee.md](./message-persistence-guarantee.md)
