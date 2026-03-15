# Publish Frontend API

> [TOC](toc.md) | [SKILL.md](../.agents/skills/project-info/SKILL.md) | Updated: 2026-03-15

---

## Endpoint

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/projects/{project_id}/publish/frontend` | POST | Build & publish frontend |

---

## Publish Request

```
POST /projects/{project_id}/publish/frontend
```

**Request Body:**
```json
{
  "project_path": "/path/to/project",
  "project_name": "myproject",
  "skip_install": false,
  "skip_build": false,
  "restart": true
}
```

**Response:**
```json
{
  "success": true,
  "message": "Frontend build and publish completed successfully",
  "output": "..."
}
```

**File:** `app.py:1420-1500`

---

## Build Steps

| Step | Description |
|------|-------------|
| 1 | Clean Vite caches |
| 2 | Remove node_modules |
| 3 | npm install --include=dev --legacy-peer-deps |
| 4 | npm run build |
| 5 | Verify dist/ |
| 6 | Fix permissions (755/644) |
| 7 | Cleanup node_modules |
| 8 | Restart PM2/nginx (optional) |

---

## Script

**File:** `templates/blank-template/frontend/buildpublish.py`

**Usage:**
```bash
python buildpublish.py [--skip-install] [--skip-build] [--restart] [--project-name NAME]
```

---

## Related

- [Publish Backend](publish_backend.md)
- [Project Status](project_status.md)
