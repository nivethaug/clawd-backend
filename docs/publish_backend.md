# Publish Backend - Complete Reference

> [TOC](toc.md) | [SKILL.md](../.agents/skills/project-info/SKILL.md) | Updated: 2026-03-15

---

## API Endpoints

| Endpoint | Method | File | Lines | Description |
|----------|--------|------|-------|-------------|
| `/projects/{id}/publish/backend` | POST | `app.py` | 1534-1624 | Build & publish backend |

---

## POST /projects/{id}/publish/backend

**File:** `app.py:1534-1624`

Build and publish backend for a project.

**Request:**
```json
{
  "project_path": "/path/to/project",
  "project_name": "myproject",
  "skip_install": false,
  "skip_build": false,
  "restart": true
}
```

**Request Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `project_path` | string | Absolute path to project (optional, uses DB if omitted) |
| `project_name` | string | Project name for PM2 restart (optional) |
| `skip_install` | bool | Skip pip install |
| `skip_build` | bool | Skip migrations |
| `restart` | bool | Restart PM2 and nginx after build |

**Response:**
```json
{
  "success": true,
  "message": "Backend build and publish completed successfully",
  "output": "...",
  "error": null
}
```

**Error Response:**
```json
{
  "success": false,
  "message": "Backend build failed",
  "output": "...",
  "error": "Build error details..."
}
```

---

## Build Steps

| Step | Description |
|------|-------------|
| 1 | Verify `main.py` exists |
| 2 | `pip install -r requirements.txt` |
| 3 | Run Alembic migrations (if `alembic.ini` exists) |
| 4 | Restart PM2/nginx (if `restart: true`) |

---

## Script Location

| File | Lines | Description |
|------|-------|-------------|
| `templates/blank-template/backend/buildpublish.py` | 1-200 | Backend build script |

---

## Related

- [Publish Frontend](publish_frontend.md)
- [Project Creation](project_creation.md)
