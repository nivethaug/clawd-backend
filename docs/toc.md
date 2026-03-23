# DreamPilot Documentation - Master Table of Contents

> **Purpose:** Help AI agents quickly navigate codebase by API endpoint
> Last updated: 2026-03-15

---

## 🔗 Quick Links

| Document | Purpose |
|----------|---------|
| [SKILL.md](../.agents/skills/project-info/SKILL.md) | Agent skill reference |
| [project_creation.md](./project_creation.md) | Complete pipeline & infrastructure reference |

---

## API Endpoints

### Project Creation & Management

| Endpoint | Method | File:Lines | Docs |
|----------|--------|------------|------|
| `/projects` | POST | `app.py:283-510` | [project_creation.md](./project_creation.md) |
| `/projects` | GET | `app.py:241-280` | [project_creation.md](./project_creation.md) |
| `/projects/{id}` | PUT | `app.py:1357-1436` | [project_deletion.md](./project_deletion.md) |
| `/projects/{id}` | DELETE | `app.py:1204-1357` | [project_deletion.md](./project_deletion.md) |

### Dashboard

| Endpoint | Method | File:Lines | Docs |
|----------|--------|------------|------|
| `/dashboard/home` | GET | `app.py:3595-3680` | [dashboard.md](./dashboard.md) |

### Recent Activity

| Endpoint | Method | File:Lines | Docs |
|----------|--------|------------|------|
| `/projects/recent-activity` | GET | `app.py:3485-3545` | [recent_activity.md](./recent_activity.md) |
| `/projects/recent-activity/simple` | GET | `app.py:3548-3560` | [recent_activity.md](./recent_activity.md) |
| `/projects/{id}/activity` | GET | `app.py:3563-3590` | [recent_activity.md](./recent_activity.md) |

### Project Status

| Endpoint | Method | File:Lines | Docs |
|----------|--------|------------|------|
| `/projects/{id}/status` | GET | `app.py:1624-1657` | [project_status.md](./project_status.md) |
| `/projects/{id}/ai-status` | GET | `app.py:1657-1813` | [project_status.md](./project_status.md) |
| `/projects/{id}/claude-session` | GET | `app.py:1819-1880` | [project_status.md](./project_status.md) |

### Project Publish

| Endpoint | Method | File:Lines | Docs |
|----------|--------|------------|------|
| `/projects/{id}/publish/frontend` | POST | `app.py:1436-1534` | [publish_frontend.md](./publish_frontend.md) |
| `/projects/{id}/publish/backend` | POST | `app.py:1534-1624` | [publish_backend.md](./publish_backend.md) |

### Project Sessions

| Endpoint | Method | File:Lines | Docs |
|----------|--------|------------|------|
| `/projects/{id}/sessions` | GET | `app.py:1882-1903` | [project_sessions.md](./project_sessions.md) |
| `/projects/{id}/sessions` | POST | `app.py:1905-1945` | [project_sessions.md](./project_sessions.md) |
| `/projects/{id}/sessions/{sid}` | DELETE | `app.py:1956-2020` | [project_sessions.md](./project_sessions.md) |
| `/sessions/{sid}/messages` | GET | `app.py:2019-2035` | [project_sessions.md](./project_sessions.md) |
| `/sessions/details` | GET | `app.py:2302-2415` | [project_sessions.md](./project_sessions.md) |

### Session Locking

| Endpoint | Method | File:Lines | Docs |
|----------|--------|------------|------|
| `/projects/{id}/active-session` | GET | `app.py:1888-1905` | [session_locking.md](./session_locking.md) |
| `/projects/{id}/lock` | DELETE | `app.py:1908-1933` | [session_locking.md](./session_locking.md) |
| `/sessions/{sid}/release-lock` | POST | `app.py:1936-1958` | [session_locking.md](./session_locking.md) |

### Chat

| Endpoint | Method | File:Lines | Docs |
|----------|--------|------------|------|
| `/chat` | POST | `app.py:2081-2155` | [chat.md](./chat.md) |
| `/chat/stream` | POST | `app.py:2038-2081` | [chat_stream.md](./chat_stream.md) |

### AI Completion

| Endpoint | Method | File:Lines | Docs |
|----------|--------|------------|------|
| `/ai/completion` | POST | `app.py:2420-2480` | [ai_completion.md](./ai_completion.md) |

### Project Files

| Endpoint | Method | File:Lines | Docs |
|----------|--------|------------|------|
| `/projects/{id}/files` | GET | `app.py:2154-2185` | [project_creation.md](./project_creation.md) |
| `/projects/{id}/files/{path}` | GET | `app.py:2187-2225` | [project_creation.md](./project_creation.md) |
| `/projects/{id}/files/{path}` | PUT | `app.py:2227-2265` | [project_creation.md](./project_creation.md) |

### Templates & Types

| Endpoint | Method | File:Lines | Docs |
|----------|--------|------------|------|
| `/project-types` | GET | `app.py:515-528` | [project_creation.md](./project_creation.md) |
| `/templates` | GET | `app.py:574-600` | [project_creation.md](./project_creation.md) |
| `/templates/select` | POST | `app.py:530-572` | [project_creation.md](./project_creation.md) |

### System

| Endpoint | Method | File:Lines | Docs |
|----------|--------|------------|------|
| `/health` | GET | `app.py:2269-2278` | - |

---

## Documentation Files

| File | Description |
|------|-------------|
| [project_creation.md](./project_creation.md) | Complete reference: API, pipeline, ACPX, infrastructure |
| [dashboard.md](./dashboard.md) | Dashboard home API (single-call for home page) |
| [recent_activity.md](./recent_activity.md) | Recent work/activity API for Activity page |
| [project_status.md](./project_status.md) | Status & AI status endpoints |
| [project_deletion.md](./project_deletion.md) | Delete/update projects |
| [project_sessions.md](./project_sessions.md) | Session management |
| [chat.md](./chat.md) | Non-streaming chat |
| [chat_stream.md](./chat_stream.md) | Streaming chat (SSE) |
| [session_locking.md](./session_locking.md) | Session locking (single active session per project) |
| [ai_completion.md](./ai_completion.md) | AI completion endpoint |
| [publish_frontend.md](./publish_frontend.md) | Frontend build & publish |
| [publish_backend.md](./publish_backend.md) | Backend build & publish |
3. **Find the exact file and line numbers** for the code you need
4. **Make targeted changes** using the line references

### Adding New Documentation

1. Create `{feature}_toc.md` in `docs/` folder
2. Add endpoint table to this file
3. Include file paths and line numbers for quick navigation

### Infrastructure & Deployment

| Document | Path | Contains | When to Use |
|----------|------|----------|-------------|
| **PostgreSQL Migration** | `POSTGRESQL_MIGRATION_GUIDE.md` | Database migration steps | Migrating from SQLite to PostgreSQL |
| **Implementation Summary** | `IMPLEMENTATION_SUMMARY.md` | Feature implementations | Understanding implemented features |
| **Deployment Paths** | `legacy/DEPLOYMENT_PATHS.md` | File paths, directories | Finding deployed files |

### Prompts & AI Instructions

| Document | Path | Contains | When to Use |
|----------|------|----------|-------------|
| **Page Inference** | `prompts/01-page-inference.md` | Groq page detection prompt | Modifying page detection |
| **ACPX Editor** | `prompts/02-acpx-frontend-editor.md` | ACPX frontend prompt | Modifying frontend generation |
| **Infrastructure Task** | `prompts/03-infrastructure-task.md` | Infrastructure prompt | Modifying deployment logic |
| **AI Refinement** | `prompts/04-ai-refinement.md` | AI refinement prompt | Modifying post-processing |
| **Build Fix** | `prompts/05-build-fix.md` | Build error fix prompt | Modifying build error handling |

### Skills (Agent Instructions)

| Document | Path | Contains | When to Use |
|----------|------|----------|-------------|
| **Project Info Skill** | `.agents/skills/project-info/SKILL.md` | Full project knowledge | Understanding codebase |
| **Spec Skill** | `.agents/skills/spec.md` | PRD generation instructions | Creating documentation |

---

## 🚀 Quick Reference by Task

### "I want to create a new project"

1. **Understand the flow:** `docs/project_info_toc.md` → Project Creation Pipeline
2. **See the code:** `app.py:1-100` (POST /projects)
3. **Background worker:** `claude_code_worker.py:1-150`
4. **Pipeline phases:** `openclaw_wrapper.py:1-100`

### "I want to modify ACPX frontend editing"

1. **Understand ACPX:** `ACP_CONTROLLED_FRONTEND_EDIT.md`
2. **See TOC:** `docs/project_info_toc.md` → ACPX Frontend Editor
3. **Main class:** `acp_frontend_editor_v2.py:1-100`
4. **Apply changes:** `acp_frontend_editor_v2.py:600-850`

### "I want to add a new pipeline phase"

1. **Understand phases:** `docs/project_info_toc.md` → Phase Implementations
2. **Pipeline orchestrator:** `openclaw_wrapper.py:1-100`
3. **Phase template:** Copy existing phase function
4. **Register phase:** Add to `run_all_phases()`

### "I want to fix deployment issues"

1. **Recent fixes:** `INFRASTRUCTURE_STABILIZATION.md`
2. **Infrastructure manager:** `docs/project_info_toc.md` → Infrastructure Manager
3. **Deployment verifier:** `deployment_verifier.py:1-200`
4. **Check paths:** `legacy/DEPLOYMENT_PATHS.md`

### "I want to modify page detection"

1. **Page inference prompt:** `prompts/01-page-inference.md`
2. **Groq service:** `groq_service.py:1-100`
3. **Page extraction:** `acp_frontend_editor_v2.py:1456-1600`

### "I want to understand the database"

1. **Migration guide:** `POSTGRESQL_MIGRATION_GUIDE.md`
2. **Connection:** `database_postgres.py:1-100`
3. **Adapter:** `database_adapter.py:1-100`
4. **Schema:** `projects_schema.sql:1-50`

---

## 📁 File Organization

```
clawd-backend/
├── docs/                          # Documentation (NEW)
│   ├── toc.md                     # This file - master index
│   └── project_info_toc.md        # Project creation detailed TOC
│
├── .agents/skills/                # Agent instructions
│   ├── project-info/SKILL.md      # Full project knowledge
│   └── spec.md                    # PRD generation
│
├── prompts/                       # AI prompts
│   ├── 01-page-inference.md
│   ├── 02-acpx-frontend-editor.md
│   ├── 03-infrastructure-task.md
│   ├── 04-ai-refinement.md
│   └── 05-build-fix.md
│
├── legacy/                        # Historical documentation
│   ├── DEPLOYMENT_PATHS.md
│   ├── DEBUGGING_REPORT.md
│   └── ...
│
└── [root markdown files]          # Various documentation
    ├── README.md
    ├── ACP_CONTROLLED_FRONTEND_EDIT.md
    ├── INFRASTRUCTURE_STABILIZATION.md
    └── ...
```

---

## 🔄 Documentation Maintenance

### When to Update This TOC

- **Adding new documentation:** Add entry to appropriate section
- **Creating new API endpoints:** Update `project_info_toc.md`
- **Adding new pipeline phases:** Update `project_info_toc.md`
- **Creating new prompts:** Add to Prompts section

### Documentation Standards

1. **Every MD should have:** Purpose, Last updated date, Related files
2. **Line numbers should be:** Approximate ranges (e.g., 100-200)
3. **File paths should be:** Relative to project root

---

## 🤖 For AI Agents

### How to Use This Documentation

1. **Start here:** Read this `toc.md` to find relevant documentation
2. **Deep dive:** Go to specific MD files for detailed information
3. **Code reference:** Use line numbers to find exact code locations
4. **Cross-reference:** Check related files mentioned in each document

### Common Agent Tasks

| Task | Primary Doc | Secondary Doc | Code Entry Point |
|------|-------------|---------------|------------------|
| Create project | `project_info_toc.md` | `projectcreationworkflow.md` | `app.py:1-100` |
| Modify ACPX | `project_info_toc.md` | `ACP_CONTROLLED_FRONTEND_EDIT.md` | `acp_frontend_editor_v2.py:1` |
| Fix deployment | `INFRASTRUCTURE_STABILIZATION.md` | `project_info_toc.md` | `infrastructure_manager.py:1` |
| Add phase | `project_info_toc.md` | `openclaw_wrapper.py` | `openclaw_wrapper.py:200-400` |

---

## 📞 Quick Links

- **Project Creation TOC:** `docs/project_info_toc.md`
- **Main README:** `README.md`
- **ACPX Guide:** `ACP_CONTROLLED_FRONTEND_EDIT.md`
- **Infrastructure Fixes:** `INFRASTRUCTURE_STABILIZATION.md`
- **Agent Skill:** `.agents/skills/project-info/SKILL.md`
