# Telegram Session Chat

> [TOC](toc.md) | Updated: 2026-07-14

## Purpose

Telegram session chat lets a linked Telegram user continue an existing DreamAgent project session from Telegram. Once a project session is selected, normal Telegram messages route to the same ACP session chat used by the web editor.

Telegram is only the transport. The project session, lock, prompt routing, message history, and billing behavior should match web session chat.

## Main Files

| File | Responsibility |
| --- | --- |
| `api/telegram_webhook.py` | Telegram command handling, inline action buttons, selected-session routing, typing heartbeat, token billing |
| `utils/devops_session_context.py` | Active project/session context shared by Telegram and DevOps chat |
| `services/session_lock_service.py` | Single active editing session lock per project and per-session in-progress guard |
| `acp_chat_handler.py` | Project-aware ACP/Claude edit handler used by web and Telegram session chat |
| `services/telegram_client.py` | Telegram API client and default bot command registration |
| `services/token_tracker.py` | Token usage recording after session completion |
| `services/billing_service.py` | Edit-token/AI-credit reconciliation |

## Commands

| Command | Behavior |
| --- | --- |
| `/switch` | Select or change the active project. Switching projects clears the active project session. |
| `/sessions` | List sessions for the active project and show inline session buttons. |
| `/newsession LABEL` | Create a new project session for the active project, subject to lock rules. |
| `/clearsession` | Clear the selected Telegram session context without releasing the project lock. |
| `/complete` | Release the selected session lock through the existing lock service. |
| `/current` | Show active project, selected session, and lock state. |
| `/status` | Show active project runtime status. |
| `/logs` | Show recent logs for the active project. |
| `/restart` | Restart the active project. |
| `/start` | Start the active project. |
| `/stop` | Stop the active project. |
| `/help` | Show the guided Telegram workflow. |

After a session is selected, any normal Telegram text message is treated as session chat input until `/complete`, `/clearsession`, or a project switch.

The default Telegram command menu is registered through `services.telegram_client.set_my_commands()`. The existing `/bot/telegram/setwebhook` endpoint calls this registration flow, so after deploy call that setup endpoint once to refresh Telegram's `/` autocomplete menu.

## Inline Action Buttons

Telegram replies include compact inline buttons for common next steps:

| Context | Buttons |
| --- | --- |
| Project/default replies | Current, Sessions, Status, Logs, Restart, Help |
| Selected-session replies | Current, Sessions, Complete, Clear Session, Status, Logs |
| Busy/in-progress replies | Current, Sessions, Complete, Clear Session |
| Selection replies | Project or session choices from the existing selection response |

Inline buttons use `callback_data` values such as `action:current`, `action:sessions`, `action:logs`, `switch:{domain}`, and `session:set:{project_domain}:{session_id}`. The callback handler routes action buttons through the same deterministic command dispatcher used by slash commands.

## Natural Aliases

Common plain-text shortcuts are treated as commands before selected-session chat routing:

| User text | Mapped behavior |
| --- | --- |
| `current`, `current project`, `current session`, `where am i` | `/current` |
| `sessions`, `show sessions`, `list sessions`, `switch session`, `select session` | `/sessions` |
| `new session mobile fixes`, `newsession mobile fixes` | `/newsession mobile fixes` |
| `clear session`, `leave session` | `/clearsession` |
| `complete`, `finish session`, `release session` | `/complete` |
| `status`, `logs`, `restart`, `start`, `stop` | Project control actions |
| `help`, `menu`, `commands` | `/help` |

This preserves natural editing messages for selected sessions while keeping obvious project/session control phrases out of the editor prompt.

## Routing Flow

```text
Telegram message
-> resolve linked user
-> resolve active project
-> resolve selected project session
-> acquire project/session lock
-> reserve edit credits
-> save user message to messages
-> get_acp_chat_handler(session_key)
-> ACPChatHandler.run_chat_streaming_unified()
-> save assistant message + token usage
-> reconcile billing
-> auto-commit if handler usage reports has_writes=true
-> send final Telegram reply
```

The selected session is a row in the existing `sessions` table. Telegram does not create a separate chat transcript for project edits; it writes to the same `messages` table used by web project sessions.

## Same Handler As Web Session Chat

Telegram selected-session chat should collect from the same streaming entrypoint used by web sessions:

```python
handler = get_acp_chat_handler(session_key)
async for chunk in handler.run_chat_streaming_unified(text, session_context):
    ...
```

`acp_chat_handler.py` then chooses the correct project prompt from `project_type_id`:

| Project type | Prompt builder |
| --- | --- |
| Website | `_build_chat_prompt()` |
| Telegram Bot | `_build_chat_prompt_telegram()` |
| Discord Bot | `_build_chat_prompt_discord()` |
| Scheduler | `_build_chat_prompt_scheduler()` |

This is the same project-aware edit pipeline used by web session chat. The key detail is that the streaming path resumes Claude context by project path and session id, so Telegram should not use the older non-streaming `run_chat_unified()` path for selected project sessions. The only UI difference is that web streams progress in-browser, while Telegram keeps a typing heartbeat active and sends the final response when the run completes.

## Lock Rules

Telegram follows the existing one-active-session-per-project lock.

- If the selected Telegram session already owns the project lock, continuing is allowed.
- If the project is unlocked, Telegram can acquire the lock for the selected session.
- If another web or Telegram session owns the lock, Telegram returns a clear error and does not run ACP.
- `/clearsession` only clears Telegram context; it does not release the lock.
- `/complete` releases the selected session lock through `SessionLockService`.
- Switching projects clears the selected session context automatically.

This keeps web and Telegram from editing the same project concurrently.

## In-Progress Message Guard

In addition to the project lock, selected-session chat uses a per-session processing flag in `sessions`:

- `processing`
- `processing_started_at`
- `processing_channel`

This prevents duplicate messages from the same selected session while a web or Telegram edit is already running. Web `/chat` and `/chat/stream` return `409 session_message_in_progress`. Telegram replies with a user-facing "Still working..." message plus inline buttons.

The flag is released when the web stream completes, a background save finishes, the user cancels from web, or Telegram selected-session processing finishes. A stale flag can be recovered after the configured timeout inside `SessionLockService.acquire_processing()`.

## Billing And Token Usage

Telegram session chat should charge the same type of edit usage as web ACP chat.

- Credits are reserved before running the selected session chat.
- Token usage is read from `handler.get_last_token_usage()` after the run.
- A `token_usage` row is recorded with `usage_type="ai_chat"`.
- Billing reconciles against the same `ADD_FEATURE` operation used by web edits.
- If the run fails before an assistant message is saved, reserved credits are refunded.
- Assistant messages may store token usage JSON in `messages.token_usage`.
- If handler usage reports `has_writes=true`, Telegram selected-session chat reuses the same auto-commit path as web session chat.

Billing is charged to the project owner, not to a separate Telegram identity.

## Active Session State

Telegram uses the linked user's active project and active project session state:

- `users.active_project_session_id` stores the cross-channel selected project session.
- `ai_sessions.active_project_session_id` can store channel/session-specific context.
- Resolution prefers the user's selected session, then the Telegram AI session context.

If the selected session no longer belongs to the active project, the session context is cleared.

## Operational Notes

- Telegram chat uses a background task so the webhook can return quickly.
- A Telegram typing heartbeat should remain active while the selected session run is in progress.
- Long responses are truncated to Telegram-safe length before sending.
- ACP orphan cleanup still runs after the session completes.
- Telegram selected-session chat is not the same as general DevOps `/api/ai/chat`; it is a bridge into project editor session chat.

## Related

- [chat.md](./chat.md)
- [project_sessions.md](./project_sessions.md)
- [session_locking.md](./session_locking.md)
- [TOKEN_USAGE_TRACKING.md](./TOKEN_USAGE_TRACKING.md)
- [billing.md](./billing.md)
