# AI Completion - Complete Reference

> [TOC](toc.md) | [SKILL.md](../.agents/skills/project-info/SKILL.md) | Updated: 2026-03-15

---

## API Endpoints

| Endpoint | Method | File | Lines | Description |
|----------|--------|------|-------|-------------|
| `/ai/completion` | POST | `app.py` | 2420-2480 | AI completion for project tasks |

---

## POST /ai/completion

**File:** `app.py:2420-2480`

Get AI completion for project-related tasks.

**Request:**
```json
{
  "projectType": "website",
  "mode": "create",
  "messages": [
    {"role": "user", "content": "Create a landing page"}
  ]
}
```

**Request Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `projectType` | string | Type: `website`, `telegrambot`, `discordbot`, `tradingbot`, `scheduler`, `custom` |
| `mode` | string | Mode: `create` or `modify` |
| `messages` | array | Array of chat messages (conversation history) |

**Response:**
```json
{
  "success": true,
  "message": {
    "content": "I'll help you create a landing page...",
    "suggestions": [...]
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
| `website` | Web application with frontend/backend |
| `telegrambot` | Telegram bot |
| `discordbot` | Discord bot |
| `tradingbot` | Trading automation |
| `scheduler` | Scheduled task runner |
| `custom` | Custom project type |

---

## Modes

| Mode | Description |
|------|-------------|
| `create` | Creating new features |
| `modify` | Modifying existing code |

---

## Related

- [Chat](chat.md)
- [Chat Stream](chat_stream.md)
