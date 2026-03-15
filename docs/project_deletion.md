# Project Deletion - Complete Reference

> [TOC](toc.md) | [SKILL.md](../.agents/skills/project-info/SKILL.md) | Updated: 2026-03-15

---

## API Endpoints

| Endpoint | Method | File | Lines | Description |
|----------|--------|------|-------|-------------|
| `/projects/{id}` | DELETE | `app.py` | 1204-1357 | Delete project with cleanup |
| `/projects/{id}` | PUT | `app.py` | 1357-1436 | Update project metadata |

---

## DELETE /projects/{id}

**File:** `app.py:1204-1357`

Delete a project with full infrastructure cleanup.

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `force` | bool | Force deletion even if validation fails (DANGEROUS) |

**Response:**
```json
{
  "success": true,
  "message": "Project deleted successfully",
  "cleanup_results": {
    "database_dropped": true,
    "pm2_stopped": true,
    "nginx_removed": true,
    "files_removed": true,
    "dns_removed": true
  }
}
```

**Cleanup Steps:**

| Step | Description |
|------|-------------|
| 1 | Get project info from database |
| 2 | Validate not deleting master database |
| 3 | Stop PM2 processes |
| 4 | Remove nginx config |
| 5 | Drop project database |
| 6 | Remove DNS records |
| 7 | Delete project files |
| 8 | Delete database record |

**Security:**
- Master database deletion is blocked
- Validates project database name pattern
- Force flag logged as warning

---

## PUT /projects/{id}

**File:** `app.py:1357-1436`

Update project metadata.

**Request:**
```json
{
  "name": "new-name",
  "domain": "new-domain",
  "description": "Updated description",
  "status": "ready"
}
```

**Response:**
```json
{
  "id": 123,
  "name": "new-name",
  "domain": "new-domain",
  "status": "ready",
  "updated_at": "2026-03-15T10:30:00"
}
```

---

## Related

- [Project Creation](project_creation.md)
- [Project Status](project_status.md)
