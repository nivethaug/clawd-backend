# Project Creation - Complete Reference

> [TOC](toc.md) | [SKILL.md](../.agents/skills/project-info/SKILL.md) | Updated: 2026-03-15

---

## API Endpoints

| Endpoint | Method | File | Lines | Description |
|----------|--------|------|-------|-------------|
| `/projects` | POST | `app.py` | 283-510 | Create new project |
| `/projects` | GET | `app.py` | 241-280 | List all projects |
| `/projects/{id}` | GET | `app.py` | 355-380 | Get project details |
| `/project-types` | GET | `app.py` | 515-528 | List project types |
| `/templates` | GET | `app.py` | 574-600 | List templates |
| `/templates/select` | POST | `app.py` | 530-572 | Select template |
| `/projects/{id}/files` | GET | `app.py` | 2154-2185 | List project files |
| `/projects/{id}/files/{path}` | GET | `app.py` | 2187-2225 | Get file content |
| `/projects/{id}/files/{path}` | PUT | `app.py` | 2227-2265 | Save file content |

---

## POST /projects - Create Project

**File:** `app.py:283-510`

**Request:**
```json
{
  "name": "my-project",
  "domain": "myproject",
  "description": "Project description",
  "user_id": 1,
  "type_id": 1,
  "template_id": "blank-template"
}
```

**Response:**
```json
{
  "id": 1,
  "user_id": 1,
  "name": "my-project",
  "domain": "myproject",
  "project_path": "/root/clawd-projects/my-project",
  "status": "creating",
  "template_id": "blank-template"
}
```

---

## Project Creation Pipeline

### Entry Point Flow

| Step | File | Lines | Description |
|------|------|-------|-------------|
| 1. API Request | `app.py` | 50-70 | Validate project name, template, user_id |
| 2. DB Insert | `app.py` | 80-95 | Insert project record with `status='creating'` |
| 3. Template Selection | `app.py` | 96-105 | Call `TemplateSelector.select_template()` |
| 4. Worker Trigger | `claude_code_worker.py` | 50-80 | Start background worker |
| 5. Fast Scaffolding | `fast_wrapper.py` | 50-240 | Create project structure |

---

## Pipeline Phases

| Phase | Function | File | Lines | Description |
|-------|----------|------|-------|-------------|
| 1 | `phase_1_analyze_project()` | `openclaw_wrapper.py` | 322-393 | Confirm project details, template |
| 2 | `phase_2_template_setup()` | `openclaw_wrapper.py` | 395-439 | Verify frontend/backend directories |
| 3 | `phase_3_database_provisioning()` | `openclaw_wrapper.py` | 441-464 | Prepare database provisioning |
| 4 | `phase_4_port_allocation()` | `openclaw_wrapper.py` | 466-488 | Prepare port allocation |
| 5 | `phase_5_service_setup()` | `openclaw_wrapper.py` | 490-526 | Call InfrastructureManager.provision_all() |
| 6 | `phase_6_nginx_routing()` | `openclaw_wrapper.py` | 528-542 | Nginx config (via InfrastructureManager) |
| 7 | `phase_7_verification()` | `openclaw_wrapper.py` | 544-558 | Deployment verification |
| 8 | `phase_8_frontend_ai_refinement()` | `openclaw_wrapper.py` | 560-692 | CrewAI frontend refinement |
| 9 | `phase_9_acp_frontend_editor()` | `openclaw_wrapper.py` | 694-850 | ACPX frontend customization |

### Phase Details

| Phase | Purpose | Key Methods | Error Handling |
|-------|---------|-------------|----------------|
| 1 | Confirm template selection | `status_tracker.start_phase()`, `complete_phase()` | Returns True (always succeeds) |
| 2 | Verify directories | Check `frontend/` and `backend/` exist | Returns False if missing, calls `fail_phase()` |
| 3 | Prepare DB provisioning | Logs delegation to InfrastructureManager | Returns True (preparation only) |
| 4 | Prepare port allocation | Logs delegation to InfrastructureManager | Returns True (preparation only) |
| 5 | Run infrastructure | `get_project_domain()`, `infra.provision_all()` | Returns False if infra fails |
| 6 | Nginx routing | Logs completion (handled in Phase 5) | Returns True (already verified) |
| 7 | Verification | Logs completion (handled in Phase 5) | Returns True (already verified) |
| 8 | AI refinement | `_get_project_type_id()`, `_verify_frontend_build()`, `_restart_pm2_service()` | Returns True even on failure (allows completion) |
| 9 | ACPX customization | `FrontendOptimizer`, `ACPFrontendEditorV2`, `_update_router_and_navigation()` | Returns True even on failure (allows completion) |

**Phase 8-9 Resilience:** These phases return True even on failure to allow project completion despite AI errors

---

## Infrastructure Manager (`infrastructure_manager.py`)

### Core Classes

| Class | Lines | Purpose | Key Methods |
|-------|-------|---------|-------------|
| `PortAllocator` | 73-152 | Allocate frontend/backend ports | `allocate_frontend_port()`, `allocate_backend_port()`, `release_ports()` |
| `DatabaseProvisioner` | 160-295 | PostgreSQL DB/user creation | `create_database_and_user()`, `drop_database_and_user()`, `_execute_sql()` |
| `ServiceManager` | 305-596 | PM2 service management | `create_backend_service()`, `start_backend_service()`, `build_frontend()` |
| `NginxConfigurator` | 822-1105 | Nginx config generation | `generate_config()`, `install_config()`, `reload_nginx()` |
| `DeploymentVerifier` | 1115-1200 | Port/health verification | `check_port()`, `check_health_endpoint()`, `verify_deployment()` |
| `DNSProvisioner` | 1210-1370 | DNS A record provisioning | `create_a_record()`, `provision_project_dns()` |
| `InfrastructureManager` | 1375-1800+ | Main orchestrator | `provision_all()` - 8-phase pipeline |

### InfrastructureManager.provision_all() Pipeline

| Phase | Description | Key Actions | Failure Mode |
|-------|-------------|-------------|--------------|
| 1 | Port allocation | Load used ports from DB, scan active ports, allocate frontend (3010-4000) and backend (8010-9000) | Raises `RuntimeError` if no ports available |
| 2 | Database provisioning | Create DB `{name}_db`, user `{name}_user`, 32-char password via Docker exec | Raises exception on SQL failure |
| 3 | Backend environment | Update `.env` with `DATABASE_URL`, `API_PORT`, `PROJECT_NAME` | Continues on file not found |
| 4 | Service configuration | Create PM2 `ecosystem.config.json` for backend with uvicorn | Returns False on write failure |
| 5 | Build frontend | Clean Vite caches → `npm install` → `npm run build` → verify `dist/index.html` | Returns False, logs `PHASE_5_BUILD_FAILED` |
| 6 | Nginx configuration | Generate config with SPA routing, API proxy, SSL support → install → reload nginx | Returns False on nginx reload failure |
| 7 | Start services | PM2 start frontend (serve dist on port) + backend (uvicorn on port) | Logs failure, continues |
| 8 | Health verification | Check frontend port, backend port, `/health` endpoint with retry logic | Returns verification results dict |

### Key Configuration Details

**Port Ranges:** Frontend 3010-4000, Backend 8010-9000
**Database Naming:** `{project_name}_db`, user `{project_name}_user`
**DNS Records:** `{domain}.dreambigwithai.com`, `{domain}-api.dreambigwithai.com`
**Nginx Features:** SPA routing, API proxy, SSL/HTTPS, Let's Encrypt

---

## ACPX Frontend Editor (`acp_frontend_editor_v2.py`)

### Core Classes

| Class | Lines | Purpose |
|-------|-------|---------|
| `ACPPathValidator` | 76-145 | Validate paths (allow src/, forbid node_modules, components/ui) |
| `FilesystemSnapshot` | 147-212 | SHA1 hash comparison, compute diff (added/removed/modified) |
| `ACPSnapshotManager` | 213-307 | Create/restore/cleanup snapshots |
| `ACPBuildGate` | 309-492 | Build verification (clean → install → build → verify dist/) |
| `ACPFrontendEditorV2` | 494-2000+ | Main editor class |

### ACPFrontendEditorV2 Key Methods

| Method | Lines | Purpose |
|--------|-------|---------|
| `apply_changes_via_acpx()` | 524-900 | Main execution - spawn Claude, monitor, validate, build |
| `_extract_required_pages_from_prompt()` | 1456-1588 | Extract page names from description |
| `_build_acpx_prompt()` | 1590-1866 | Build ACPX prompt with page specs |
| `_enforce_page_guardrails()` | 1908-? | Enforce page structure rules |

### Execution Flow

1. **Snapshot:** Capture before state (SHA1 hashes of all files in `src/`, excluding `node_modules`, `.git`, `dist`)
2. **Extract Pages:** Parse goal description using `_extract_required_pages_from_prompt()` - detects page names via keywords, Groq inference, conjunction stripping
3. **Build Prompt:** Generate ACPX prompt with page specs, templates, project context, and customization guidelines
4. **Execute ACPX:** Spawn Claude Code worker process, monitor stdout/stderr streams with watchdog timer (300s max idle)
5. **Diff Changes:** Compare before/after filesystem hashes using `FilesystemSnapshot.compute_diff()` - returns added/removed/modified lists
6. **Validate:** Check paths with `ACPPathValidator.is_path_allowed()`, enforce max 50 new files limit
7. **Build Gate:** Run `ACPBuildGate.run_build()` - clean Vite caches → `npm install` → `npm run build` → verify `dist/index.html` (30-min timeout)
8. **Rollback if Failed:** Call `ACPSnapshotManager.restore_snapshot()` on build failure or validation failure
9. **Post-Processing:** Fix duplicate "/" routes, add Layout wrapper, replace `{children}` with `<Outlet />`, remove unused imports

**Watchdog Timer:** Monitors stdout/stderr streams, terminates if idle for 300s (5 minutes)
**Rollback Strategy:** Full filesystem restore from backup directory `frontend_backup_{timestamp}/`

---

## Fast Wrapper (`fast_wrapper.py`)

### FastWrapper Methods

| Method | Lines | Purpose |
|--------|-------|---------|
| `__init__()` | 53-100 | Initialize wrapper |
| `update_status()` | 62-100 | Update project status in DB |
| `git_clone()` / `_copy_blank_template()` | 102-238 | Clone/copy template to frontend/ |
| `create_backend()` | 240-314 | Create backend/main.py skeleton |
| `create_database_setup()` | 316-389 | Create backend/init.sql |
| `create_environment()` | 391-418 | Create backend/.env |
| `run()` | 420-470 | Execute all tasks |

### Template Strategy

- **Mode:** `EMPTY_TEMPLATE_MODE = True` (always use blank template)
- **Path:** `templates/blank-template`
- **Reason:** Clean starting point, AI builds frontend from scratch in Phase 8/9
- **Fallback:** If blank template not found, logs warning and continues

### Backend Files Created

**`backend/main.py` (240-314):**
- FastAPI app with CORS middleware
- Health check endpoint: `GET /health` → `{"status": "healthy"}`
- Basic API structure ready for extension

**`backend/init.sql` (316-389):**
- Table creation SQL (users, data tables)
- Index definitions for performance
- Seed data placeholders

**`backend/.env` (391-418):**
- `PROJECT_NAME` - Project name
- `DATABASE_URL` - Populated in Phase 3 (PostgreSQL connection string)
- `API_PORT` - Populated in Phase 4 (backend port)
- `BACKEND_HOST` - Default: `0.0.0.0`

### Task Execution Order

1. **Task 1:** Template already selected via Groq in `app.py` (skip)
2. **Task 2:** Copy `templates/blank-template` → `project_path/frontend/`
3. **Task 3:** Create `backend/main.py` with FastAPI skeleton
4. **Task 4:** Create `backend/init.sql` with table schemas
5. **Task 5:** Create `backend/.env` with environment variables

**Status Updates:** Calls `update_status("scaffolding")` during execution, `update_status("scaffolded")` on completion

---

## Supporting Services

| Service | File | Lines | Purpose | Key Methods |
|---------|------|-------|---------|-------------|
| GroqService | `groq_service.py` | 15-100 | AI completions | `complete()`, `infer_template()`, `infer_pages()` |
| PageManifest | `page_manifest.py` | 1-200 | Track pages | `create_page_manifest()`, `scaffold_pages()` |
| DeploymentVerifier | `deployment_verifier.py` | 50-200 | Verify deployment | `verify_all()`, `check_build_output()`, `check_http_response()` |
| DNS Manager | `dns_manager.py` | 1-150 | Hostinger DNS API | `create_a_record()`, `check_subdomain_exists()` |
| ContextInjector | `context_injector.py` | 1-100 | Inject context | `inject_context()`, `load_project_info()` |
| FrontendOptimizer | `frontend_optimizer.py` | 1-300 | Rule-based branding | `run()`, `update_package_json()`, `update_index_html()` |

### FrontendOptimizer Changes (Phase 9 Step 0)

- **package.json:** Update name, description, version
- **index.html:** Update title, meta description
- **App.tsx:** Update hero section, branding
- **.env:** Update project name, API URL

### DeploymentVerifier Details (`deployment_verifier.py`)

**Retry Logic:**
- Max retries: 3 attempts
- Retry delay: 5.0s (exponential backoff: 5s → 10s → 20s)
- HTTP timeout: 30.0s per request

**Verification Checks:**
1. **Build output:** Check `dist/index.html` exists and not empty
2. **Nginx config:** Verify `{domain}.conf` exists in `/etc/nginx/sites-available/`
3. **DNS resolution:** Resolve `{domain}.dreambigwithai.com` to server IP
4. **HTTP response:** GET request to frontend, expect 200 OK
5. **PM2 status:** Check PM2 process running for frontend/backend services

**Result Structure:**
```python
{
  "success": True/False,
  "checks": {
    "build_output": VerificationResult(...),
    "nginx_config": VerificationResult(...),
    "dns_resolution": VerificationResult(...),
    "http_response": VerificationResult(...),
    "pm2_status": VerificationResult(...)
  },
  "failed_checks": ["check_name", ...],
  "total_duration": 12.5
}
```

### DNS Manager Details (`dns_manager.py`)

**Hostinger API Integration:**
- Requires `HOSTINGER_API_TOKEN` environment variable
- Base URL: `https://developers.hostinger.com/api/dns/v1`
- Zone ID: `dreambigwithai.com`

**DNS Record Types:**
- **A Record:** Maps subdomain to IPv4 address (195.200.14.37)
- **TTL:** Default 14400 seconds (4 hours)
- **Propagation:** 5-60 minutes for global DNS propagation

**Methods:**
- `check_subdomain_exists(domain, subdomain)` → Returns `(exists: bool, current_ip: str)`
- `create_a_record(domain, subdomain, ip, ttl)` → Returns success bool
- `update_a_record(domain, subdomain, ip)` → Updates existing record
- `delete_a_record(domain, subdomain)` → Removes record

**Wildcard DNS:** `*.dreambigwithai.com` pre-configured, so manual DNS provisioning often skipped

---

## Database Layer

### PostgreSQL Connection (`database_postgres.py`)

**Methods:** `get_connection()`, `execute_query()`, `execute_insert()`, `close_connection()`
**Settings:** Host: localhost:5432, DB: dreampilot, User: admin

### Database Adapter (`database_adapter.py`)

**Methods:** `get_project()`, `get_project_by_name()`, `update_project_status()`, `delete_project()`
**Supports:** PostgreSQL (primary), SQLite (fallback)

### Schema (`projects_schema.sql`)

**Tables:** `projects`, `project_types`, `templates`

**Projects Table:**
| Column | Type | Description |
|--------|------|-------------|
| `id` | SERIAL PRIMARY KEY | Auto-increment ID |
| `user_id` | INTEGER | Foreign key to users table |
| `name` | VARCHAR(255) | Project name (unique) |
| `domain` | VARCHAR(255) | Subdomain (e.g., "myproject") |
| `description` | TEXT | Project description |
| `project_path` | VARCHAR(500) | Filesystem path to project |
| `status` | VARCHAR(50) | Current status: creating, scaffolding, ready, error |
| `template_id` | VARCHAR(100) | Template identifier (e.g., "blank-template") |
| `frontend_port` | INTEGER | Frontend port (3010-4000) |
| `backend_port` | INTEGER | Backend port (8010-9000) |
| `created_at` | TIMESTAMP | Creation timestamp |
| `updated_at` | TIMESTAMP | Last update timestamp |

**Status Values:**
- `creating` - Initial state after POST /projects
- `scaffolding` - Fast wrapper executing
- `scaffolded` - Fast wrapper completed
- `provisioning` - Infrastructure manager running
- `ai_provisioning` - Phase 8/9 AI refinement
- `ready` - All phases complete
- `error` - Pipeline failed

### Connection Pooling (`database_postgres.py`)

**Pool Configuration:**
- Min connections: 2
- Max connections: 10
- Connection timeout: 30s
- Idle timeout: 300s (5 minutes)

**Methods:**
- `get_connection()` - Get connection from pool, blocks if pool exhausted
- `execute_query(query, params)` - Execute SELECT, returns list of rows
- `execute_insert(query, params)` - Execute INSERT, returns new row ID
- `close_connection(conn)` - Return connection to pool (not actual close)

---

## Common Modifications

### Add New Page Type

| Step | File | Lines | Action |
|------|------|-------|--------|
| 1 | `acp_frontend_editor_v2.py` | 1460-1490 | Add keyword mapping for page detection |
| 2 | `page_specs.py` | - | Define page spec with components, layout |
| 3 | `templates/` | - | Create template file if needed |

**Example:**
```python
# acp_frontend_editor_v2.py:1470
"analytics": ["dashboard", "metrics", "charts", "reports"],
"settings": ["config", "preferences", "account"],
```

### Modify Build Process

| Step | File | Lines | Action |
|------|------|-------|--------|
| 1 | `infrastructure_manager.py` | 1700-1860 | Edit `build_frontend()` method |
| 2 | `deployment_verifier.py` | 100-150 | Update build verification logic |

**Common Changes:**
- Add build cache cleaning: `shutil.rmtree("node_modules/.cache")`
- Modify npm flags: `--legacy-peer-deps`, `--force`
- Add custom build steps: Run tests, linting before build

### Add New Pipeline Phase

| Step | File | Action |
|------|------|--------|
| 1 | `openclaw_wrapper.py` | Create `phase_X_name()` method returning bool |
| 2 | `openclaw_wrapper.py` | Add to `run_all_phases()` execution order |
| 3 | `pipeline_status.py` | Add to `PipelinePhase` enum |
| 4 | `pipeline_status.py` | Add error codes if needed |

**Template:**
```python
def phase_X_name(self) -> bool:
    logger.info("📋 Phase X/9: Phase Name")
    self.status_tracker.start_phase(PipelinePhase.PHASE_NAME)
    try:
        # Implementation
        self.completed_phases.append("Phase Name")
        self.status_tracker.complete_phase(PipelinePhase.PHASE_NAME, {...})
        return True
    except Exception as e:
        logger.error(f"❌ Phase X failed: {e}")
        self.status_tracker.fail_phase(PipelinePhase.PHASE_NAME, ...)
        return False
```

### Fix Routing Issues

| Issue | File | Lines | Fix |
|-------|------|-------|-----|
| Duplicate "/" routes | `acp_frontend_editor_v2.py` | 992-1065 | Step 10.5 - Detect and merge duplicate routes |
| Missing Layout wrapper | `acp_frontend_editor_v2.py` | 992-1065 | Wrap routes with `<Layout>` component |
| Missing Outlet | `acp_frontend_editor_v2.py` | 1072-1118 | Step 10.6 - Replace `{children}` with `<Outlet />` |

**Detection Logic:**
```python
# Finds routes like: <Route path="/" /> and <Route path="/" element={<Home />} />
# Merges into single route with proper element
```

### Modify DNS/Domain Handling

| Task | File | Lines | Action |
|------|------|-------|--------|
| Change base domain | `infrastructure_manager.py` | 36 | Update `BASE_DOMAIN = "dreambigwithai.com"` |
| Change server IP | `infrastructure_manager.py` | 37 | Update `SERVER_IP = "195.200.14.37"` |
| Add DNS provider | `dns_manager.py` | 1-150 | Implement new provider API client |
| Modify nginx template | `infrastructure_manager.py` | 878-1021 | Edit `generate_config()` method |

### Customize Frontend Optimization

| File | Lines | Customization |
|------|-------|---------------|
| `frontend_optimizer.py` | 50-100 | Add custom package.json fields |
| `frontend_optimizer.py` | 120-180 | Customize index.html template |
| `frontend_optimizer.py` | 200-250 | Modify App.tsx branding logic |
| `frontend_optimizer.py` | 260-300 | Add environment variable injection |

---

## Key Configuration

**Environment Variables:**
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`
- `USE_POSTGRES` (default: true)
- `HOSTINGER_API_TOKEN` (optional, for DNS)

**Timeouts:**
- Build: 30 minutes (1800s)
- ACPX watchdog: 5 minutes (300s)
- HTTP verification: 30s

**Limits:**
- Max new files (ACPX): 50
- Frontend ports: 3010-4000
- Backend ports: 8010-9000
