# Slack Session Chat

> [TOC](toc.md) | Updated: 2026-07-14

## Purpose

Slack control chat lets a linked Slack user manage DreamAgent projects from `/dreamagent` and continue selected project sessions from the DreamAgent app DM.

Slack is only a transport. It reuses the same DevOps project tools, selected-session ACP handler, lock service, billing, token usage, and auto-commit behavior used by web, Telegram, and Discord.

## Main Files

| File | Responsibility |
| --- | --- |
| `api/slack_webhook.py` | Slash command, interaction, and event handling |
| `services/slack_client.py` | Slack Web API and response URL helper |
| `utils/devops_session_context.py` | Shared active project/session context |
| `services/external_session_chat.py` | Shared selected-session ACP runner |
| `services/session_lock_service.py` | Project lock and per-session in-progress guard |
| `api/bot_link.py` | Shared bot link-code generation and Slack unlink endpoint |

## Slack App URLs

Configure these in the Slack app console:

| Slack setting | URL |
| --- | --- |
| Slash command request URL | `https://api.dreamagent.cloud/bot/slack/commands` |
| Interactivity request URL | `https://api.dreamagent.cloud/bot/slack/interactions` |
| Events request URL | `https://api.dreamagent.cloud/bot/slack/events` |

The events endpoint supports Slack `url_verification` and app-DM message events.

## Commands

Slack uses one primary slash command: `/dreamagent`.

Optional shortcut commands can be added for better Slack autocomplete. Every shortcut uses the same request URL:

| Command | Request URL | Behavior |
| --- | --- | --- |
| `/dream-link` | `/bot/slack/commands` | Link Slack to DreamAgent. |
| `/dream-unlink` | `/bot/slack/commands` | Unlink Slack. |
| `/dream-switch` | `/bot/slack/commands` | Select or change active project. |
| `/dream-sessions` | `/bot/slack/commands` | List/select project sessions. |
| `/dream-newsession` | `/bot/slack/commands` | Create/select a project session. |
| `/dream-clearsession` | `/bot/slack/commands` | Clear selected session context. |
| `/dream-complete` | `/bot/slack/commands` | Release selected session lock. |
| `/dream-current` | `/bot/slack/commands` | Show active project/session. |
| `/dream-billing` | `/bot/slack/commands` | Show billing summary. |
| `/dream-status` | `/bot/slack/commands` | Show active project status. |
| `/dream-logs` | `/bot/slack/commands` | Show recent logs. |
| `/dream-start` | `/bot/slack/commands` | Start active project. |
| `/dream-stop` | `/bot/slack/commands` | Stop active project. |
| `/dream-restart` | `/bot/slack/commands` | Restart active project. |
| `/dream-project` | `/bot/slack/commands` | Normal DevOps project message. |
| `/dream-chat` | `/bot/slack/commands` | Selected-session edit message. |
| `/dream-help` | `/bot/slack/commands` | Guided workflow. |

| Command | Behavior |
| --- | --- |
| `/dreamagent link CODE` | Link Slack to the DreamAgent account that generated the code. |
| `/dreamagent unlink` | Unlink Slack only. |
| `/dreamagent switch` | Select or change active project. |
| `/dreamagent sessions` | List sessions for the active project. |
| `/dreamagent newsession LABEL` | Create/select a project session, subject to lock rules. |
| `/dreamagent clearsession` | Clear selected Slack session context without releasing the lock. |
| `/dreamagent complete` | Release selected session lock. |
| `/dreamagent current` | Show active project/session. |
| `/dreamagent billing` | Show plan, balances, and recent billing activity. |
| `/dreamagent status` | Show active project status. |
| `/dreamagent logs` | Show recent logs. |
| `/dreamagent start` | Start active project. |
| `/dreamagent stop` | Stop active project. |
| `/dreamagent restart` | Restart active project. |
| `/dreamagent project MESSAGE` | Normal DevOps project assistant message. |
| `/dreamagent chat MESSAGE` | Selected-session edit message. |
| `/dreamagent help` | Guided workflow. |

## DM Behavior

Inside the DreamAgent Slack app DM:

- Natural control aliases such as `billing`, `current`, `sessions`, `status`, and `logs` run deterministic actions.
- If a project session is selected, ordinary text routes to selected-session ACP chat.
- If no project session is selected, ordinary text routes to normal DevOps `process_message`.

## Required Slack Scopes

- `commands`
- `chat:write`
- `im:history`
- `im:read`
- `im:write`
- `users:read`

## Environment

```env
SLACK_BOT_TOKEN=
SLACK_SIGNING_SECRET=
SLACK_APP_ID=
SLACK_CLIENT_ID=
SLACK_CLIENT_SECRET=
SLACK_INSTALL_URL=
SLACK_INTERACTIONS_SECRET=
```

Frontend Settings can use `VITE_SLACK_INSTALL_URL` to show a direct install/open link.

## Locking And Billing

Slack selected-session chat uses `services.external_session_chat.run_selected_session_chat()` with `channel="slack"`. It follows the same behavior as Telegram and Discord:

- blocks if another web/Telegram/Discord/Slack message is processing in the selected session
- blocks if another session owns the project lock
- charges edit usage to the project owner
- records token usage after completion
- auto-commits and pushes when handler usage reports `has_writes=true`

## Related

- [telegram_session_chat.md](./telegram_session_chat.md)
- [discord_session_chat.md](./discord_session_chat.md)
- [project_sessions.md](./project_sessions.md)
- [session_locking.md](./session_locking.md)
- [billing.md](./billing.md)
