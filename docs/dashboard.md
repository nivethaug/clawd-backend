# Dashboard API

> [TOC](toc.md) | Updated: 2026-07-12

## Purpose

`GET /dashboard/home` returns all data needed for the authenticated home dashboard in one response.

## Endpoint

`GET /dashboard/home?project_limit=50`

Requires `Authorization: Bearer <token>`.

## Response Sections

| Section | Description |
| --- | --- |
| `server` | Server connection status and psutil metrics |
| `stats` | Project counts by UI status bucket |
| `projects` | User projects with UI-ready status/actions/last activity |
| `highlight` | Most recent project needing a fix |
| `suggestions` | Suggested next actions |

## Example Response

```json
{
  "server": {
    "status": "connected",
    "label": "My Server",
    "message": "Connected and running smoothly",
    "metrics": {
      "cpu_usage": 12.3,
      "ram_usage": 37.8,
      "ram_total": 16000,
      "ram_used": 6048,
      "uptime_seconds": 223000
    }
  },
  "stats": {
    "running": 4,
    "needs_fix": 1,
    "stopped": 0,
    "creating": 1
  },
  "projects": [
    {
      "id": 1625,
      "name": "panda",
      "description": "Premium dark-mode CPQ workspace",
      "type_id": 1,
      "status": "running",
      "status_label": "Running",
      "domain": "https://panda.dreamagent.cloud",
      "last_active": "2026-07-12T10:00:00Z",
      "actions": ["view", "pause", "code", "publish", "delete"]
    }
  ],
  "highlight": {
    "needs_fix_project_id": 1620,
    "needs_fix_project_name": "example"
  },
  "suggestions": [
    {"type": "fix", "title": "Fix the example", "project_id": 1620},
    {"type": "create", "title": "Create something new"},
    {"type": "activity", "title": "Review recent activity"}
  ]
}
```

## Status Mapping

Current dashboard mapping in `dashboard_service.py`:

| DB status | UI status | Label |
| --- | --- | --- |
| `ready` | `running` | Running |
| `error` | `needs_fix` | Needs Fix |
| `failed` | `needs_fix` | Needs Fix |
| `stopped` | `stopped` | Stopped |
| `creating` | `creating` | Setting up... |
| `scaffolded` | `creating` | Preparing workspace... |
| `initializing` | `creating` | Initializing... |
| `building` | `creating` | Building... |
| `deploying` | `creating` | Deploying... |
| `verifying` | `creating` | Verifying... |
| `provisioning` | `creating` | Provisioning... |
| `infrastructure_provisioning` | `creating` | Provisioning... |
| `ai_provisioning` | `creating` | AI customizing... |

Creating statuses expose a `progress` value and no actions.

## Action Mapping

| DB status | Actions |
| --- | --- |
| `ready` | `view`, `pause`, `code`, `publish`, `delete` |
| `error`, `failed` | `fix`, `code`, `delete` |
| `stopped` | `start`, `code`, `delete` |
| Creating statuses | none |

## Related

- [recent_activity.md](./recent_activity.md)
- [project_status.md](./project_status.md)
- [backend_api_reference.md](./backend_api_reference.md)
