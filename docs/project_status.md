# Project Status - Complete Reference

> [TOC](toc.md) | [SKILL.md](../.agents/skills/project-info/SKILL.md) | Updated: 2026-03-15

---

## API Endpoints

| Endpoint | Method | File | Lines | Description |
|----------|--------|------|-------|-------------|
| `/projects/{id}/status` | GET | `app.py` | 1624-1657 | Get pipeline status |
| `/projects/{id}/ai-status` | GET | `app.py` | 1657-1813 | Get AI refinement status |
| `/projects/{id}/claude-session` | GET | `app.py` | 1819-1880 | Get Claude session info |

---

## GET /projects/{id}/status

**File:** `app.py:1624-1657`

Get project creation pipeline status.

**Response:**
```json
{
  "status": "creating"
}
```

**Status Values:**

| Status | Description |
|--------|-------------|
| `creating` | OpenClaw pipeline is running |
| `ready` | Pipeline completed successfully |
| `failed` | Pipeline failed |

---

## GET /projects/{id}/ai-status

**File:** `app.py:1657-1813`

Get detailed AI refinement status (Phase 8 monitoring).

**Response:**
```json
{
  "project_id": 123,
  "project_name": "my-project",
  "project_path": "/var/www/projects/my-project",
  "frontend_path": "/var/www/projects/my-project/frontend",
  "process_running": true,
  "pid": 12345,
  "elapsed_seconds": 120,
  "recent_modifications": [
    {"file": "src/pages/Home.tsx", "time": "2026-03-15T10:05:00"}
  ],
  "status": "running"
}
```

---

## GET /projects/{id}/claude-session

**File:** `app.py:1819-1880`

Get Claude Code session information.

**Response:**
```json
{
  "session_name": "project-123-session",
  "session_path": "/root/.claude/projects/project-123",
  "exists": true,
  "files": ["CLAUDE.md", "context.json"]
}
```

---

## Related

- [Project Creation](project_creation.md)
- [Project Deletion](project_deletion.md)
