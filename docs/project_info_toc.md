# Project Creation API - Table of Contents

> Project Management Endpoints with Code References
> Last updated: 2026-03-15

---

## API Endpoints

| Endpoint | Method | File | Lines | Handler Function |
|----------|--------|------|-------|------------------|
| `/projects` | POST | `app.py` | 50-120 | `create_project()` |
| `/projects` | GET | `app.py` | 125-150 | `list_projects()` |
| `/projects/{id}` | GET | `app.py` | 155-180 | `get_project()` |
| `/projects/{id}` | DELETE | `app.py` | 185-210 | `delete_project()` |
| `/projects/{id}/status` | GET | `app.py` | 215-240 | `get_project_status()` |
| `/projects/{id}/deploy` | POST | `app.py` | 245-280 | `trigger_deploy()` |

---

## Project Creation Pipeline

### Entry Point

| Component | File | Lines | Description |
|-----------|------|-------|-------------|
| API Endpoint | `app.py` | 50-120 | `POST /projects` - validates and creates project |
| DB Insert | `app.py` | 80-95 | Insert project record with `status='creating'` |
| Template Selection | `app.py` | 96-105 | `TemplateSelector.select_template()` |
| Worker Trigger | `claude_code_worker.py` | 50-80 | `run_claude_code_background()` |

### Fast Scaffolding (fast_wrapper.py)

| Task | Lines | Description |
|------|-------|-------------|
| Task 1 | 50-80 | Select template (skipped if provided) |
| Task 2 | 85-120 | Git clone or copy blank template |
| Task 3 | 125-160 | Create backend skeleton (`main.py`) |
| Task 4 | 165-200 | Create database setup (`init.sql`) |
| Task 5 | 205-240 | Create `.env` config |

---

## Pipeline Phases

| Phase | Function | File | Lines | Description |
|-------|----------|------|-------|-------------|
| 1 | `phase_1_analyze_project()` | `openclaw_wrapper.py` | 200-250 | Analyze project requirements |
| 2 | `phase_2_template_setup()` | `openclaw_wrapper.py` | 255-300 | Verify frontend/backend directories |
| 3 | `phase_9_acp_frontend_editor()` | `openclaw_wrapper.py` | 305-450 | ACPX frontend customization |
| 4 | `phase_3_database_provisioning()` | `infrastructure_manager.py` | 200-280 | Database provisioning |
| 5 | `phase_4_port_allocation()` | `infrastructure_manager.py` | 285-350 | Port allocation |
| 6 | `phase_5_service_setup()` | `infrastructure_manager.py` | 355-500 | PM2 + build + infrastructure |
| 7 | `phase_6_nginx_routing()` | `infrastructure_manager.py` | 505-650 | Nginx configuration |
| 8 | *(skipped)* | - | - | Legacy AI refinement |
| 9 | `phase_7_verification()` | `deployment_verifier.py` | 50-200 | Deployment verification |

---

## ACPX Frontend Editor

### Core Components

| Component | File | Lines | Description |
|-----------|------|-------|-------------|
| Main Class | `acp_frontend_editor_v2.py` | 80-200 | `ACPFrontendEditorV2` class definition |
| Path Validator | `acp_frontend_editor_v2.py` | 48-100 | `ACPPathValidator.is_path_allowed()` |
| Snapshot System | `acp_frontend_editor_v2.py` | 250-350 | Before/after filesystem snapshots |
| Change Detection | `acp_frontend_editor_v2.py` | 355-450 | Compare snapshots for changes |

### Page Detection

| Component | Lines | Description |
|-----------|-------|-------------|
| Page Extraction | 1456-1600 | `_extract_required_pages_from_prompt()` |
| Conjunction Stripping | 1532-1541 | Strip `and`, `or`, `&` from page names |
| Groq Inference | 1470-1510 | AI-based page inference |
| Keyword Matching | 1520-1560 | Fallback keyword detection |

### ACPX Execution

| Component | Lines | Description |
|-----------|-------|-------------|
| Main Execution | 600-850 | `apply_changes_via_acpx()` |
| Watchdog Timer | 698-800 | Idle timeout monitoring (300s) |
| Build Gate | 850-950 | Verify build before applying |

### Post-Processing Fixes

| Step | Lines | Description |
|------|-------|-------------|
| **Step 10.5** Routing Fix | 992-1065 | Fix duplicate "/" routes, add Layout wrapper |
| **Step 10.6** Layout Outlet | 1072-1118 | Replace `{children}` → `<Outlet />` |
| **Step 13** Empty Pages | 1177-1240 | Detect and repopulate empty pages |

---

## Infrastructure Manager

### Components

| Component | File | Lines | Description |
|-----------|------|-------|-------------|
| Port Allocator | `infrastructure_manager.py` | 100-180 | `PortAllocator` class |
| Service Manager | `infrastructure_manager.py` | 350-500 | `ServiceManager` class |
| DNS Manager | `dns_manager.py` | 1-150 | Hostinger API client |

### Build Process

| Step | Lines | Description |
|------|-------|-------------|
| Clean Caches | 1710-1730 | Remove Vite caches |
| npm install | 1755-1780 | Install dependencies |
| npm run build | 1785-1810 | Build production bundle |
| Verify dist | 1815-1835 | Check `dist/index.html` |
| Cleanup | 1850-1860 | Remove `node_modules/` |

---

## Services

| Service | File | Lines | Description |
|---------|------|-------|-------------|
| Groq AI | `groq_service.py` | 15-100 | `GroqService` class |
| Template Selection | `template_selector.py` | 20-100 | `TemplateSelector` class |
| Page Manifest | `page_manifest.py` | 1-200 | `PageManifest` class |
| Deployment Verifier | `deployment_verifier.py` | 50-200 | `DeploymentVerifier` class |

---

## Database

| Component | File | Lines | Description |
|-----------|------|-------|-------------|
| PostgreSQL Connection | `database_postgres.py` | 20-100 | Connection pooling |
| DB Adapter | `database_adapter.py` | 1-100 | Abstraction layer |
| Schema | `projects_schema.sql` | 1-50 | Table definitions |

---

## Common Modifications

### Add New Page Type

1. Update keyword mapping: `acp_frontend_editor_v2.py:1460-1490`
2. Add page spec: `page_specs.py`
3. Update template: Template files in `templates/`

### Modify Build Process

1. Edit build method: `infrastructure_manager.py:1700-1860`
2. Update verification: `deployment_verifier.py:100-150`

### Add New Pipeline Phase

1. Create phase function in `openclaw_wrapper.py`
2. Add to `run_all_phases()` loop
3. Update `pipeline_status.py` enum if needed

### Fix Routing Issues

1. Update Step 10.5: `acp_frontend_editor_v2.py:992-1065`
2. Update Step 10.6: `acp_frontend_editor_v2.py:1072-1118`
