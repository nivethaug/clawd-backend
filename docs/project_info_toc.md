# Project Creation API - Detailed Reference

> [SKILL.md](../.agents/skills/project-info/SKILL.md) | [TOC](toc.md) | Updated: 2026-03-15

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/projects` | POST | Create new project |
| `/projects` | GET | List all projects |
| `/projects/{project_id}` | GET | Get project details |
| `/projects/{project_id}` | PUT | Update project |
| `/projects/{project_id}` | DELETE | Delete project |
| `/projects/{project_id}/status` | GET | Get pipeline status |
| `/projects/{project_id}/ai-status` | GET | Get AI refinement status |
| `/projects/{project_id}/claude-session` | GET | Get Claude session info |
| `/projects/{project_id}/publish/frontend` | POST | Build & publish frontend |
| `/projects/{project_id}/publish/backend` | POST | Build & publish backend |
| `/projects/{project_id}/sessions` | GET | List project sessions |
| `/projects/{project_id}/sessions` | POST | Create session |
| `/projects/{project_id}/sessions/{session_id}` | DELETE | Delete session |
| `/projects/{project_id}/files` | GET | List project files |
| `/projects/{project_id}/files/{path}` | GET | Get file content |
| `/projects/{project_id}/files/{path}` | PUT | Save file content |
| `/project-types` | GET | List project types |
| `/templates` | GET | List templates |
| `/templates/select` | POST | Select template |
| `/chat` | POST | Chat completion |
| `/chat/stream` | POST | Streaming chat |
| `/ai/completion` | POST | AI completion |
| `/health` | GET | Health check |

---

## Project Creation Pipeline

### Entry Point Flow

| Step | File | Lines | Description |
|------|------|-------|-------------|
| 1. API Request | `app.py` | 50-70 | Validate project name, template, user_id |
| 2. DB Insert | `app.py` | 80-95 | Insert project record with `status='creating'` |
| 3. Template Selection | `app.py` | 96-105 | Call `TemplateSelector.select_template()` |
| 4. Worker Trigger | `claude_code_worker.py` | 50-80 | Start background `run_claude_code_background()` |
| 5. Fast Scaffolding | `fast_wrapper.py` | 50-240 | Create project structure |

### Fast Scaffolding Tasks (`fast_wrapper.py`)

| Task | Lines | Description |
|------|-------|-------------|
| Task 1 | 50-80 | Select template (skip if provided) |
| Task 2 | 85-120 | Git clone or copy blank template |
| Task 3 | 125-160 | Create backend skeleton (`main.py`) |
| Task 4 | 165-200 | Create database setup (`init.sql`) |
| Task 5 | 205-240 | Create `.env` config file |

---

## Pipeline Phases

| Phase | Function | File | Lines | Description |
|-------|----------|------|-------|-------------|
| 1 | `phase_1_analyze_project()` | `openclaw_wrapper.py` | 200-250 | Analyze project requirements, detect tech stack |
| 2 | `phase_2_template_setup()` | `openclaw_wrapper.py` | 255-300 | Verify frontend/backend directories exist |
| 3 | `phase_9_acp_frontend_editor()` | `openclaw_wrapper.py` | 305-450 | Run ACPX frontend customization |
| 4 | `phase_3_database_provisioning()` | `infrastructure_manager.py` | 200-280 | Create database, run migrations |
| 5 | `phase_4_port_allocation()` | `infrastructure_manager.py` | 285-350 | Allocate ports for frontend/backend |
| 6 | `phase_5_service_setup()` | `infrastructure_manager.py` | 355-500 | PM2 setup, build, infrastructure |
| 7 | `phase_6_nginx_routing()` | `infrastructure_manager.py` | 505-650 | Configure nginx reverse proxy |
| 8 | *(skipped)* | - | - | Legacy AI refinement phase |
| 9 | `phase_7_verification()` | `deployment_verifier.py` | 50-200 | Verify deployment health |

---

## ACPX Frontend Editor (`acp_frontend_editor_v2.py`)

### Core Components

| Component | Lines | Description |
|-----------|-------|-------------|
| Main Class | 80-200 | `ACPFrontendEditorV2` class definition |
| Path Validator | 48-100 | `ACPPathValidator.is_path_allowed()` security check |
| Snapshot System | 250-350 | Before/after filesystem snapshots |
| Change Detection | 355-450 | Compare snapshots for file changes |

### Page Detection

| Component | Lines | Description |
|-----------|-------|-------------|
| Page Extraction | 1456-1600 | `_extract_required_pages_from_prompt()` |
| Conjunction Stripping | 1532-1541 | Strip `and`, `or`, `&` from page names |
| Groq Inference | 1470-1510 | AI-based page name inference |
| Keyword Matching | 1520-1560 | Fallback keyword detection |

### ACPX Execution

| Component | Lines | Description |
|-----------|-------|-------------|
| Main Execution | 600-850 | `apply_changes_via_acpx()` main loop |
| Watchdog Timer | 698-800 | Idle timeout monitoring (300s max) |
| Build Gate | 850-950 | Verify build success before applying |
| Error Recovery | 960-990 | Handle build failures, retry logic |

### Post-Processing Fixes

| Step | Lines | Description |
|------|-------|-------------|
| **10.5** Routing Fix | 992-1065 | Fix duplicate "/" routes, add Layout wrapper |
| **10.6** Layout Outlet | 1072-1118 | Replace `{children}` → `<Outlet />` |
| **11** Import Cleanup | 1120-1170 | Remove unused imports |
| **13** Empty Pages | 1177-1240 | Detect and repopulate empty page components |

---

## Infrastructure Manager (`infrastructure_manager.py`)

### Core Components

| Component | Lines | Description |
|-----------|-------|-------------|
| Port Allocator | 100-180 | `PortAllocator` - manage port assignments |
| Service Manager | 350-500 | `ServiceManager` - PM2 process control |
| DNS Manager | `dns_manager.py:1-150` | Hostinger API DNS client |
| Nginx Config | 505-650 | Generate nginx site configs |

### Build Process

| Step | Lines | Description |
|------|-------|-------------|
| Clean Caches | 1710-1730 | Remove `.vite`, `node_modules/.cache` |
| npm install | 1755-1780 | Install dependencies with npm |
| npm run build | 1785-1810 | Build production bundle |
| Verify dist | 1815-1835 | Check `dist/index.html` exists |
| Cleanup | 1850-1860 | Remove `node_modules/` to save space |

---

## Services

| Service | File | Lines | Description |
|---------|------|-------|-------------|
| Groq AI | `groq_service.py` | 15-100 | `GroqService` - AI completions |
| Template Selector | `template_selector.py` | 20-100 | `TemplateSelector` - match templates |
| Page Manifest | `page_manifest.py` | 1-200 | `PageManifest` - track pages |
| Deployment Verifier | `deployment_verifier.py` | 50-200 | `DeploymentVerifier` - health checks |
| DNS Manager | `dns_manager.py` | 1-150 | Hostinger DNS API |
| Context Injector | `context_injector.py` | 1-100 | Inject project context |

---

## Database

| Component | File | Lines | Description |
|-----------|------|-------|-------------|
| PostgreSQL Connection | `database_postgres.py` | 20-100 | Connection pooling, queries |
| DB Adapter | `database_adapter.py` | 1-100 | Abstraction layer for DB ops |
| Schema | `projects_schema.sql` | 1-50 | Table definitions |

---

## Common Modifications

### Add New Page Type

1. Update keyword mapping: `acp_frontend_editor_v2.py:1460-1490`
2. Add page spec: `page_specs.py`
3. Update template files in `templates/`

### Modify Build Process

1. Edit build method: `infrastructure_manager.py:1700-1860`
2. Update verification: `deployment_verifier.py:100-150`

### Add New Pipeline Phase

1. Create phase function in `openclaw_wrapper.py`
2. Add to `run_all_phases()` loop
3. Update `pipeline_status.py` enum

### Fix Routing Issues

1. Update Step 10.5: `acp_frontend_editor_v2.py:992-1065`
2. Update Step 10.6: `acp_frontend_editor_v2.py:1072-1118`

### Modify DNS/Domain Handling

1. DNS Manager: `dns_manager.py:1-150`
2. Nginx config: `infrastructure_manager.py:505-650`
