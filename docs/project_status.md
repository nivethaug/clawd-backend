# Project Status

> [TOC](toc.md) | Updated: 2026-07-12

## Purpose

Project status endpoints let the UI track creation, deployment, and AI refinement state.

## Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/projects/{project_id}/status` | Current database status |
| GET | `/projects/{project_id}/ai-status` | AI/pipeline process details |
| GET | `/projects/{project_id}/claude-session` | Claude Code session metadata for website projects |

All endpoints require project ownership.

## Status Values

Current code treats these as creation/in-progress states:

```text
creating, scaffolded, initializing, building, deploying, verifying,
provisioning, infrastructure_provisioning, ai_provisioning
```

Other important statuses:

| Status | Meaning |
| --- | --- |
| `ready` | Project is built and available |
| `stopped` | Runtime is stopped |
| `error` | Website/runtime needs fix |
| `failed` | Bot/scheduler pipeline or project creation failed |

## GET `/projects/{project_id}/status`

Response:

```json
{
  "status": "ready"
}
```

## GET `/projects/{project_id}/ai-status`

Response shape:

```json
{
  "project_id": 1624,
  "project_name": "check",
  "project_status": "ai_provisioning",
  "ai_refinement_status": "in_progress",
  "processes": {
    "openclaw_wrapper": {
      "running": true,
      "pid": 12345,
      "elapsed": "00:02:10"
    },
    "claude_code": {
      "running": false,
      "pid": null
    }
  },
  "paths": {
    "project": "/root/clawd-projects/1624-check",
    "frontend": "/root/clawd-projects/1624-check/frontend"
  },
  "recent_activity": {
    "files_modified": ["Home.tsx"],
    "count": 1
  },
  "phase_info": {
    "phase": 8,
    "phase_name": "AI-Driven Frontend Refinement",
    "total_phases": 8,
    "completed_phases": 7
  }
}
```

`ai_refinement_status` is derived from project status:

| Project status | AI status |
| --- | --- |
| `ai_provisioning` | `in_progress` |
| `ready` | `completed` |
| `failed` | `failed` |
| Anything else | `not_started` |

## GET `/projects/{project_id}/claude-session`

Returns Claude Code session information for website projects. If a project has no Claude session, the endpoint returns `404`.

## Related

- [project_creation.md](./project_creation.md)
- [dashboard.md](./dashboard.md)
