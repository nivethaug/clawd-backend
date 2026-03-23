# Session Locking

Single active session per project with strict database-backed locking.

## Overview

Each project can have **only one active session at a time**. When a session sends its first message, it acquires a lock on the project. Other sessions are blocked until the lock is released.

## Behavior

| Scenario | Result |
|----------|--------|
| Session A sends message | ✅ Locks project |
| Session B tries to send message | ❌ HTTP 423 (Locked) |
| Session A completes/deleted | ✅ Lock released |
| Session B retries | ✅ Allowed |

## API Endpoints

### Get Active Session

```http
GET /projects/{project_id}/active-session
```

Returns the currently active (locked) session for a project.

**Response (Locked):**
```json
{
  "active_session_id": 123,
  "session_name": "Design Session"
}
```

**Response (Unlocked):**
```json
{
  "active_session_id": null,
  "session_name": null
}
```

### Force Release Lock (Admin)

```http
DELETE /projects/{project_id}/lock
```

Force release any lock on a project. Use for crash recovery.

**Response:**
```json
{
  "success": true,
  "released_session_id": 123,
  "message": "Lock released from session 123"
}
```

### Release Session Lock

```http
POST /sessions/{session_id}/release-lock
```

Explicitly release a session's lock without deleting the session. Useful for "End Chat" buttons.

**Response:**
```json
{
  "success": true,
  "message": "Lock released"
}
```

## Error Response

When a session tries to send a message while another session is active:

**HTTP 423 Locked:**
```json
{
  "detail": {
    "error": "Another session is active",
    "active_session_id": 123
  }
}
```

## Lock Lifecycle

1. **Acquisition**: Lock is acquired when sending a message via `/chat` or `/chat/stream`
2. **Holding**: Lock persists during the entire chat session
3. **Release**: Lock is released when:
   - Session is deleted
   - Explicit release via `/sessions/{session_id}/release-lock`
   - Admin force release via `/projects/{project_id}/lock`

## Frontend Integration

### Check if project is locked before starting chat:

```typescript
const response = await fetch(`/projects/${projectId}/active-session`);
const data = await response.json();

if (data.active_session_id) {
  // Show warning: "Another session is active"
  // Option to wait or force release (admin only)
} else {
  // Safe to start chatting
}
```

### Handle 423 error:

```typescript
try {
  await sendChatMessage(projectId, message);
} catch (error) {
  if (error.status === 423) {
    const detail = error.detail;
    // Show: "Session locked by another session (ID: {detail.active_session_id})"
    // Poll for unlock or show "End Session" button
  }
}
```

### End session explicitly:

```typescript
// When user clicks "End Chat"
await fetch(`/sessions/${sessionId}/release-lock`, { method: 'POST' });
```

## Implementation Details

- **Database Column**: `projects.active_session_id` (INTEGER, nullable)
- **Lock Method**: PostgreSQL `SELECT ... FOR UPDATE` (row-level locking)
- **Idempotent**: Same session can acquire lock multiple times safely
- **No Timeout**: Locks persist until explicitly released (no auto-release)

## Crash Recovery

If the server crashes while a session is active, the lock will persist. Use the admin endpoint to force release:

```bash
curl -X DELETE http://localhost:8002/projects/1/lock
```

Or directly in database:
```sql
UPDATE projects SET active_session_id = NULL WHERE id = 1;
```
