# Dashboard API

> **Purpose:** Single API powering the entire Home page
> Last updated: 2026-03-23

---

## Overview

The Dashboard API returns **everything needed for the home page in ONE response** - no multiple API calls required.

---

## Endpoint

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/dashboard/home` | GET | Complete dashboard data |

---

## GET /dashboard/home

Get complete dashboard data for home page in a single call.

### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `project_limit` | int | 50 | Max projects to return (1-100) |

### Response

```json
{
  "server": {
    "status": "connected",
    "label": "My Server",
    "message": "Connected and running smoothly",
    "metrics": {
      "cpu_usage": 21.4,
      "ram_usage": 65.2,
      "ram_total": 16384,
      "ram_used": 10680,
      "uptime_seconds": 92000
    }
  },
  "stats": {
    "running": 1,
    "needs_fix": 1,
    "stopped": 1,
    "creating": 1
  },
  "projects": [
    {
      "id": 1,
      "name": "Crypto Price Website",
      "description": "Live cryptocurrency prices",
      "status": "running",
      "status_label": "Running",
      "domain": "https://crypto.mysite.com",
      "last_active": "2026-03-23T12:00:00Z",
      "actions": ["view", "pause", "code", "publish", "delete"]
    },
    {
      "id": 2,
      "name": "Trading Bot",
      "description": "Automated trading",
      "status": "needs_fix",
      "status_label": "Needs Fix",
      "domain": "https://trading.mysite.com",
      "last_active": "2026-03-22T10:00:00Z",
      "actions": ["fix", "code", "delete"]
    },
    {
      "id": 3,
      "name": "New SaaS App",
      "description": null,
      "status": "creating",
      "status_label": "AI customizing...",
      "domain": null,
      "last_active": null,
      "progress": 8,
      "actions": []
    }
  ],
  "highlight": {
    "needs_fix_project_id": 2
  },
  "suggestions": [
    {
      "type": "fix",
      "title": "Fix the Trading Bot",
      "project_id": 2
    },
    {
      "type": "create",
      "title": "Create something new"
    },
    {
      "type": "activity",
      "title": "Review recent activity"
    }
  ]
}
```

---

## Response Sections

### server

Server status and performance metrics.

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Server status (`connected`, `warning`, `error`) |
| `label` | string | Display label |
| `message` | string | Status message |
| `metrics` | object | Performance metrics |

**Metrics:**

| Field | Type | Description |
|-------|------|-------------|
| `cpu_usage` | float | CPU usage percentage |
| `ram_usage` | float | RAM usage percentage |
| `ram_total` | int | Total RAM in MB |
| `ram_used` | int | Used RAM in MB |
| `uptime_seconds` | int | Server uptime in seconds |

---

### stats

Project counts by status category.

| Field | Type | Description |
|-------|------|-------------|
| `running` | int | Projects with status `ready` |
| `needs_fix` | int | Projects with status `error` or `failed` |
| `stopped` | int | Projects with status `stopped` |
| `creating` | int | Projects in creation phases |

---

### projects

List of user's projects with UI-ready fields.

| Field | Type | Description |
|-------|------|-------------|
| `id` | int | Project ID |
| `name` | string | Project name |
| `description` | string? | Project description |
| `status` | string | UI status (see mapping below) |
| `status_label` | string | Human-readable status |
| `domain` | string? | Project URL (with https://) |
| `last_active` | string? | ISO timestamp of last message |
| `actions` | string[] | Available actions |
| `progress` | int? | Progress 1-9 (only for creating status) |

---

### highlight

Highlighted items for user attention.

| Field | Type | Description |
|-------|------|-------------|
| `needs_fix_project_id` | int? | ID of project needing fix |

---

### suggestions

Action suggestions for the user.

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | `fix`, `create`, or `activity` |
| `title` | string | Suggestion text |
| `project_id` | int? | Project ID (for `fix` type) |

---

## Status Mapping

Database status is mapped to UI-friendly values:

| DB Status | UI Status | Label |
|-----------|-----------|-------|
| `ready` | `running` | Running |
| `error` | `needs_fix` | Needs Fix |
| `failed` | `needs_fix` | Needs Fix |
| `stopped` | `stopped` | Stopped |
| `creating` | `creating` | Setting up... |
| `infrastructure_provisioning` | `creating` | Provisioning... |
| `ai_provisioning` | `creating` | AI customizing... |

---

## Progress Mapping

Progress percentage for creating states:

| Status | Progress |
|--------|----------|
| `creating` | 1 |
| `infrastructure_provisioning` | 4 |
| `ai_provisioning` | 8 |
| `ready` | 9 |

---

## Actions by Status

| Status | Actions |
|--------|---------|
| `running` | `view`, `pause`, `code`, `publish`, `delete` |
| `needs_fix` | `fix`, `code`, `delete` |
| `stopped` | `start`, `code`, `delete` |
| `creating` | (none) |

---

## Performance

- **Single API call** - No multiple requests
- **Optimized queries** - FILTER aggregation, LEFT JOINs
- **<100ms target** - Timing logged in server

### Indexes Used

```sql
-- From recent_activity_service.py
CREATE INDEX idx_messages_session_created ON messages(session_id, created_at DESC);
CREATE INDEX idx_sessions_project ON sessions(project_id);
CREATE INDEX idx_projects_user ON projects(user_id);
```

---

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| No projects | Empty `projects` array, all stats = 0 |
| No messages | `last_active = null` |
| Metrics fail | Fallback to zero values |
| No broken projects | `highlight = {}`, no fix suggestion |

---

## File References

| File | Lines | Description |
|------|-------|-------------|
| `dashboard_service.py` | 1-400 | Dashboard service with all logic |
| `app.py` | 3595-3680 | API endpoint definition |

---

## Frontend Integration

```typescript
// Single call for entire home page
const response = await fetch('/dashboard/home');
const dashboard = await response.json();

// Use sections directly
const { server, stats, projects, highlight, suggestions } = dashboard;

// Display server status
if (server.status === 'connected') {
  showGreenBadge(server.metrics);
}

// Render project cards
projects.forEach(project => {
  renderProjectCard({
    title: project.name,
    status: project.status_label,
    actions: project.actions
  });
});

// Show highlight badge
if (highlight.needs_fix_project_id) {
  showNeedsFixBadge(highlight.needs_fix_project_id);
}

// Render suggestions
suggestions.forEach(s => {
  if (s.type === 'fix') {
    showFixButton(s.project_id, s.title);
  }
});
```
