# Project Creation API

> [SKILL.md](../.agents/skills/project-info/SKILL.md) | [TOC](toc.md) | Updated: 2026-03-15

---

## API Endpoints

| Endpoint | Method | File:Lines |
|----------|--------|------------|
| `/projects` | POST | `app.py:50-120` |
| `/projects` | GET | `app.py:125-150` |
| `/projects/{id}` | GET/DELETE | `app.py:155-210` |
| `/projects/{id}/status` | GET | `app.py:215-240` |
| `/projects/{id}/deploy` | POST | `app.py:245-280` |

---

## Pipeline Phases

| # | Function | File:Lines |
|---|----------|------------|
| 1 | `phase_1_analyze_project()` | `openclaw_wrapper.py:200-250` |
| 2 | `phase_2_template_setup()` | `openclaw_wrapper.py:255-300` |
| 3 | `phase_9_acp_frontend_editor()` | `openclaw_wrapper.py:305-450` |
| 4 | `phase_3_database_provisioning()` | `infrastructure_manager.py:200-280` |
| 5 | `phase_4_port_allocation()` | `infrastructure_manager.py:285-350` |
| 6 | `phase_5_service_setup()` | `infrastructure_manager.py:355-500` |
| 7 | `phase_6_nginx_routing()` | `infrastructure_manager.py:505-650` |
| 9 | `phase_7_verification()` | `deployment_verifier.py:50-200` |

---

## ACPX Editor (`acp_frontend_editor_v2.py`)

| Component | Lines |
|-----------|-------|
| Main Class | 80-200 |
| Path Validator | 48-100 |
| Snapshot System | 250-350 |
| Page Extraction | 1456-1600 |
| ACPX Execution | 600-850 |
| Routing Fix (10.5) | 992-1065 |
| Layout Outlet (10.6) | 1072-1118 |
| Empty Pages (13) | 1177-1240 |

---

## Infrastructure (`infrastructure_manager.py`)

| Component | Lines |
|-----------|-------|
| Port Allocator | 100-180 |
| Service Manager | 350-500 |
| Build Frontend | 1700-1860 |

---

## Services

| Service | File:Lines |
|---------|------------|
| Groq AI | `groq_service.py:15-100` |
| Template Selector | `template_selector.py:20-100` |
| Page Manifest | `page_manifest.py:1-200` |
| Deployment Verifier | `deployment_verifier.py:50-200` |
| DNS Manager | `dns_manager.py:1-150` |

---

## Database

| Component | File:Lines |
|-----------|------------|
| PostgreSQL | `database_postgres.py:20-100` |
| Adapter | `database_adapter.py:1-100` |
| Schema | `projects_schema.sql:1-50` |

---

## Common Tasks

| Task | Files to Edit |
|------|---------------|
| Add page type | `acp_frontend_editor_v2.py:1460-1490`, `page_specs.py` |
| Modify build | `infrastructure_manager.py:1700-1860` |
| Add pipeline phase | `openclaw_wrapper.py`, `pipeline_status.py` |
| Fix routing | `acp_frontend_editor_v2.py:992-1118` |
