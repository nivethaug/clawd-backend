# Backend Deployment Paths & Architecture (PostgreSQL Edition)

This document explains how we maintain separate deployments for **main** (production on port 8002) and **feature branches** (development on port 8001) for FastAPI backend with **PostgreSQL support**.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────┐
│  SOURCE CODE (/root/clawd-backend/)           │
│                                              │
│  ├─ main branch (stable)                 │
│  │  ├─ app.py                                    │
│  │  ├─ database_adapter.py (universal backend)        │
│  │  ├─ database_postgres.py (PostgreSQL module)      │
│  │  ├─ database.py (SQLite fallback)               │
│  │  └─ start-backend.sh                          │
│                                              │
│  └─ feature/* branches (development)       │
│     ├─ (modified Python files)                     │
│     └─ start-backend.sh (may use port 8001)      │
└──────────────────┬──────────────────────────────────┘
                   │
                   │ (Python runs in place, backend selected at runtime)
                   ▼
┌─────────────────────────────────────────────────────┐
│  DATABASE SYSTEM                                  │
│                                              │
│  ├─ PostgreSQL Docker (dreampilot-postgres)       │
│  │  ├─ Container: Up 8 days                      │
│  │  ├─ Port: 5432 (127.0.0.1:5432)           │
│  │  └─ Version: PostgreSQL 15.16                 │
│                                              │
│  └─ SQLite Fallback (/root/clawd-backend/...)       │
│     └─ Available via USE_POSTGRES=false             │
└──────────────────┬──────────────────────────────────┘
                   │
                   │ (connection pooling, 5-20 connections)
                   ▼
┌─────────────────────────────────────────────────────┐
│  RUNNING APPLICATION (Python FastAPI)         │
│  Serves source code directly from .py files       │
│  Uses: Uvicorn ASGI server                   │
│  Database: PostgreSQL or SQLite (runtime selected)  │
└──────────────────┬──────────────────────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
        │ PM2 Process          │ PM2 Process (Optional)
        │                      │
        ▼                      ▼
┌──────────────┐      ┌─────────────────────┐
│ Port 8002    │      │ Port 8001           │
│ Production   │      │ Development           │
│              │      │                      │
│ Server: Uvicorn │      │ Server: Uvicorn       │
│ Process: main│      │ Process: feature/*   │
│ Branch: main  │      │ Branch: feature/*     │
│ URL:          │      │ URL:                 │
│ http://       │      │ http://              │
│ localhost:    │      │ localhost:           │
│ 8002         │      │ 8001                │
│              │      │                      │
│ API Public   │      │ API Public (Optional) │
│ http://195.   │      │ http://195.           │
│ 200.14.37:   │      │ 200.14.37:           │
│ 8002         │      │ 8001                 │
└──────────────┘      └─────────────────────┘
```

---

## Deployment Paths

### 1. Production (Main Branch - Port 8002)

| Property | Value |
|----------|--------|
| **Git Branch** | `main` |
| **Source Directory** | `/root/clawd-backend/` |
| **Server** | Uvicorn (FastAPI) |
| **Port** | 8002 |
| **Process** | PM2: `clawd-backend` |
| **Database** | PostgreSQL: `dreampilot` (Docker container) |
| **Environment Variable** | `USE_POSTGRES=true` (default) |
| **Database Connection** | Connection pooling (5-20 connections) |
| **Public URL** | http://195.200.14.37:8002 |

**Startup Commands:**
```bash
# Switch to main branch
cd /root/clawd-backend
git checkout main

# Restart PM2 process
pm2 restart clawd-backend

# Server runs on port 8002 with PostgreSQL
```

**PM2 Configuration:**
```json
{
  "name": "clawd-backend",
  "script": "/root/clawd-backend/start-backend.sh",
  "cwd": "/root/clawd-backend",
  "env": {
    "USE_POSTGRES": "true",
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "DB_NAME": "dreampilot",
    "DB_USER": "admin",
    "DB_PASSWORD": "StrongAdminPass123"
  }
}
```

**Startup Script:**
```bash
#!/bin/bash
# Clawd Backend Startup Script
# Supports both SQLite and PostgreSQL modes

cd /root/clawd-backend

# Activate virtual environment
source venv/bin/activate

# Check for PostgreSQL configuration
POSTGRES_ENV_FILE="/root/clawd-backend/.env.postgres"

if [ -f "$POSTGRES_ENV_FILE" ]; then
    # Load PostgreSQL environment variables
    source "$POSTGRES_ENV_FILE"
    
    # Set PostgreSQL mode
    export USE_POSTGRES=true
    
    echo "Starting backend with PostgreSQL database..."
    echo "  Host: $DB_HOST"
    echo "  Port: $DB_PORT"
    echo "  Database: $DB_NAME"
    echo "  User: $DB_USER"
else
    # SQLite mode (fallback/default)
    export USE_POSTGRES=false
    export DB_PATH="/root/clawd-backend/clawdbot_adapter.db"
    
    echo "Starting backend with SQLite database..."
    echo "  Database: $DB_PATH"
fi

# Start FastAPI application
exec venv/bin/uvicorn app:app --host 0.0.0.0 --port 8002
```

---

### 2. Development (Feature Branches - Port 8001 - Optional)

| Property | Value |
|----------|--------|
| **Git Branch** | `feature/*`, `fix/*`, `development/*` |
| **Source Directory** | `/root/clawd-backend/` |
| **Server** | Uvicorn (FastAPI) |
| **Port** | 8001 (optional) |
| **Process** | PM2: `clawd-backend-dev` (create if needed) |
| **Database** | Same as production (PostgreSQL) |
| **Environment Variable** | `USE_POSTGRES=true` |
| **Public URL** | http://195.200.14.37:8001 (if running) |

**Startup Commands:**
```bash
# Switch to feature branch
cd /root/clawd-backend
git checkout feature/my-feature

# Option 1: Use port 8001 with separate PM2 process
pm2 start clawd-backend-dev -- \
  -- /root/clawd-backend/start-backend.sh \
  --name "clawd-backend-dev" \
  --env USE_POSTGRES=true \
  --env DB_PORT=8001

# Option 2: Test locally with uvicorn directly
source venv/bin/activate
uvicorn app:app --host 0.0.0.0 --port 8001 --reload
```

---

## Database System Architecture

### Two-Tier Database Design

The system uses **two separate database types** with strict separation:

#### 1. MASTER DATABASE (Protected)
**Purpose:** Stores core application data
- **PostgreSQL:** `dreampilot` (default)
- **SQLite Fallback:** `/root/clawd-backend/clawdbot_adapter.db` (optional)

**Stores:**
- Projects (all projects metadata)
- Sessions (all chat sessions)
- Messages (all message history)
- Project Types (template definitions)

**Protection Rules:**
- ❌ NEVER deletable
- ❌ NEVER dropped
- ❌ NEVER truncated
- ❌ NEVER cleaned during project deletion
- ❌ No destructive operations allowed

**Protected Names (PostgreSQL):**
- `dreampilot` (master database)
- `defaultdb` (PostgreSQL default)
- `postgres` (PostgreSQL system)
- `information_schema`
- `pg_catalog`

#### 2. PROJECT DATABASE (Per-Project)
**Purpose:** Stores project-specific data
- **Naming Convention:** `{project_name}_db` (e.g., `newproject_db`)
- **Example:** `amazon_db`, `ecommerce22_db`

**Stores:**
- Project-specific tables
- Application data for individual projects

**Protection Rules:**
- ✅ CAN be deleted when project deleted
- ✅ CAN be dropped safely
- ✅ Only project-specific data
- ❌ No master DB data mixed in

---

## Database Connection Layer

### Universal Database Adapter (database_adapter.py)

```python
# Automatic backend selection based on environment
import os

# Check environment
USE_POSTGRES = os.getenv("USE_POSTGRES", "true").lower() == "true"

if USE_POSTGRES:
    # PostgreSQL mode (production)
    from database_postgres import (
        get_db,
        init_schema,
        is_master_database,
        validate_project_database_deletion,
        delete_project_database,
        test_connection,
        close_pool
    )
else:
    # SQLite mode (fallback/development)
    from database import (
        get_db,
        init_schema
    )
```

### PostgreSQL Connection Pooling

```python
# Connection pool configuration
connection_pool = pool.ThreadedConnectionPool(
    minconn=5,      # Minimum connections
    maxconn=20,     # Maximum connections
    host=DB_HOST,
    port=DB_PORT,
    database=DB_NAME,
    user=DB_USER,
    password=DB_PASSWORD,
    cursor_factory=RealDictCursor  # Dict-like row access
)
```

### Context Manager Usage

```python
# All database operations use context manager
from database_adapter import get_db

# Automatic connection management
with get_db() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM users")
        users = cur.fetchall()

# Connection automatically returned to pool on exit
```

---

## Master Database Protection

### Protection Rules

**The master database is CRITICAL and MUST NEVER be deleted!**

#### Operations BLOCKED:
- ❌ `DROP DATABASE dreampilot`
- ❌ `DELETE FROM projects` (all records)
- ❌ `DELETE FROM sessions` (all records)
- ❌ `DELETE FROM messages` (all records)
- ❌ Any destructive operation on master DB

#### Validation Function:
```python
def is_master_database(db_name: str) -> bool:
    """
    Check if database name is master database (protected).
    
    Returns:
        True if it's master database, False otherwise
    """
    protected_names = [DB_NAME, 'dreampilot', 'defaultdb', 'postgres']
    return db_name.lower() in [name.lower() for name in protected_names]
```

### Project Database Validation

**Before deleting project database, the system validates:**

1. **Pattern Check:** Database name matches `{project_name}_db`
2. **Master DB Check:** Not a protected database
3. **System DB Check:** Not a critical system database
4. **Force Flag:** Requires `force=true` for dangerous operations

**Validation Function:**
```python
def validate_project_database_deletion(project_name: str, db_name: str) -> tuple[bool, str]:
    """
    Validate if a project database deletion is allowed.
    
    Args:
        project_name: Name of the project
        db_name: Database name to delete
    
    Returns:
        Tuple of (is_allowed: bool, reason: str)
    """
    # Rule 1: Database name must match project pattern
    expected_db_name = f"{project_name.replace('-', '_')}_db"
    if db_name != expected_db_name:
        return False, f"Database name '{db_name}' doesn't match expected pattern '{expected_db_name}' for project '{project_name}'"
    
    # Rule 2: Database must NOT be master database
    if is_master_database(db_name):
        return False, f"Cannot delete master database '{db_name}'. Master database is protected from deletion."
    
    # Rule 3: Database must not be critical system database
    if db_name.lower() in ['information_schema', 'pg_catalog', 'template0', 'template1']:
        return False, f"Cannot delete system database '{db_name}'."
    
    return True, "Validation passed"
```

### Force Flag Implementation

**Prevents accidental deletions:**

```python
@app.delete("/projects/{project_id}")
async def delete_project(project_id: int, force: bool = False):
    """
    Delete a project with infrastructure cleanup and master DB protection.
    
    Args:
        project_id: ID of the project to delete
        force: Force deletion even if validation fails (DANGEROUS)
    
    Returns:
        Deletion status with cleanup results
    """
    # Security: Log force deletion attempts
    if force:
        logger.warning(f"⚠️ FORCE deletion requested for project {project_id}")
    
    # Validate before deletion
    is_allowed, reason = validate_project_database_deletion(project_name, db_name)
    
    if not is_allowed and not force:
        # Reject deletion
        logger.error(f"❌ Project DB deletion rejected: {reason}")
        raise HTTPException(status_code=400, detail={
            "success": False,
            "error": reason,
            "database": db_name,
            "force_required": True
        })
```

**Error Response Examples:**

```json
// Request without force flag
{
  "success": false,
  "error": "Cannot delete master database 'dreampilot'. Master database is protected from deletion.",
  "database": "dreampilot",
  "force_required": true
}

// Request with force flag
{
  "success": true,
  "database": "amazon_db",
  "warning": "⚠️ FORCE deletion requested for project 124"
}
```

---

## PostgreSQL Migration

### Migration Script: `migrate_to_postgres.py`

**Features:**
- ✅ Migrates all tables from SQLite to PostgreSQL
- ✅ Preserves IDs (SERIAL with sequence reset)
- ✅ Preserves relationships (FOREIGN KEY constraints)
- ✅ Idempotent (ON CONFLICT DO NOTHING/UPDATE)
- ✅ Validation step (compare record counts)
- ✅ Dry-run mode for testing

**Migration Commands:**

```bash
# Dry-run (test without migrating)
python3 migrate_to_postgres.py --dry-run

# Full migration
python3 migrate_to_postgres.py

# Validation only
python3 migrate_to_postgres.py --validate-only
```

**Tables Migrated:**
1. `users` - User accounts
2. `project_types` - Template definitions
3. `projects` - Project metadata
4. `sessions` - Chat sessions
5. `messages` - Message history

**Validation:**
```python
def validate_migration() -> bool:
    """
    Validate migration by comparing record counts.
    
    Returns:
        True if validation passed, False otherwise
    """
    logger.info("Validating migration...")
    
    # Compare counts for each table
    for table in ['users', 'project_types', 'projects', 'sessions', 'messages']:
        sqlite_count = get_sqlite_count(table)
        postgres_count = get_postgres_count(table)
        
        if sqlite_count == postgres_count:
            logger.info(f"  ✓ {table}: {sqlite_count} records")
        else:
            logger.error(f"  ✗ {table}: SQLite={sqlite_count}, PostgreSQL={postgres_count}")
```

---

## Database Deletion Flow

### Project Deletion (Safe)

```python
# Step 1: Validate database deletion
is_allowed, reason = validate_project_database_deletion(project_name, db_name)

if not is_allowed:
    # Reject deletion
    raise HTTPException(status_code=400, detail={
        "success": False,
        "error": reason,
        "database": db_name,
        "force_required": True
    })

# Step 2: Delete project database
result = delete_project_database(project_name, force=False)

if result["success"]:
    logger.info(f"✓ Deleted project database: {db_name}")
else:
    logger.error(f"✗ Failed to delete project database: {result['error']}")
```

### Master Database Protection (Blocked)

```python
# Attempt to delete master database
if is_master_database("dreampilot"):
    # BLOCKED!
    logger.error("❌ CRITICAL: Attempt to delete master database blocked!")
    raise HTTPException(status_code=403, detail="Master database is protected from deletion")
```

---

## Environment Variables

### PostgreSQL Mode (Default/Production)

```bash
# Required PostgreSQL connection
export DB_HOST=localhost
export DB_PORT=5432
export DB_NAME=dreampilot
export DB_USER=admin
export DB_PASSWORD=StrongAdminPass123

# Backend selection
export USE_POSTGRES=true

# Optional: Override default SQLite path (fallback)
# export DB_PATH=/root/clawd-backend/clawdbot_adapter.db
```

**Configuration File:**
```bash
# Create /root/clawd-backend/.env.postgres
# Copy from .env.postgres.example and update values
```

### SQLite Mode (Fallback/Development)

```bash
# Use SQLite instead of PostgreSQL
export USE_POSTGRES=false

# SQLite database path
export DB_PATH=/root/clawd-backend/clawdbot_adapter.db
```

---

## How It Works

### No Build Step

**Key Insight:** Python/FastAPI runs directly from source files

```
main branch ────> (Python code in place)
                              │
feature branch ──> (Python code in place)
                              │
                              ▼
                    Uvicorn serves directly from .py files
```

**Benefits:**
- ✅ No build step needed
- ✅ Changes reflect immediately on restart
- ✅ Simple development workflow
- ✅ Less disk usage (no build artifacts)

---

### Backend Selection at Runtime

```
┌─────────────────────────────────────┐
│  start-backend.sh                  │
│                                     │
│  Check .env.postgres                │
│         │                          │
│    exists? ──┐                  │
│         │    │                  │
│    YES    │    NO               │
│         │    │                  │
│    ▼      ▼                  ▼
│ PostgreSQL  │ SQLite            │
│   mode     │   mode           │
│                                     │
│ export      │ export            │
│ USE_POSTGRES=│ export           │
│ true        │ USE_POSTGRES=      │
│             │ false            │
│                                     │
│                                     ▼
│                    Uvicorn app:app --port 8002
│                    (uses selected backend)
│                    (via database_adapter.py)
└─────────────────────────────────────┘
```

---

### Separate PM2 Instances (Port Separation)

| Instance | Port | Branch | Use Case |
|----------|-------|---------|-----------|
| `clawd-backend` | 8002 | `main` | Production (always running) |
| `clawd-backend-dev` | 8001 | `feature/*` | Development (optional, create when needed) |

**Port Isolation:**
- Production and development run simultaneously
- Different ports prevent conflicts
- Same code base, different running instances
- Same PostgreSQL database (master DB is shared)

---

## Deployment Rules

### Rule 1: Main Branch → Port 8002 Only

❌ **Never** run feature branches on port 8002
✅ Only `main` branch runs on port 8002
✅ Used by production frontend
✅ Production PostgreSQL database

### Rule 2: Feature Branches → Port 8001 Only

❌ **Never** run main branch on port 8001
✅ Only feature/fix/dev branches use port 8001
✅ Used for testing API changes
✅ Can use same or separate database

### Rule 3: Branch Naming Convention

| Branch Type | Pattern | Port | Database |
|-------------|----------|-------|-----------|
| **Feature** | `feature/<description>` | 8001 | PostgreSQL |
| **Fix** | `fix/<description>` | 8001 | PostgreSQL |
| **Development** | `development` | 8001 | PostgreSQL |
| **Main** | `main` | 8002 | PostgreSQL |

---

## Workflow Example

### Scenario: Developing a New API Feature

#### 1. Create Feature Branch
```bash
cd /root/clawd-backend
git checkout main
git pull origin main
git checkout -b feature/add-new-endpoint
```

#### 2. Implement Changes
```bash
# Edit Python files
vim app.py
vim chat_handlers.py
```

#### 3. Test on Port 8001 (Optional)
```bash
# Option 1: Create dev PM2 process
pm2 start clawd-backend-dev -- \
  -- /root/clawd-backend/start-backend.sh \
  --name "clawd-backend-dev" \
  --env USE_POSTGRES=true

# Option 2: Run directly with uvicorn
source venv/bin/activate
uvicorn app:app --host 0.0.0.0 --port 8001 --reload

# Feature API now available at http://195.200.14.37:8001/
```

#### 4. Test with Frontend
```bash
# Point frontend dev server to port 8001
# Or use curl/tester
curl http://localhost:8001/health
```

#### 5. Create Pull Request
```bash
gh pr create --base main --head feature/add-new-endpoint
```

#### 6. Merge & Deploy to Production
```bash
# After PR is merged
git checkout main
git pull origin main

# Restart production PM2 process
pm2 restart clawd-backend

# Production API now running at http://195.200.14.37:8002/
```

---

## Quick Reference

### Check Current Deployment

```bash
# Production (Port 8002)
curl http://localhost:8002/health
# Expected: {"status":"ok",...}

# Development (Port 8001) - if running
curl http://localhost:8001/health
# Expected: {"status":"ok",...}
```

### Check Current Branch
```bash
cd /root/clawd-backend
git branch --show-current
# main or feature/*
```

### Switch Between Environments

```bash
# Switch to production (main)
git checkout main
pm2 restart clawd-backend
# API on http://195.200.14.37:8002/

# Switch to development (feature)
git checkout feature/my-feature
# Option 1: Start dev server
pm2 start clawd-backend-dev -- /root/clawd-backend/start-backend.sh
# Option 2: Run uvicorn directly
source venv/bin/activate && uvicorn app:app --port 8001 --reload
# API on http://195.200.14.37:8001/
```

### Restart Production Backend

```bash
pm2 restart clawd-backend
# OR for graceful restart
pm2 reload clawd-backend
```

### Test PostgreSQL Connection

```bash
cd /root/clawd-backend
python3 -c "from database_postgres import test_connection; import json; print(json.dumps(test_connection(), indent=2))"
# Returns: {status: "ok", version: {...}, host: ..., port: ..., database: ...}
```

### Check Database Backend

```bash
# Check which backend is active
cd /root/clawd-backend
python3 -c "from database_adapter import get_database_info; import json; print(json.dumps(get_database_info(), indent=2))"
# Returns: {"backend": "postgresql"|"sqlite", ...}
```

---

## File Permissions

### Production (Port 8002)
```bash
# PM2 runs as root user
# Source code: /root/clawd-backend/
# PostgreSQL: Docker container (runs as root)
# Database: dreampilot (in Docker)
# Virtual environment: /root/clawd-backend/venv/
```

### Development (Port 8001)
```bash
# Same permissions as production
# Uses same PostgreSQL database (master DB)
# If separate database needed, ensure proper ownership
```

---

## Database Considerations

### Shared Database Approach

Both production and development use **same PostgreSQL master database**:
```
PostgreSQL: dreampilot (Docker container: dreampilot-postgres)
```

**Pros:**
- ✅ Tests use real production schema
- ✅ Can test with real data (careful!)
- ✅ Simple setup
- ✅ Connection pooling for performance

**Cons:**
- ⚠️ Development can corrupt production data
- ⚠️ Not isolated testing environment

### Separate Database Approach (Recommended for Testing)

For safer testing, use a separate development database:
```bash
# Create dev database
docker exec dreampilot-postgres psql -U admin -d defaultdb -c "CREATE DATABASE dreampilot_dev;"
```

Then update environment:
```bash
export DB_NAME=dreampilot_dev
```

---

## API Endpoints

### Production (Port 8002)
```bash
Base URL: http://195.200.14.37:8002

Endpoints:
- POST /auth/signup
- POST /auth/login
- GET /projects
- POST /projects
- DELETE /projects/{project_id}?force=true
- GET /projects/{project_id}/sessions
- POST /projects/{project_id}/sessions
- GET /sessions/{id}/messages
- POST /chat
- GET /health
```

### DELETE Endpoint with Force Flag

```bash
# Request without force (blocked if validation fails)
DELETE /projects/124

# Response: 400 Bad Request
{
  "success": false,
  "error": "Database name doesn't match expected pattern",
  "database": "newprojectdemo_db",
  "force_required": true
}

# Request with force (dangerous, bypasses validation)
DELETE /projects/124?force=true

# Response: 200 OK
{
  "status": "deleted",
  "message": "Project deleted",
  "cleanup": {...}
}
```

### Development (Port 8001)
```bash
Base URL: http://195.200.14.37:8001

Same endpoints as production, but running feature branch code
```

---

## Summary

| Aspect | Production (Port 8002) | Development (Port 8001) |
|---------|-------------------------|--------------------------|
| **Git Branch** | `main` | `feature/*`, `fix/*` |
| **Source Location** | `/root/clawd-backend/` | `/root/clawd-backend/` |
| **Deployment Method** | Run in-place (PM2) | Run in-place (PM2 or uvicorn) |
| **Server** | Uvicorn (FastAPI) | Uvicorn (FastAPI) |
| **Port** | 8002 | 8001 |
| **Process Manager** | PM2 | PM2 or direct uvicorn |
| **Database** | PostgreSQL: dreampilot | Same or separate |
| **Database Mode** | USE_POSTGRES=true | USE_POSTGRES=true |
| **Connection Pooling** | 5-20 connections | 5-20 connections |
| **Public URL** | http://195.200.14.37:8002/ | http://195.200.14.37:8001/ |

---

## Troubleshooting

### PostgreSQL Connection Issues

```bash
# Check PostgreSQL container
docker ps | grep postgres

# Check container logs
docker logs dreampilot-postgres --tail 50

# Test connection
cd /root/clawd-backend
python3 -c "from database_postgres import test_connection; test_connection()"

# Create database if missing
docker exec dreampilot-postgres psql -U admin -d defaultdb -c "CREATE DATABASE dreampilot;"

# Check databases
docker exec dreampilot-postgres psql -U admin -d defaultdb -c "\l"
```

### Backend Not Responding

```bash
# Check PM2 status
pm2 status clawd-backend

# Check logs
pm2 logs clawd-backend --lines 50

# Check database backend
cd /root/clawd-backend
python3 -c "from database_adapter import get_database_info; print(get_database_info())"

# Check if port is listening
netstat -tlnp | grep 8002
```

### Database Locked

```bash
# Check PostgreSQL connections
docker exec dreampilot-postgres psql -U admin -d dreampilot -c "SELECT * FROM pg_stat_activity WHERE datname='dreampilot';"

# Restart backend to release connections
pm2 restart clawd-backend
```

### Migration Issues

```bash
# Run migration with dry-run
python3 migrate_to_postgres.py --dry-run

# Validate existing data
python3 migrate_to_postgres.py --validate-only

# Check record counts before/after
# SQLite: sqlite3 /root/clawd-backend/clawdbot_adapter.db "SELECT COUNT(*) FROM users;"
# PostgreSQL: docker exec dreampilot-postgres psql -U admin -d dreampilot -c "SELECT COUNT(*) FROM users;"
```

---

## Migration Checklist

### Pre-Migration Checklist
- [ ] PostgreSQL Docker container running
- [ ] Database `dreampilot` created
- [ ] Connection tested successfully
- [ ] Environment variables configured
- [ ] .env.postgres file created with correct values
- [ ] Backup of SQLite database (optional)

### Migration Execution Checklist
- [ ] Dry-run completed successfully
- [ ] Validation passed (all counts match)
- [ ] Users table migrated
- [ ] Project types table migrated
- [ ] Projects table migrated
- [ ] Sessions table migrated
- [ ] Messages table migrated
- [ ] All sequences reset
- [ ] Foreign key constraints validated

### Post-Migration Checklist
- [ ] All record counts match
- [ ] Application starts with PostgreSQL
- [ ] Test API endpoints working
- [ ] Project creation/deletion tested
- [ ] Master DB protection verified
- [ ] Project DB validation working
- [ ] Force flag tested

### Production Switch Checklist
- [ ] All tests passed
- [ ] .env.postgres configured with production values
- [ ] start-backend.sh updated to PostgreSQL mode
- [ ] Application restarted
- [ ] Health check returns `{"status":"ok"}`
- [ ] API endpoints responding correctly
- [ ] Documentation updated
- [ ] Backups created (optional)

---

## Important Notes

### Master Database Protection

🔒 **CRITICAL:** The master database (`dreampilot`) is protected and can NEVER be deleted. This is a hard rule.

- Any attempt to delete the master database will be blocked
- Project-specific databases (`{project_name}_db`) are safe to delete
- Force flag provides emergency bypass but logs all attempts
- All deletions are logged for security audit

### Database Deletion Safety

⚠️ **Warning:** Force deletion bypasses validation and is DANGEROUS.

- Only use `force=true` when absolutely necessary
- Force deletions are logged with security warnings
- Always verify database name before using force
- Test force flag on non-critical data first

### Connection Pooling

✅ **Performance:** Connection pooling (5-20 connections) significantly improves performance
- Connections are automatically returned to pool after use
- Prevents connection leaks
- Thread-safe for concurrent requests

---

**Last Updated:** 2026-02-21 (PostgreSQL Migration Edition)
