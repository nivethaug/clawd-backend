# AI Prompt Builder - Complete Reference

> [TOC](toc.md) | Updated: 2026-07-01

---

## API Endpoints

| Endpoint | Method | File | Lines | Description |
|----------|--------|------|-------|-------------|
| `/ai/completion` | POST | `app.py` | 7717-7788 | DreamAgent prompt builder for Project AI |

---

## POST /ai/completion

**File:** `app.py:7717-7788`

Transform a short idea, draft prompt, or multi-turn conversation into one final
DreamAgent Project AI prompt. `mode=create` builds a premium MVP creation prompt;
`mode=modify` builds a scoped edit prompt for an existing project.

**Request:**
```json
{
  "projectType": "website",
  "mode": "create",
  "messages": [
    {"role": "user", "content": "Jurassic website"}
  ]
}
```

**Request Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `projectType` | string | Type: `website`, `telegrambot`, `discordbot`, `tradingbot`, `scheduler`, `custom` |
| `mode` | string | Mode: `create` or `modify` |
| `messages` | array | Array of user/assistant messages. Client system messages are rejected. |

Canonical `projectType` values match the project type table and Prompt Assistant dropdown payloads: `website`, `telegrambot`, `discordbot`, `tradingbot`, `scheduler`, `custom`.

**Behavior:**

- Returns only the final Project AI prompt, not generic chat assistance.
- Does not generate code, execute work, or provide implementation narration.
- Uses independent system prompts for `create` and `modify`.
- Sends only the selected `projectType` guidance in the system prompt.
- For `create`, expands rough ideas into concise, visual-first MVP prompts.
- For `modify`, produces incremental edit instructions and never regenerates the full project brief.
- Scales prompt depth to the request: simple ideas stay short, complex products get more structure.
- Matches visual style to user intent instead of defaulting every website to cinematic, 3D, or dashboard layouts.
- Infers sensible design direction when unspecified, such as warm restaurant sites, premium real estate, clean healthcare, futuristic AI, or bold creative agency experiences.
- Assumes DreamAgent Project AI already understands React, TypeScript, Tailwind CSS, existing structure, backend scaffold, routing, base APIs, deployment pipeline, and development environment.
- Avoids repeating routine implementation details and spends tokens on product vision, UX, visual quality, user journey, layout, features, animations, interactions, and final experience.
- May use inspiration qualities from Apple, Linear, Stripe, Vercel, Notion, Raycast, Arc Browser, or Awwwards when helpful, without copying existing products.
- Focuses on frontend experience, UX, visual quality, interactions, and requested functionality unless backend work is explicitly requested.
- Preserves pasted prompt intent while improving specificity and execution quality.
- Asks a follow-up question only when critical information cannot be inferred.

**Response:**
```json
{
  "success": true,
  "message": {
    "role": "assistant",
    "content": "Build a cinematic Jurassic website..."
  },
  "error": null
}
```

**Error Response:**
```json
{
  "success": false,
  "message": null,
  "error": "Invalid project type"
}
```

---

## Project Types

| Type | Description |
|------|-------------|
| `website` | Web application with frontend/backend; max 4 pages and explicit page names |
| `telegrambot` | Telegram bot that defaults to 5 commands unless more are requested |
| `discordbot` | Discord bot that defaults to 5 slash commands unless more are requested |
| `tradingbot` | Trading automation with mandatory risk management |
| `scheduler` | Scheduled task runner with retries, monitoring, and recovery |
| `custom` | Custom project type with inferred architecture |

---

## Modes

| Mode | Description |
|------|-------------|
| `create` | Create a concise, premium, visual-first MVP prompt |
| `modify` | Create a precise incremental edit prompt for an existing project |

---

## Related

- [Chat](chat.md)
- [Chat Stream](chat_stream.md)
