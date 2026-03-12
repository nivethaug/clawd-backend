---
name: project-info
description: DreamPilot Backend project knowledge - architecture, pipeline flow, key files, and coding conventions. Use when working with project creation, infrastructure provisioning, or understanding codebase structure.
---

# DreamPilot Backend - Project Knowledge

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    DreamPilot Backend                        │
│                                                              │
│  FastAPI (Python 3.11+) ←→ PostgreSQL ←→ Redis (optional)  │
│         ↓                                                    │
│  PM2 Process Manager                                         │
│         ↓                                                    │
│  Nginx Reverse Proxy                                         │
│         ↓                                                    │
│  *.dreambigwithai.com (Wildcard DNS)                        │
└─────────────────────────────────────────────────────────────┘
```

## Project Creation Pipeline

### Flow Diagram

```
POST /projects (app.py:288)
    │
    ├─→ Insert DB record (status='creating')
    ├─→ Create project folder with Git
    ├─→ Select template via Groq API
    └─→ run_claude_code_background() [spawns thread]
            │
            ├─→ fast_wrapper.py (5 tasks, ~30s)
            │       ├─ Task 1: Template selection (skipped)
            │       ├─ Task 2: Git clone / copy template
            │       ├─ Task 3: Create FastAPI backend files
            │       ├─ Task 4: Create database schema files
            │       └─ Task 5: Create .env config
            │
            └─→ openclaw_wrapper.py (9 phases, ~5-15min)
                    ├─ Phase 1: Analyze Project
                    ├─ Phase 2: Verify Template Setup
                    ├─ Phase 3: ACPX Frontend Refinement (AI)
                    ├─ Phase 4: Database Provisioning
                    ├─ Phase 5: Port Allocation
                    ├─ Phase 6: Service Setup (PM2 + build)
                    ├─ Phase 7: Nginx Routing
                    ├─ Phase 8: (Skipped - legacy)
                    └─ Phase 9: Deployment Verification
```

## Key Files Reference

| File | Purpose | Key Functions |
|------|---------|---------------|
| `app.py` | FastAPI entry point | `create_project()`, `get_projects()`, API routes |
| `claude_code_worker.py` | Background thread | `run_claude_code_background()`, `_worker()` |
| `fast_wrapper.py` | Quick scaffolding | `FastWrapper.run()`, `git_clone()`, `create_backend()` |
| `openclaw_wrapper.py` | Infrastructure pipeline | `run_all_phases()`, `phase_*()` methods |
| `infrastructure_manager.py` | PM2, nginx, DB | `provision_all()`, `DatabaseProvisioner`, `ServiceManager` |
| `database_adapter.py` | DB abstraction | `get_db()`, `init_schema()` |
| `database_postgres.py` | PostgreSQL connection | `get_connection_pool()`, `CursorAsConnection` |
| `acp_frontend_editor_v2.py` | AI frontend editing | `apply_changes_via_acpx()` |
| `deployment_verifier.py` | Verify deployment | `verify_deployment()` |

## Coding Conventions

### Path Resolution
```python
# Always use dynamic path resolution
BACKEND_DIR = Path(__file__).parent.resolve()
```

### Subprocess Execution
```python
# Use this pattern for background workers
result = subprocess.run(
    cmd_args,  # List, not string
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    stdin=subprocess.DEVNULL,  # Prevents blocking
    text=True,
    timeout=900,
    close_fds=True,
    env=os.environ.copy()
)
```

### Database Connections
```python
# Use context manager
with get_db() as conn:
    result = conn.execute("SELECT * FROM projects")
    conn.commit()
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `USE_POSTGRES` | true | Use PostgreSQL vs SQLite |
| `DB_HOST` | localhost | PostgreSQL host |
| `DB_PORT` | 5432 | PostgreSQL port |
| `DB_NAME` | dreampilot | Database name |
| `EMPTY_TEMPLATE_MODE` | false | Use blank template |
| `HOSTINGER_API_TOKEN` | - | DNS management (optional) |

## Common Commands

```bash
# Start server
pm2 start ecosystem.config.json

# View logs
pm2 logs clawd-backend --lines 100

# Restart after changes
pm2 restart clawd-backend

# Check status
pm2 status

# Run tests
python test_full_pipeline.py

# Database connection
docker exec -it dreampilot-postgres psql -U admin -d dreampilot
```

## Status Progression

| Status | When | Where |
|--------|------|-------|
| `creating` | Project created | `app.py:345` |
| `ai_provisioning` | Phase 3 starts | `openclaw_wrapper.py:740` |
| `ready` | All phases complete | `openclaw_wrapper.py:1607` |
| `failed` | Any phase fails | Multiple locations |

## Quick Debugging

### Check if wrapper is running
```bash
ps aux | grep openclaw_wrapper
```

### View worker logs
```bash
pm2 logs clawd-backend | grep -E "(WORKER|Phase|Error)"
```

### Test database connection
```bash
docker exec dreampilot-postgres pg_isready -U admin
```

### Check project status
```sql
SELECT id, name, status FROM projects ORDER BY id DESC LIMIT 5;
```

## File Naming Conventions

| Pattern | Meaning |
|---------|---------|
| `*_wrapper.py` | Pipeline stages |
| `*_manager.py` | Infrastructure components |
| `*_worker.py` | Background threads |
| `*_service.py` | External service clients |
| `*_adapter.py` | Database/interface adapters |

## Don't Modify Without Reason

- `database_postgres.py` - Connection pooling logic
- `pipeline_status.py` - Status tracking enums
- `ecosystem.config.json` - PM2 configuration (unless port changes)
- `.env` - Production credentials