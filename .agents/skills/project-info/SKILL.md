# DreamPilot Backend - Project Knowledge

> **Note:** This documentation reflects the actual codebase implementation.
> Last verified: 2026-03-14 (updated with infrastructure stabilization fixes)

---

## Architecture Overview

### System Architecture (Two-Subdomain Model)

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENT REQUEST                           │
│         {project}.dreambigwithai.com (Frontend)                 │
│         {project}-api.dreambigwithai.com (Backend)              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      NGINX (Port 80/443)                        │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ FRONTEND SERVER BLOCK                                      │  │
│  │ server_name {project}.dreambigwithai.com;                  │  │
│  │                                                            │  │
│  │ root /root/dreampilot/projects/website/{domain}/dist;     │  │
│  │                                                            │  │
│  │ location /     → try_files $uri /index.html (SPA)         │  │
│  │ location /api/  → proxy_pass http://127.0.0.1:8xxx/       │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ BACKEND SERVER BLOCK                                       │  │
│  │ server_name {project}-api.dreambigwithai.com;              │  │
│  │                                                            │  │
│  │ location /     → proxy_pass http://127.0.0.1:8xxx         │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────┐  ┌──────────────────────────────┐
│   FRONTEND SERVICE (PM2)     │  │    BACKEND SERVICE (PM2)     │
│                              │  │                              │
│   npx serve -s dist          │  │   uvicorn main:app           │
│   -l <frontend_port>         │  │   --host 0.0.0.0             │
│   (Port 3000-4000)           │  │   --port <backend_port>      │
│                              │  │   (Port 8010-9000)           │
└──────────────────────────────┘  └──────────────────────────────┘
                                              │
                                              ▼
                               ┌──────────────────────────────┐
                               │      POSTGRESQL DATABASE     │
                               │   Database: {project}_db     │
                               │   (Docker Container)         │
                               └──────────────────────────────┘
```

### URL Structure

| Service | URL | Purpose |
|---------|-----|---------|
| Frontend | `http(s)://{project}.dreambigwithai.com/` | React SPA |
| Frontend API Proxy | `http(s)://{project}.dreambigwithai.com/api/` | Proxied to backend |
| Backend Direct | `http(s)://{project}-api.dreambigwithai.com/` | Direct API access |
| Health Check | `http(s)://{project}-api.dreambigwithai.com/health` | Backend health |

### Backend Stack

- **FastAPI** (Python 3.11+)
- **PostgreSQL** (via Docker container)
- **Redis** (optional)
- **PM2** (process management)
- **Nginx** (reverse proxy)
- **Hostinger DNS API** (wildcard *.dreambigwithai.com)

---

## Project Creation Pipeline

### High-Level Flow

```
POST /projects (app.py)
      │
      ├─ Validate domain/subdomain format
      │
      ├─ Insert DB record (status='creating')
      │   └─ RETURNING id → project_id
      │
      ├─ Create project folder with Git init
      │   └─ ProjectFileManager.create_project_with_git()
      │
      ├─ Update DB with project_path
      │
      ├─ Select template via Groq API
      │   └─ TemplateSelector.select_template()
      │
      └─ Trigger background worker
          └─ run_claude_code_background()
                 │
                 ├─ fast_wrapper.py (~5-30s)
                 │   ├─ Task 1: Select template (skipped if provided)
                 │   ├─ Task 2: Git clone or copy blank template
                 │   ├─ Task 3: Create backend skeleton (main.py)
                 │   ├─ Task 4: Create database setup (init.sql)
                 │   └─ Task 5: Create .env config
                 │
                 └─ openclaw_wrapper.py (~1-10 min)
                     └─ OpenClawWrapper.run_all_phases()
```

---

## Pipeline Phases (Actual Execution Order)

The pipeline executes in `openclaw_wrapper.py` via `run_all_phases()`:

| Phase | Log Label | Function Called | Description |
|-------|-----------|-----------------|-------------|
| 1 | `PHASE_1_PLANNER` | `phase_1_analyze_project()` | Analyze project requirements |
| 2 | `PHASE_2_TEMPLATE` | `phase_2_template_setup()` | Verify frontend/backend directories exist |
| 3 | `PHASE_3_ACPX` | `phase_9_acp_frontend_editor()` | **ACPX Frontend customization** |
| 4 | `PHASE_4_DATABASE` | `phase_3_database_provisioning()` | Database provisioning (delegated) |
| 5 | `PHASE_5_PORT` | `phase_4_port_allocation()` | Port allocation (delegated) |
| 6 | `PHASE_6_SERVICE` | `phase_5_service_setup()` | PM2 + build + infrastructure |
| 7 | `PHASE_7_NGINX` | `phase_6_nginx_routing()` | Nginx configuration |
| 8 | `PHASE_8_AI` | *(skipped)* | Legacy AI refinement - bypassed |
| 9 | `PHASE_9_VERIFY` | `phase_7_verification()` | Deployment verification |

> **Important:** Function names in code do NOT match phase numbers due to historical refactoring.
> Example: Phase 3 calls `phase_9_acp_frontend_editor()` instead of `phase_3_*`.

### Phase Details

**Phase 1 — Analyze Project**
- Template already selected via Groq API
- Logs project name, description, template ID

**Phase 2 — Template Setup**
- Verifies `frontend/` directory exists
- Verifies `backend/` directory exists

**Phase 3 — ACPX Frontend Refinement**
- Runs `ACPFrontendEditorV2` for AI-powered frontend customization
- Updates router and navigation
- Runs Frontend Optimizer (rule-based branding)
- Creates `ACP_README.md` documentation

**Phase 3.1 — Automatic Post-Processing Steps**
After ACPX completes, `ACPFrontendEditorV2.apply_changes_via_acpx()` automatically fixes common issues:

| Step | File | Lines | Issue Fixed |
|------|------|-------|-------------|
| 10.5 | `acp_frontend_editor_v2.py` | 992-1065 | Duplicate "/" routes, missing Layout wrapper |
| 10.6 | `acp_frontend_editor_v2.py` | 1072-1118 | Layout using `{children}` instead of `<Outlet />` |
| 13 | `acp_frontend_editor_v2.py` | 1177-1240 | Empty/placeholder pages after timeout |

**Step 10.5 — Routing Fix (lines 992-1065)**

| Issue | Symptom | Fix Applied |
|-------|---------|-------------|
| Duplicate "/" routes | Blank page (Welcome wins) | Remove ALL routes at "/" |
| No Layout wrapper | No navigation sidebar | Wrap routes in `<Route element={<Layout />}>` |
| Dashboard at wrong path | Dashboard unreachable | Move Dashboard to "/" route |

**Routing Fix Logic:**
1. Remove all duplicate "/" routes using regex: `<Route\s+path="/"\s+element=\{<[^>]+>\s*/>\}\s*/>`
2. Remove `/dashboard` route (consolidated to "/")
3. Detect if Layout wrapper exists:
   - ✅ **Has Layout**: Insert default page at "/" inside Layout wrapper
   - ✅ **No Layout**: Wrap ALL routes with Layout, add default page at "/"

**Before Fix (broken):**
```tsx
<Routes>
  <Route path="/" element={<Welcome />} />     // First match wins = blank
  <Route path="/" element={<Dashboard />} />   // Never reached
  <Route path="/team" element={<Team />} />
</Routes>
```

**After Fix (working):**
```tsx
<Routes>
  <Route element={<Layout />}>                 // Layout wrapper added
    <Route path="/" element={<Dashboard />} /> // Dashboard at root
    <Route path="/team" element={<Team />} />
  </Route>
</Routes>
```

**Step 10.6 — Layout Outlet Fix (lines 1072-1118)**

| Issue | Symptom | Fix Applied |
|-------|---------|-------------|
| `{children}` in Layout | Nested routes don't render | Replace with `<Outlet />` |
| Missing Outlet import | Runtime error | Add `import { Outlet } from 'react-router-dom'` |

**Step 13 — Empty Page Detection (lines 1177-1240)**

Detects and re-populates pages that are empty after ACPX timeout:
- Checks for files < 500 bytes
- Detects placeholder text ("Page content will be generated by AI")
- Re-runs ACPX to populate empty pages

**Phase 4 — Database Provisioning**
- Delegated to `InfrastructureManager`
- Creates PostgreSQL database: `{project}_db`
- Creates database user: `{project}_user`
- Grants privileges

**Phase 5 — Port Allocation**
- Frontend port: 3000-4000 range
- Backend port: 8010-9000 range
- Scans for available ports

**Phase 6 — Service Setup**
- Runs `npm install` and `npm run build`
- Starts PM2 services (frontend + backend)
- Configures environment variables

**Phase 7 — Nginx Routing**
- Generates nginx config in `/etc/nginx/sites-available/`
- Creates symlink to `/etc/nginx/sites-enabled/`
- Reloads nginx

**Phase 8 — Legacy AI Phase**
- Currently **SKIPPED**
- ACPX in Phase 3 handles frontend refinement

**Phase 9 — Deployment Verification**
- Verifies build output (`dist/index.html`)
- Checks nginx configuration
- Verifies DNS resolution
- Tests HTTP response (200 OK)
- Checks PM2 service status

---

## PipelinePhase Enum (Status Tracking)

The `pipeline_status.py` module tracks **high-level milestones** (not all internal phases):

```python
class PipelinePhase(str, Enum):
    PLANNER = "planner"    # Phase 1
    SCAFFOLD = "scaffold"  # Phase 2
    ACPX = "acpx"          # Phase 3
    ROUTER = "router"      # (tracked inside Phase 3)
    BUILD = "build"        # Phase 6
    DEPLOY = "deploy"      # Phase 9
```

> **Note:** Internal phases (Database, Port, Nginx) are not separately tracked in the enum.

---

## Runtime Service Architecture

### Frontend Service

```bash
npx serve -s dist -l <frontend_port>
```

- Serves static React/Vite build from `dist/` directory
- Port range: 3000-4000
- Managed by PM2 as `{project-name}-frontend`

### Backend Service

```bash
uvicorn main:app --host 0.0.0.0 --port <backend_port>
```

- FastAPI application from `backend/main.py`
- Port range: 8010-9000
- Managed by PM2 as `{project-name}-backend`
- Health endpoint: `GET /health` → `{"status": "ok"}`

### Nginx Routing (Two-Subdomain Architecture)

```nginx
# Frontend: project.dreambigwithai.com
server {
    listen 80;
    server_name project.dreambigwithai.com;

    root /root/dreampilot/projects/website/project/frontend/dist;
    index index.html;

    # SPA routing - serve index.html for all routes
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API proxy (trailing slash strips /api prefix)
    location /api/ {
        proxy_pass http://127.0.0.1:8xxx/;
    }
}

# Backend: project-api.dreambigwithai.com
server {
    listen 80;
    server_name project-api.dreambigwithai.com;

    location / {
        proxy_pass http://127.0.0.1:8xxx;
    }
}
```

Result:
- `{project}.dreambigwithai.com/` → Frontend (React SPA)
- `{project}.dreambigwithai.com/api/` → Backend (via proxy, `/api` stripped)
- `{project}-api.dreambigwithai.com/` → Backend (direct access)
- `{project}-api.dreambigwithai.com/health` → Health check endpoint

---

## Infrastructure Manager

The `infrastructure_manager.py` handles all infrastructure provisioning:

### Port Allocation (`PortAllocator`)
- Loads used ports from `projects.db`
- Scans ports 3000-4000 (frontend) and 8010-9000 (backend)
- Socket check to verify availability

### Frontend Build (`ServiceManager.build_frontend()`)
1. Clean Vite caches (`node_modules/.vite`)
2. Run `npm install`
3. Run `npm run build`
4. Verify `dist/index.html` exists
5. **Cleanup node_modules** (lines 1850-1860) — Removes `node_modules/` after build to save disk space

### PM2 Service Management
- Creates `ecosystem.config.json` for each service
- Starts services via `pm2 start`
- Verifies services are running

### Nginx Configuration
- Generates config from template
- Writes to `/etc/nginx/sites-available/{domain}`
- Creates symlink to `/etc/nginx/sites-enabled/`
- Reloads nginx

### DNS Provisioning (`dns_manager.py`)
- Checks if domain already resolves
- Creates A-record via Hostinger API if missing
- Waits for propagation (12 attempts × 10s = 120s)

---

## Deployment Verification

The `deployment_verifier.py` performs comprehensive checks:

| Check | Description | Retry |
|-------|-------------|-------|
| Build Output | `dist/` and `dist/index.html` exist | No |
| Nginx Config | `/etc/nginx/sites-enabled/{domain}` exists | No |
| DNS Resolution | `socket.gethostbyname(domain)` succeeds | Yes (3×) |
| HTTP Response | `GET http://{domain}` returns 200 | Yes (3×) |
| PM2 Status | Both services running | No |

Retry configuration:
- Max retries: 3
- Base delay: 5.0s (exponential backoff)
- HTTP timeout: 30.0s

---

## Status Progression

| Status | Meaning |
|--------|---------|
| `creating` | Project record created |
| `initializing` | Phase 1 (Planner) running |
| `ai_provisioning` | ACPX phase started |
| `building` | Build phase |
| `deploying` | Service + nginx phase |
| `verifying` | Deployment verification |
| `ready` | Deployment successful |
| `failed` | Pipeline failure |

---

## DNS Automation

```
DNS Check (inside infrastructure_manager)
      │
      ├ Check domain resolution
      │
      ├ If missing:
      │   ├ Create A-record via Hostinger API
      │   └ Wait for propagation
      │
      └ Continue deployment verification
```

Propagation strategy:
- Attempts: 12
- Delay: 10 seconds
- Total wait: 120 seconds

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `app.py` | FastAPI API server, entry point |
| `claude_code_worker.py` | Background project worker thread |
| `fast_wrapper.py` | Initial project scaffolding (5 tasks) |
| `openclaw_wrapper.py` | Infrastructure pipeline (9 phases) |
| `infrastructure_manager.py` | PM2, nginx, database, DNS, build, node_modules cleanup |
| `dns_manager.py` | Hostinger DNS API client |
| `acp_frontend_editor_v2.py` | AI frontend modification (ACPX) + routing/Layout fixes + empty page detection |
| `page_manifest.py` | Page manifest management for ACPX |
| `page_specs.py` | Page specifications for UI quality |
| `groq_service.py` | Groq API client (with log-once error handling, lines 17-40) |
| `template_selector.py` | Template selection (with log-once error handling, lines 18-70) |
| `database_adapter.py` | DB abstraction layer |
| `database_postgres.py` | PostgreSQL connection |
| `deployment_verifier.py` | Deployment verification |
| `pipeline_status.py` | Pipeline phase tracking |
| `dreamctl` | CLI management tool |

---

## Recent Infrastructure Fixes (2026-03-14)

### ACPX-V2 Stabilization

| Fix | File | Lines | Description |
|-----|------|-------|-------------|
| Conjunction Stripping | `acp_frontend_editor_v2.py` | 1532-1541 | Strips `and`, `or`, `&` from page names to prevent "AndAudience" bug |
| Path Validation | `acp_frontend_editor_v2.py` | 48-54 | Changed to allow-all except forbidden paths (fixes `hooks/` blocking) |
| Idle Timeout | `acp_frontend_editor_v2.py` | 698 | Increased from 180s to 300s (5 minutes) |
| Layout Outlet Fix | `acp_frontend_editor_v2.py` | 1072-1118 | Auto-replace `{children}` with `<Outlet />` in Layout components |
| Empty Page Detection | `acp_frontend_editor_v2.py` | 1177-1240 | Detects and re-populates empty pages after ACPX timeout |
| node_modules Cleanup | `infrastructure_manager.py` | 1850-1860 | Removes `node_modules/` after build to save disk space |

### Log Spam Reduction

| File | Lines | Fix |
|------|-------|-----|
| `groq_service.py` | 17, 30-40 | Global `_GROQ_API_KEY_LOGGED` flag logs error only once |
| `template_selector.py` | 18, 51-70 | Global `_TEMPLATE_SELECTOR_ERROR_LOGGED` flag logs error only once |

---

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `USE_POSTGRES` | Enable PostgreSQL (default: true) |
| `DB_HOST` | PostgreSQL host |
| `DB_PORT` | PostgreSQL port |
| `DB_NAME` | Database name |
| `DB_USER` | Database user |
| `DB_PASSWORD` | Database password |
| `EMPTY_TEMPLATE_MODE` | Use blank template |
| `HOSTINGER_API_TOKEN` | DNS automation |
| `RULES_DIR` | Path to rule files for OpenClaw |

---

## Subprocess Execution Pattern

Always use this safe pattern:

```python
result = subprocess.run(
    cmd_args,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    stdin=subprocess.DEVNULL,
    text=True,
    timeout=900,
    close_fds=True,
    env=os.environ.copy()
)
```

---

## Database Usage

Use context manager:

```python
with get_db() as conn:
    conn.execute(query)
    conn.commit()
```

---

## Common Commands

### Start backend
```bash
pm2 start ecosystem.config.json
```

### View logs
```bash
pm2 logs clawd-backend --lines 100
```

### Restart server
```bash
pm2 restart clawd-backend
```

### PM2 status
```bash
pm2 status
```

### Check worker processes
```bash
ps aux | grep openclaw_wrapper
```

---

## CLI Management (dreamctl)

```bash
python dreamctl repair-dns <project_id>
python dreamctl repair-all-dns
python dreamctl list
python dreamctl status <project_id>
python dreamctl verify <project_id>
```

---

## Debugging Deployment Issues

### Check PM2 Services
```bash
pm2 list
pm2 logs clawd-backend --lines 100
pm2 logs project-<id>-backend
pm2 logs project-<id>-frontend
```

### Check Database
```sql
SELECT id, name, status FROM projects ORDER BY id DESC LIMIT 5;
```

### Test Backend Directly
```bash
# Via backend subdomain
curl http://project-api.dreambigwithai.com/health
# Expected: {"status":"ok"}

# Via frontend API proxy
curl http://project.dreambigwithai.com/api/health
# Expected: {"status":"ok"}

# Direct port access
curl http://127.0.0.1:<backend_port>/health
# Expected: {"status":"ok"}
```

### Check Nginx Configuration
```bash
sudo cat /etc/nginx/sites-enabled/<domain>.conf
sudo nginx -t  # Test configuration
```

### Check DNS Resolution
```bash
# Frontend domain
nslookup <domain>.dreambigwithai.com
dig <domain>.dreambigwithai.com

# Backend domain
nslookup <domain>-api.dreambigwithai.com
dig <domain>-api.dreambigwithai.com
```

### Common Issue: Frontend Loads but Backend Unreachable

**Symptoms:**
- Frontend page loads at `http://project.dreambigwithai.com/`
- API calls to `/api/` fail with 502 or timeout
- Backend subdomain `http://project-api.dreambigwithai.com/` unreachable

**Debugging Steps:**
1. Check both nginx server blocks exist (frontend + backend)
2. Verify backend PM2 process is running: `pm2 list`
3. Check backend logs: `pm2 logs project-<id>-backend`
4. Test backend directly: `curl http://127.0.0.1:<backend_port>/health`
5. Check DNS for both domains: `dig project-api.dreambigwithai.com`

### Common Issue: HTTP 500 on Frontend

**Symptoms:**
- Frontend returns HTTP 500
- Nginx error logs show "permission denied" or "file not found"

**Debugging Steps:**
1. Check `dist/` directory exists: `ls -la /root/dreampilot/projects/website/{domain}/frontend/dist/`
2. Verify `index.html` exists: `cat /root/dreampilot/projects/website/{domain}/frontend/dist/index.html`
3. Check nginx error logs: `tail -50 /var/log/nginx/error.log`
4. Verify nginx config has correct `root` path

---

## File Naming Conventions

| Pattern | Meaning |
|---------|---------|
| `*_wrapper.py` | Pipeline execution |
| `*_manager.py` | Infrastructure components |
| `*_worker.py` | Background workers |
| `*_service.py` | External services |
| `*_adapter.py` | DB interfaces |

---

## Do Not Modify Without Care

These files control core infrastructure:

- `database_postgres.py`
- `pipeline_status.py`
- `ecosystem.config.json`
- `.env`
- `infrastructure_manager.py`

---

## Known Code Issues

> These issues exist in the codebase but do not affect functionality.
> Documented for future refactoring.

### 1. Phase Function Naming Mismatch

**File:** `openclaw_wrapper.py`

Phase numbers don't match function names:
- Phase 3 calls `phase_9_acp_frontend_editor()`
- Phase 4 calls `phase_3_database_provisioning()`
- Phase 5 calls `phase_4_port_allocation()`
- Phase 6 calls `phase_5_service_setup()`
- Phase 7 calls `phase_6_nginx_routing()`
- Phase 9 calls `phase_7_verification()`

**Impact:** Code maintenance confusion, debugging difficulty

### 2. Phase Counter Display Error

**File:** `openclaw_wrapper.py`

Phase logging inside individual phase functions shows incorrect totals:
```python
logger.info("📋 Phase 1/8: Analyze Project")      # Should be Phase 1/9
logger.info("📋 Phase 2/8: Template Setup")       # Should be Phase 2/9
logger.info("📋 Phase 3/8: Database Provisioning") # Should be Phase 4/9
logger.info("📋 Phase 9/8: ACP Controlled Frontend Editor")  # Should be Phase 3/9
```

However, `run_all_phases()` uses correct total: `total_phases = 9`

**Impact:** Misleading logs in individual phase functions (main execution shows correct phases)

### 3. Duplicate Exception Handlers

**File:** `claude_code_worker.py` (lines 107-145)

Two identical `except` blocks - second set is dead code.

**Impact:** Code bloat, confusion

### 4. PipelinePhase Enum Incomplete

**File:** `pipeline_status.py`

Enum has 6 phases but wrapper has 9 phases. Missing:
- `DATABASE`
- `PORT`
- `NGINX`

**Impact:** Status tracking incomplete

### 5. Phase 8 Skipped

**File:** `openclaw_wrapper.py`

`phase_8_frontend_ai_refinement()` function exists (line 571) but is never called in `run_all_phases()`.
Phase 8 is explicitly skipped with comment: "Phase 8 skipped - ACPX in Phase 3 handles frontend refinement"

**Impact:** Dead code, maintenance confusion

---

## Summary

DreamPilot performs:

```
Prompt
   ↓
Project Creation (POST /projects)
   ↓
Template Scaffolding (fast_wrapper.py)
   ↓
ACPX AI Frontend Generation (Phase 3: openclaw_wrapper.py → phase_9_acp_frontend_editor)
   ↓
Post-Processing Fixes (acp_frontend_editor_v2.py):
   • Step 10.5: Routing Fix (lines 992-1065)
   • Step 10.6: Layout Outlet Fix (lines 1072-1118)
   • Step 13: Empty Page Detection (lines 1177-1240)
   ↓
Infrastructure Provisioning (Phase 4-7: infrastructure_manager.py)
   ↓
Deployment Verification (Phase 9: deployment_verifier.py)
   ↓
Live SaaS Application
```

All phases automated. Full stack deployment in ~5-15 minutes.

