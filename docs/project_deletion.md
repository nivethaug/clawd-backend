# Project Deletion - Complete Reference

> [TOC](toc.md) | [SKILL.md](../.agents/skills/project-info/SKILL.md) | Updated: 2026-03-16

---

## Performance Update (2026-03-16)

**ASYNC DELETE**: Delete API now returns immediately (<1s) instead of waiting for cleanup (30-70s).

- ✅ **Before**: 30-70 second blocking request
- ✅ **After**: <1 second immediate response
- ✅ Cleanup runs in background
- ✅ Frontend can poll for completion

---

## API Endpoints

| Endpoint | Method | File | Lines | Description |
|----------|--------|------|-------|-------------|
| `/projects/{id}` | DELETE | `app.py` | 1204-1357 | Delete project with async cleanup |
| `/projects/{id}` | PUT | `app.py` | 1357-1436 | Update project metadata |

---

## DELETE /projects/{id}

**File:** `app.py:1204-1357`

Delete a project with full infrastructure cleanup (ASYNC).

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| `force` | bool | Force deletion even if validation fails (DANGEROUS) |

**Response (Immediate):**
```json
{
  "status": "deleting",
  "message": "Project deletion started (cleanup running in background)",
  "project_id": 123,
  "project_name": "my-project",
  "cleanup": "running"
}
```

**Cleanup Steps (Background):**

| Step | Duration | Description |
|------|----------|-------------|
| 1 | Instant | Mark project as 'deleting' |
| 2 | Instant | Return immediate response |
| 3 | 5-10s | Stop PM2 processes (background) |
| 4 | 1-2s | Remove nginx config (background) |
| 5 | 2-5s | Remove SSL certificates (background) |
| 6 | 5-10s | Remove DNS records (background) |
| 7 | 10-30s | Drop project database (background) |
| 8 | 5-10s | Delete project files (background) |
| 9 | Instant | Delete database record (background) |

**Total Duration**: 30-70 seconds (but API returns immediately)

**Frontend Integration:**

```typescript
// Step 1: Call delete API (returns immediately)
const response = await fetch(`/projects/${projectId}`, { method: 'DELETE' });
const data = await response.json();

// Response: { status: "deleting", ... }
showToast("Project deletion started...");

// Step 2: Optionally poll for completion
const pollInterval = setInterval(async () => {
  const status = await fetch(`/projects/${projectId}`);
  if (status.status === 404) {
    // Project fully deleted
    clearInterval(pollInterval);
    showToast("Project deleted successfully");
  }
}, 5000); // Poll every 5 seconds

// Or just show "Deleting..." and let user continue
```

**Security:**
- Master database deletion is blocked
- Validates project database name pattern
- Force flag logged as warning

**Logs:**
- Background cleanup logs with `[BG]` prefix
- Example: `[BG] Starting infrastructure cleanup for project 123`
- Example: `[BG] ✅ Cleanup completed for project 123`

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
  "updated_at": "2026-03-16T10:30:00"
}
```

---

## Architecture

### Before (Synchronous - SLOW)

```python
@app.delete("/projects/{id}")
async def delete_project(id: int):
    # Step 1: PM2 cleanup (5-10s) ← BLOCKS
    cleanup_pm2()
    
    # Step 2: Nginx cleanup (1-2s) ← BLOCKS
    cleanup_nginx()
    
    # Step 3: Database DROP (10-30s) ← BLOCKS
    drop_database()
    
    # ... more blocking operations
    
    return {"status": "deleted"}  # Returns after 30-70s
```

### After (Asynchronous - FAST)

```python
@app.delete("/projects/{id}")
async def delete_project(id: int):
    # Mark as deleting
    update_status(id, "deleting")
    
    # Start background task
    asyncio.create_task(cleanup_task(id))
    
    # Return immediately
    return {"status": "deleting"}  # Returns in <1s

async def cleanup_task(id: int):
    # All cleanup runs in background
    cleanup_pm2()      # 5-10s
    cleanup_nginx()    # 1-2s
    drop_database()    # 10-30s
    # ...
    logger.info("[BG] ✅ Cleanup completed")
```

---

## Related

- [Project Creation](project_creation.md)
- [Project Status](project_status.md)
- [Database Connection Pool Fix](database_connection_pool_fix.md)
