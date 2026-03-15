# Project Status API

> [TOC](toc.md) | [SKILL.md](../.agents/skills/project-info/SKILL.md) | Updated: 2026-03-15

---

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/projects/{project_id}/status` | GET | Get pipeline status |
| `/projects/{project_id}/ai-status` | GET | Get AI refinement status |
| `/projects/{project_id}/claude-session` | GET | Get Claude session info |

---

## Get Project Status

```
GET /projects/{project_id}/status
```

**Response:**
```json
{
  "status": "creating" | "ready" | "failed"
}
```

**Status Values:**
- `creating` - Pipeline is running
- `ready` - Project deployed successfully
- `failed` - Pipeline failed

**File:** `app.py:1417-1450`

---

## Get AI Status

```
GET /projects/{project_id}/ai-status
```

**Response:**
```json
{
  "running": true,
  "pid": 12345,
  "elapsed_seconds": 120,
  "recent_modifications": ["src/App.tsx", "src/pages/Home.tsx"],
  "project_path": "/root/clawd-projects/my-project",
  "frontend_path": "/root/clawd-projects/my-project/frontend"
}
```

**File:** `app.py:1450-1610`

---

## Get Claude Session

```
GET /projects/{project_id}/claude-session
```

**Response:**
```json
{
  "session_name": "my-project-session",
  "session_path": "/root/.claude/sessions/my-project-session",
  "exists": true
}
```

**File:** `app.py:1612-1670`

---

## Related

- [Project Creation](project_creation.md)
- [Project Session](project_session.md)
