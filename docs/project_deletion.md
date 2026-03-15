# Project Deletion API

> [TOC](toc.md) | [SKILL.md](../.agents/skills/project-info/SKILL.md) | Updated: 2026-03-15

---

## Endpoint

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/projects/{project_id}` | DELETE | Delete project with cleanup |

---

## Delete Project

```
DELETE /projects/{project_id}?force=false
```

**Query Params:**
- `force` (bool, optional): Force deletion even if validation fails (DANGEROUS)

**Response:**
```json
{
  "success": true,
  "message": "Project deleted successfully",
  "cleanup_results": {
    "project_path_removed": true,
    "pm2_stopped": true,
    "nginx_removed": true,
    "database_dropped": true
  }
}
```

**File:** `app.py:1204-1355`

---

## Cleanup Steps

| Step | Description |
|------|-------------|
| 1 | Stop PM2 processes |
| 2 | Remove nginx config |
| 3 | Drop project database |
| 4 | Remove project directory |
| 5 | Delete DB record |

---

## Safety Checks

- Validates project exists
- Blocks master database deletion
- Validates database name pattern
- Force flag required for unsafe deletions

---

## Related

- [Project Creation](project_creation.md)
