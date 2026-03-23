# Recent Activity API

> **Purpose:** Fetch recent work/activity grouped by project, sorted by latest message timestamp
> Last updated: 2026-03-23

---

## Overview

The Recent Activity API powers the **Activity page (Recent Work UI)**. It returns projects sorted by their most recent message across all sessions, with optional message previews and session statistics.

---

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/projects/recent-activity` | GET | Full activity list with preview |
| `/projects/recent-activity/simple` | GET | Lightweight version (no preview) |
| `/projects/{id}/activity` | GET | Detailed single-project activity |

---

## GET /projects/recent-activity

Fetch recent activity grouped by project, sorted by latest message timestamp.

### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 20 | Max projects to return (1-100) |
| `offset` | int | 0 | Pagination offset |
| `include_preview` | bool | true | Include last message preview |

### Response

```json
{
  "items": [
    {
      "project_id": 1,
      "project_name": "Trading Bot",
      "project_description": "AI-powered trading bot",
      "project_status": "active",
      "domain": "trading.dreambigwithai.com",
      "last_activity": "2026-03-23T14:06:16Z",
      "total_messages": 12,
      "total_sessions": 3,
      "last_message_preview": "Fixed API connection issue...",
      "last_session_id": 5,
      "last_session_label": "Bug Fixes",
      "active_session_id": 5
    }
  ],
  "total": 42,
  "limit": 20,
  "offset": 0
}
```

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `project_id` | int | Project ID |
| `project_name` | string | Project name |
| `project_description` | string? | Project description |
| `project_status` | string? | Project status (creating, active, error) |
| `domain` | string? | Project domain |
| `last_activity` | string | ISO timestamp of latest message |
| `total_messages` | int | Total messages across all sessions |
| `total_sessions` | int | Total sessions count |
| `last_message_preview` | string? | Preview of last message (truncated to 100 chars) |
| `last_session_id` | int? | ID of session with latest message |
| `last_session_label` | string? | Label of session with latest message |
| `active_session_id` | int? | Active session ID (for lock badge) |

### Example Request

```bash
curl "http://localhost:8000/projects/recent-activity?limit=10&include_preview=true"
```

---

## GET /projects/recent-activity/simple

Simplified version without preview - faster response.

### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 20 | Max projects to return (1-100) |

### Response

```json
{
  "items": [
    {
      "project_id": 1,
      "project_name": "Trading Bot",
      "project_status": "active",
      "active_session_id": 5,
      "last_activity": "2026-03-23T14:06:16Z",
      "total_sessions": 3,
      "total_messages": 12
    }
  ],
  "count": 10
}
```

---

## GET /projects/{project_id}/activity

Detailed activity for a single project, including recent messages.

### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `project_id` | int | Project ID |

### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `message_limit` | int | 10 | Max recent messages (1-50) |

### Response

```json
{
  "project_id": 1,
  "project_name": "Trading Bot",
  "description": "AI-powered trading bot",
  "status": "active",
  "domain": "trading.dreambigwithai.com",
  "active_session_id": 5,
  "last_activity": "2026-03-23T14:06:16Z",
  "total_sessions": 3,
  "total_messages": 12,
  "recent_messages": [
    {
      "id": 123,
      "session_id": 5,
      "session_label": "Bug Fixes",
      "role": "assistant",
      "content": "Fixed API connection issue...",
      "created_at": "2026-03-23T14:06:16Z"
    }
  ]
}
```

---

## Performance

### Indexes

The following indexes are automatically created on module load:

```sql
-- Composite index for messages by session + time
CREATE INDEX idx_messages_session_created 
ON messages(session_id, created_at DESC);

-- Index for session-project joins
CREATE INDEX idx_sessions_project 
ON sessions(project_id);

-- Index for project-user filtering
CREATE INDEX idx_projects_user 
ON projects(user_id);

-- Index for messages with role filter
CREATE INDEX idx_messages_session_role_created 
ON messages(session_id, role, created_at DESC);
```

### Query Optimization

- Uses PostgreSQL `DISTINCT ON` for single-pass query
- CTE-based aggregation for stats
- Preview truncated to 100 chars
- Pagination via `LIMIT`/`OFFSET`

---

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| Project with no messages | Excluded from results |
| Deleted sessions | Ignored (INNER JOIN) |
| Large datasets | Use pagination (limit/offset) |
| Multiple sessions | Picks latest message across all |

---

## File References

| File | Lines | Description |
|------|-------|-------------|
| `recent_activity_service.py` | 1-400 | Service with optimized queries |
| `app.py` | 3485-3590 | API endpoint definitions |

---

## Frontend Integration

### Activity Page Usage

```typescript
// Fetch recent activity
const response = await fetch('/projects/recent-activity?limit=20');
const { items, total } = await response.json();

// Display project cards sorted by last_activity
items.forEach(project => {
  // Show lock badge if active_session_id exists
  // Show last_message_preview as subtitle
  // Format last_activity as relative time
});
```

### Lock Badge

Use `active_session_id` to show a lock badge when another session is active:

```typescript
{project.active_session_id && (
  <LockBadge sessionId={project.active_session_id} />
)}
```
