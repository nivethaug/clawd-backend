# Publish Frontend - Complete Reference

> [TOC](toc.md) | [SKILL.md](../.agents/skills/project-info/SKILL.md) | Updated: 2026-03-15

---

## API Endpoints

| Endpoint | Method | File | Lines | Description |
|----------|--------|------|-------|-------------|
| `/projects/{id}/publish/frontend` | POST | `app.py` | 1436-1534 | Build & publish frontend |

---

## POST /projects/{id}/publish/frontend

**File:** `app.py:1436-1534`

Build and publish frontend for a project.

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
| `skip_install` | bool | Skip npm install |
| `skip_build` | bool | Skip npm build |
| `restart` | bool | Restart PM2 and nginx after build |

**Response:**
```json
{
  "success": true,
  "message": "Frontend build and publish completed successfully",
  "output": "...",
  "error": null
}
```

**Error Response:**
```json
{
  "success": false,
  "message": "Frontend build failed",
  "output": "...",
  "error": "Build error details..."
}
```

---

## Build Steps

| Step | Description |
|------|-------------|
| 1 | Clean Vite caches (`.vite-temp`, `.vite`) |
| 2 | Remove existing `node_modules` |
| 3 | `npm install --include=dev --legacy-peer-deps` |
| 4 | `npm run build` |
| 5 | Verify `dist/index.html` |
| 6 | Fix permissions (755/644) |
| 7 | Cleanup `node_modules` |
| 8 | Restart PM2/nginx (if `restart: true`) |

---

## Script Location

| File | Lines | Description |
|------|-------|-------------|
| `templates/blank-template/frontend/buildpublish.py` | 1-250 | Frontend build script |

---

## Related

- [Publish Backend](publish_backend.md)
- [Project Creation](project_creation.md)
