# Project Update and Deletion

> [TOC](toc.md) | Updated: 2026-07-12

## Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| PUT | `/projects/{project_id}` | Update project name/description |
| DELETE | `/projects/{project_id}` | Delete project and start background infrastructure cleanup |

Both endpoints require project ownership.

## Update Project

Only `name` and `description` can be changed.

```json
{
  "name": "new name",
  "description": "Updated description"
}
```

The backend explicitly rejects `typeId` / `type_id` and `domain` changes after creation.

Response is the updated `ProjectResponse`.

## Delete Project

`DELETE /projects/{project_id}?force=false`

Deletion flow:

1. Validates project ownership.
2. Validates master database safety.
3. Attempts GitHub repository deletion when `repo_url` exists.
4. Deletes messages, sessions, and project row immediately.
5. Starts infrastructure cleanup in a background task.
6. Returns immediately so the UI can remove the project card.

Response:

```json
{
  "status": "deleted",
  "message": "Project deleted successfully (infrastructure cleanup running in background)",
  "project_id": 1624,
  "project_name": "check",
  "cleanup": "running"
}
```

## Cleanup Scope

Cleanup uses `cleanup_infrastructure()` with database-provided domain and ports.

| Project type | Cleanup behavior |
| --- | --- |
| Website | PM2 frontend/backend, nginx, SSL, DNS, project DB/user, project directory |
| Telegram | Telegram-specific PM2/webhook/nginx/SSL/DNS cleanup |
| Discord | Discord-specific PM2/nginx/SSL/DNS cleanup |
| Scheduler | Scheduler jobs/logs and project directory |

The background task also removes matching OpenClaw session entries and JSONL transcript files when possible.

## Force Delete

`force=true` bypasses some project database deletion validation. It is logged as a warning and should only be used for recovery.

## Related

- [project_creation.md](./project_creation.md)
- [project_status.md](./project_status.md)
