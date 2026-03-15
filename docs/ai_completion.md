# AI Completion API

> [TOC](toc.md) | [SKILL.md](../.agents/skills/project-info/SKILL.md) | Updated: 2026-03-15

---

## Endpoint

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/ai/completion` | POST | AI completion for project context |

---

## Completion Request

```
POST /ai/completion
```

**Request Body:**
```json
{
  "projectType": "website",
  "mode": "create",
  "messages": [
    {"role": "user", "content": "Create a blog page"}
  ]
}
```

**Response:**
```json
{
  "success": true,
  "message": {
    "content": "I'll create a blog page for you...",
    "actions": ["create_file", "update_route"]
  }
}
```

**File:** `app.py:1100-1200`

---

## Project Types

| Type | Description |
|------|-------------|
| `website` | Web application |
| `telegrambot` | Telegram bot |
| `discordbot` | Discord bot |
| `tradingbot` | Trading bot |
| `scheduler` | Job scheduler |
| `custom` | Custom project |

---

## Modes

| Mode | Description |
|------|-------------|
| `create` | Create new features |
| `modify` | Modify existing code |

---

## Completion Service

```python
# completion_service.py
class CompletionService:
    def complete(self, project_type, mode, messages):
        """Generate AI completion"""
        ...
```

**File:** `completion_service.py:1-200`

---

## Related

- [Chat](chat.md)
- [Chat Stream](chat_stream.md)
