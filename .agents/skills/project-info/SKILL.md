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
| `infrastructure_manager.py` | PM2, nginx, DB, DNS | `provision_all()`, `repair_dns()`, `_phase_8_dns()`, `DatabaseProvisioner`, `ServiceManager` |
| `dns_manager.py` | Hostinger DNS API | `HostingerDNSAPI`, `create_a_record()`, `check_subdomain_exists()` |
| `dreamctl` | CLI management tool | `repair-dns`, `repair-all-dns`, `verify`, `list`, `status` |
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

# DNS repair (CLI tool)
python dreamctl repair-dns <project_id>    # Repair single project
python dreamctl repair-all-dns              # Repair all projects
python dreamctl list                        # List all projects
python dreamctl status <project_id>         # Show project status
python dreamctl verify <project_id>         # Verify deployment
```

## Status Progression

| Status | When | Where |
|--------|------|-------|
| `creating` | Project created | `app.py:345` |
| `ai_provisioning` | Phase 3 starts | `openclaw_wrapper.py:740` |
| `ready` | All phases complete | `openclaw_wrapper.py:1607` |
| `failed` | Any phase fails | Multiple locations |

## DNS Automation

### Auto-Repair Flow
```
PHASE_9 Verification
    │
    ├─→ Check DNS resolution for frontend domain
    │       │
    │       ├─→ If NOT resolving:
    │       │       ├─→ Log: [DNS] Missing DNS record detected
    │       │       ├─→ Log: [DNS] Attempting automatic repair
    │       │       ├─→ Call _phase_8_dns() → Hostinger API
    │       │       ├─→ Log: [DNS] A-record created
    │       │       └─→ Retry loop (12 attempts, 10s each)
    │       │               ├─→ Log: [DNS] Waiting for propagation...
    │       │               └─→ Log: [DNS] Domain resolving correctly
    │       │
    │       └─→ If resolving:
    │               └─→ Log: [DNS] Domain resolving correctly
    │
    └─→ Continue to HTTP verification
```

### DNS Propagation Retry
- **Max attempts:** 12
- **Delay between attempts:** 10 seconds
- **Total max wait:** 120 seconds

### Rate Limiting
- `dreamctl repair-all-dns` includes 1-second delay between API calls
- Prevents Hostinger API rate limit errors (HTTP 423)

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