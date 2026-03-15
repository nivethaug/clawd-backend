# Publish Backend API

> [TOC](toc.md) | [SKILL.md](../.agents/skills/project-info/SKILL.md) | Updated: 2026-03-15

---

## Endpoint

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/projects/{project_id}/publish/backend` | POST | Build & publish backend |

---

## Publish Request

```
POST /projects/{project_id}/publish/backend
```

**Request Body:**
```json
{
  "project_path": "/path/to/project",
  "project_name": "myproject",
  "skip_install": false,
  "restart": true
}
```

**Response:**
```json
{
  "success": true,
  "message": "Backend build and publish completed successfully",
  "output": "..."
}
```

**File:** `app.py:1505-1570`

---

## Build Steps

| Step | Description |
|------|-------------|
| 1 | pip install -r requirements.txt |
| 2 | Verify main.py |
| 3 | Run migrations (if alembic configured) |
| 4 | Restart PM2/nginx (optional) |

---

## Script

**File:** `templates/blank-template/backend/buildpublish.py`

**Usage:**
```bash
python buildpublish.py [--skip-deps] [--skip-migrations] [--restart] [--project-name NAME]
```

---

## Related

- [Publish Frontend](publish_frontend.md)
- [Project Status](project_status.md)
