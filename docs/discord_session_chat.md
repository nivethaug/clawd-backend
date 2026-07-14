# Discord Session Chat

Discord session chat lets a linked Discord user control DreamAgent projects and continue an existing project editor session from Discord.

Discord is only the transport. Project selection, session locks, ACP execution, token usage, billing, and auto-commit behavior use the same shared backend paths as web session chat and Telegram session chat.

## Main Files

| File | Purpose |
| --- | --- |
| `api/discord_webhook.py` | Discord Interactions endpoint, slash commands, buttons, linking, selected-session routing |
| `services/discord_client.py` | Discord API client, command registration, response editing |
| `services/external_session_chat.py` | Shared external selected-session runner used by Telegram and Discord |
| `utils/devops_session_context.py` | Active project/session context |
| `acp_chat_handler.py` | Project-aware ACP edit handler |
| `services/session_lock_service.py` | Project lock and per-session processing lock |
| `services/billing_service.py` | Credit reservation, token charging, and billing summary |

## Environment

| Variable | Purpose |
| --- | --- |
| `DISCORD_CONTROL_BOT_TOKEN` | Bot token for the DreamAgent control bot |
| `DISCORD_PUBLIC_KEY` | Discord application public key used to verify Interactions |
| `DISCORD_APPLICATION_ID` | Discord application ID for follow-up responses and command registration |
| `DISCORD_GUILD_ID` | Optional guild ID for fast development command registration |
| `DISCORD_INTERACTIONS_SECRET` | Optional setup secret for command registration/removal routes |

## Routes

| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/bot/discord/interactions` | Discord Interactions receiver |
| `POST` | `/bot/discord/register-commands` | Register Discord slash commands |
| `DELETE` | `/bot/discord/commands` | Remove Discord slash commands |

Discord signs every interaction with `X-Signature-Ed25519` and `X-Signature-Timestamp`. The webhook rejects unsigned or invalid requests.

## Commands

| Command | Purpose |
| --- | --- |
| `/link code:CODE` | Link the Discord user to a DreamAgent account |
| `/unlink` | Remove the Discord link |
| `/switch [project]` | Select or change active project |
| `/sessions` | List sessions for the active project |
| `/newsession label:LABEL` | Create and select a new project session |
| `/chat message:TEXT` | Continue the selected project session |
| `/clearsession` | Clear selected session context without releasing the lock |
| `/complete` | Release selected session lock |
| `/current` | Show active project/session |
| `/billing` | Show current plan, credit balances, and recent activity |
| `/status` | Check project status |
| `/logs` | Show recent logs |
| `/start` | Start active project |
| `/stop` | Stop active project |
| `/restart` | Restart active project |
| `/help` | Show guided workflow |

Discord Interactions do not deliver arbitrary normal channel messages to this webhook. Use `/chat message:...` as the Discord equivalent of typing naturally in Telegram after a session is selected.

## Buttons

Discord replies include buttons for common next steps:

| Context | Buttons |
| --- | --- |
| Project/default | Current, Sessions, Status, Logs, Restart, Billing, Help |
| Selected session | Current, Sessions, Complete, Clear Session, Status, Logs, Billing |
| Busy session | Current, Sessions, Complete, Clear Session, Billing |

Button `custom_id` values follow the same idea as Telegram callback data:

- `action:current`
- `action:sessions`
- `action:billing`
- `switch:{domain}`
- `session:set:{project_domain}:{session_id}`

## Session Chat Flow

```text
/chat message:...
-> resolve Discord user link
-> resolve active DreamAgent project/session
-> acquire processing lock with channel=discord
-> acquire project session lock
-> reserve ADD_FEATURE credit
-> insert user message into messages
-> run ACP streaming handler through services.external_session_chat
-> record token usage and charge edit tokens
-> insert assistant response into messages
-> auto-commit and push if handler reports writes
-> release processing lock
-> edit Discord interaction response with final answer
```

## Locking

Discord follows the same one-active-session-per-project rule as web and Telegram:

- If the selected session already owns the project lock, continuing is allowed.
- If the project is unlocked, Discord can acquire the lock for the selected session.
- If another web, Telegram, or Discord session owns the lock, Discord blocks the action and explains the owner.
- If the same session is already processing a message, Discord returns a busy response.
- `/clearsession` only clears Discord/user context; it does not release the project lock.
- `/complete` releases the selected session lock through `SessionLockService`.

## Setup

1. Set the required Discord environment variables.
2. Configure the Discord Interactions endpoint to:

```text
https://api.dreamagent.cloud/bot/discord/interactions
```

3. Register slash commands:

```bash
curl -X POST https://api.dreamagent.cloud/bot/discord/register-commands
```

If `DISCORD_INTERACTIONS_SECRET` is configured, include:

```bash
-H "X-Discord-Setup-Secret: $DISCORD_INTERACTIONS_SECRET"
```

## Related Docs

- [telegram_session_chat.md](./telegram_session_chat.md)
- [session_locking.md](./session_locking.md)
- [project_sessions.md](./project_sessions.md)
- [billing.md](./billing.md)
