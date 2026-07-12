# AI Prompt Builder Completion API

> [TOC](toc.md) | Updated: 2026-07-12

## Purpose

`POST /ai/completion` powers the Prompt Assistant. It is a conversational product-planning assistant that refines user ideas and, after confirmation or an explicit generate action, produces one DreamAgent Project AI prompt.

The endpoint does not create projects, edit files, or generate application code. It only returns assistant text.

The route is currently stateless and anonymous. The client owns conversation history and sends the complete message list on each request.

## Main Files

| File | Responsibility |
| --- | --- |
| `app.py` | Request/response models and `/ai/completion` route |
| `completion_service.py` | Conversation workflow, create/edit system prompts, project-type guidance |
| `services/ai/openrouter_client.py` | OpenRouter chat completions client |

## Provider

The Prompt Assistant uses OpenRouter through `services/ai/openrouter_client.py`.

| Setting | Default |
| --- | --- |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` |
| `PROMPT_ASSISTANT_MODEL` | `z-ai/glm-4.7-flash` |
| `PROMPT_ASSISTANT_PROVIDER` | `balanced` |
| `OPENROUTER_APP_NAME` | `DreamAgent` |

`OPENROUTER_API_KEY` must be configured in the environment. Provider routing is balanced by default. Exact provider ordering can be enabled later with `PROMPT_ASSISTANT_PROVIDER=exact` and `PROMPT_ASSISTANT_PROVIDER_ORDER`.

## Request

```json
{
  "projectType": "website",
  "mode": "create",
  "generatePrompt": false,
  "messages": [
    {"role": "user", "content": "Premium landing page for an AI startup"}
  ],
  "projectInfo": null
}
```

## Request Fields

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `projectType` | string | yes | `website`, `telegrambot`, `discordbot`, `tradingbot`, `scheduler`, or `custom` |
| `mode` | string | yes | `create`, `modify`, or legacy `edit` alias handled as edit behavior by callers |
| `generatePrompt` | boolean | no | Forces final prompt generation if enough context exists |
| `messages` | array | yes | User/assistant conversation history. Client-supplied system messages are rejected. |
| `projectInfo` | object | no | Existing project context for edit mode |

## `projectInfo`

Edit mode can include existing project context so Prompt Assistant can produce better edit prompts.

```json
{
  "title": "Modern furniture store",
  "name": "furniture-store",
  "description": "Premium editorial ecommerce website",
  "projectType": "website",
  "status": "ready",
  "domain": "furniture-store",
  "liveUrl": "https://furniture-store.dreamagent.cloud"
}
```

For non-website projects, frontend callers should avoid website-only fields such as `domain` and `liveUrl` unless they are truly useful.

## Conversation Flow

1. Understand the user's idea or edit request.
2. Ask at most 1-2 high-value follow-up rounds when needed.
3. Infer reasonable defaults instead of collecting perfect information.
4. Present a short recommended summary.
5. Generate the final DreamAgent Project AI prompt only after confirmation, `generatePrompt=true`, or an explicit generate request.

Greetings and generic help messages should receive a short natural response, not a full project prompt.

## Create Mode

Create mode turns a rough idea into a concise, premium MVP build prompt. It focuses on:

- Product vision
- User experience
- Visual quality
- Layout and journey
- Features and interactions
- Mobile-first polish
- Final expected experience

DreamAgent Project AI already understands React, TypeScript, Tailwind CSS, routing, project structure, backend scaffold, base APIs, deployment pipeline, and development environment, so prompts should not waste space repeating routine implementation details.

## Edit Mode

Edit mode produces incremental edit instructions for an existing project. It should preserve existing architecture, folder structure, design language, navigation, user experience, routes, data, and working behavior unless the user explicitly requests a redesign.

Edit prompts should include only relevant:

- Requested changes
- Likely affected files/components
- UI changes
- Feature additions
- Bug fixes
- Compatibility requirements
- Constraints
- Expected final behavior

## Project-Type Guidance

Only the selected project type guidance is sent to the model.

| Type | Key rules |
| --- | --- |
| `website` | Max 4 pages, page names, premium UI, hero experience, animations, mobile/performance expectations |
| `telegrambot` | Default max 5 commands unless user asks for more, practical MVP user flow |
| `discordbot` | Default max 5 slash commands unless user asks for more, events and permissions |
| `tradingbot` | Strategy, indicators, risk management, stop loss, take profit, position sizing |
| `scheduler` | Jobs, schedules, retries, notifications, monitoring |
| `custom` | Infer the most suitable lightweight MVP shape |

## Response

```json
{
  "success": true,
  "message": {
    "role": "assistant",
    "content": "Based on our discussion, I recommend building..."
  },
  "error": null
}
```

## Error Response

```json
{
  "success": false,
  "message": null,
  "error": "Invalid project type"
}
```

Provider failures, rate limits, invalid API keys, and timeouts are logged by `OpenRouterClient` and converted to the existing completion error shape.

Note: usage tracking for this endpoint is recorded as anonymous usage in `app.py` because the route does not currently require authentication.

## Related

- [backend_api_reference.md](./backend_api_reference.md)
- [chat.md](./chat.md)
- [chat_stream.md](./chat_stream.md)
