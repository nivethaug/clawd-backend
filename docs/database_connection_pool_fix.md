# Database Connection Pool Fix - Delete Flow Blocking Issue

> Date: 2026-03-16
> Severity: CRITICAL
> Status: FIXED

---

## Problem Summary

The project delete endpoint (`DELETE /projects/{id}`) was causing **database connection pool exhaustion**, leading to other API calls blocking and timing out.

## Root Cause

**Connection Leak in `delete_project_database()`:**

```python
# database_postgres.py:386 (BEFORE FIX)
conn = pool.getconn()  # Opens connection from pool

with conn.cursor() as cur:
    cur.execute("DROP DATABASE ...")
    conn.commit()
    return {...}  # ❌ RETURNS WITHOUT pool.putconn(conn)!

except Exception as e:
    return {...}  # ❌ EXCEPTION ALSO LEAKS CONNECTION!
```

**Missing:** `pool.putconn(conn)` in finally block

## Impact

- **Every delete operation leaked 1 connection**
- Pool size: 50 connections
- After 50 deletes: **Pool exhausted**
- All subsequent API calls blocked waiting for connections
- Symptoms: Timeouts, 504 errors, unresponsive API

## Delete Flow Analysis

```python
# Step 1: Get project info (Connection #1)
with get_db() as conn:
    project = conn.execute("SELECT * FROM projects WHERE id = ?", ...)
    sessions = conn.execute("SELECT session_key FROM sessions WHERE project_id = ?", ...)
# Connection #1 returned to pool ✓

# Step 2: Long-running cleanup (30-60 seconds)
cleanup_infrastructure(project_path):
    ├─ PM2 stop/restart (5-10s)
    ├─ Nginx config removal (1-2s)
    ├─ SSL cleanup (2-5s)
    ├─ DNS deletion (5-10s)
    ├─ Database DROP (10-30s) ← Opens Connection #2 (LEAKED)
    └─ File deletion (5-10s)

# Step 3: Delete records (Connection #3)
with get_db() as conn:
    conn.execute("DELETE FROM messages WHERE session_id IN ...")
    conn.execute("DELETE FROM sessions WHERE project_id = ?")
    conn.execute("DELETE FROM projects WHERE id = ?")
# Connection #3 returned to pool ✓
```

**Problem:** Connection #2 opened in `delete_project_database()` was never returned to pool.

## Solution Implemented

### 1. Connection Leak Fix

```python
# database_postgres.py:386 (AFTER FIX)
conn = None
try:
    pool = get_connection_pool()
    conn = pool.getconn()
    
    with conn.cursor() as cur:
        # Set timeout to prevent hanging
        cur.execute("SET statement_timeout = 60000")
        
        # Drop operations
        cur.execute("DROP USER IF EXISTS ...")
        cur.execute("DROP DATABASE IF EXISTS ...")
        conn.commit()
        
        return {"success": True, ...}

except Exception as e:
    logger.error(f"Failed to delete project database: {e}")
    return {"success": False, "error": str(e)}

finally:
    # CRITICAL: Always return connection to pool
    if conn:
        try:
            pool.putconn(conn)
            logger.debug("✓ Connection returned to pool")
        except Exception as e:
            logger.error(f"❌ Failed to return connection to pool: {e}")
```

### 2. Timeout Protection

Added 60-second statement timeout to prevent DROP DATABASE from hanging indefinitely:

```python
cur.execute("SET statement_timeout = 60000")
```

### 3. Pool Monitoring

Added `get_pool_status()` function for monitoring:

```python
def get_pool_status() -> Dict[str, Any]:
    """
    Get connection pool status for monitoring.
    """
    pool = get_connection_pool()
    return {
        "pool_size": 50,
        "used_connections": len(pool._used),
        "idle_connections": len(pool._pool),
        "utilization": f"{(len(pool._used) / 50) * 100:.1f}%"
    }
```

## Verification

To verify the fix is working:

1. **Check pool status before/after delete:**
   ```python
   from database_postgres import get_pool_status
   
   # Before delete
   print(get_pool_status())
   # {"used_connections": 5, "idle_connections": 45, "utilization": "10.0%"}
   
   # Delete project
   DELETE /projects/123
   
   # After delete
   print(get_pool_status())
   # {"used_connections": 5, "idle_connections": 45, "utilization": "10.0%"}
   # ✓ Should be same - no leak!
   ```

2. **Monitor PM2 logs for connection returns:**
   ```bash
   pm2 logs backend | grep "Connection returned to pool"
   ```

3. **Run 50+ deletes without pool exhaustion:**
   ```bash
   # Should not see timeout errors
   for i in {1..60}; do
     curl -X DELETE http://localhost:3001/projects/$i
   done
   ```

## Lessons Learned

1. **Always use try/finally with connection pools**
   - Manual `pool.getconn()` requires manual `pool.putconn(conn)`
   - Never rely on garbage collection to return connections

2. **Context managers are safer**
   - `with get_db() as conn:` automatically returns connections
   - Use context managers wherever possible

3. **Add timeout protection**
   - Long-running operations (DROP DATABASE) can hang
   - Set statement_timeout to prevent indefinite blocking

4. **Monitor pool utilization**
   - Add metrics for connection pool health
   - Alert when utilization > 80%

## Related Files

- `database_postgres.py:355-435` - delete_project_database() function
- `database_postgres.py:130-160` - get_db() context manager
- `app.py:1204-1357` - DELETE /projects/{id} endpoint
- `app.py:1060-1204` - cleanup_infrastructure() function

## References

- [psycopg2 Connection Pool Documentation](https://www.psycopg.org/docs/pool.html)
- [PostgreSQL Statement Timeout](https://www.postgresql.org/docs/current/runtime-config-client.html#GUC-STATEMENT-TIMEOUT)
