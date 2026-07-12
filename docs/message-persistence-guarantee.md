# Message Persistence Guarantees

> [TOC](toc.md) | Updated: 2026-07-12

## Purpose

Chat messages should remain visible in the UI even when an AI request fails, a stream disconnects, or image processing takes longer than expected.

## Current Guarantees

| Flow | Guarantee |
| --- | --- |
| `/chat` non-streaming | User message is committed before AI work starts. Assistant response or error is saved afterward. |
| `/chat/stream` streaming | User message is committed before streaming starts. Assistant content is accumulated and saved when the stream completes or when background recovery succeeds. |
| Image uploads | User image payload is saved on the user message. ACP also receives a temp file path for tool inspection. |
| Session deletes | Messages are deleted with their session. |
| Project deletes | Messages are deleted before project row removal. |

## Streaming Recovery

`chat_handlers.StreamState` tracks accumulated content while `/chat/stream` runs. If the client disconnects, the backend can continue waiting for content and save the final or partial assistant response.

Related endpoints:

- `GET /chat/status?session_key=...`
- `GET /chat/chunks?session_key=...&after=0`
- `POST /chat/cancel`

## Message Fields

Important message columns and response fields:

| Field | Description |
| --- | --- |
| `role` | `user` or `assistant` |
| `content` | Message text or error text |
| `image` | Optional uploaded image data on user messages |
| `mode` | Chat mode, such as `dream` or `plan` |
| `token_usage` | Optional assistant token usage JSON |
| `commit_hash` / `commit_status` | Optional commit metadata for code edits |
| `reverted_message_id` | Rollback tracking |

## Image Persistence

Uploaded image data may arrive as a browser data URL. The backend:

1. Stores the image payload on the user message.
2. Decodes the data URL/base64 payload.
3. Writes a temporary file under `/tmp/acp_images`.
4. Adds the temp file path to ACP prompt context.

This lets MCP/ACP tooling read the image by path without requiring direct model vision support.

## Related

- [chat.md](./chat.md)
- [chat_stream.md](./chat_stream.md)
- [project_sessions.md](./project_sessions.md)
