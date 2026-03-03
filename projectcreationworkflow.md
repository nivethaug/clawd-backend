# DreamPilot Project Creation Workflow

**Version:** 1.0
**Last Updated:** 2026-03-03
**Total Phases:** 9

---

## Overview

DreamPilot website projects follow a **9-phase initialization workflow** that provisions complete infrastructure, frontend, backend, database, and AI refinement in 30-45 seconds.

**Entry Point:** `POST /projects` API endpoint
**Backend:** FastAPI on port 8002
**Orchestration:** `openclaw_wrapper.py` + `infrastructure_manager.py`

---

## Phase 1: Analyze Project (2 seconds)

**Purpose:** Template selection via Groq LLM

**Actions:**
1. Read project name and description
2. Call Groq API with project details
3. Select best template from 7 available options:
   - `saas` - SaaS dashboard template
   - `ecommerce` - E-commerce template
   - `blog` - Blog template
   - `landing` - Landing page template
   - `portfolio` - Portfolio template
   - `dashboard` - Analytics dashboard
   - `crm` - CRM template

**Output:**
- `template_id` (e.g., "saas")
- `template_repo` (GitHub URL)
- `template_features` (list of features)

**Dependencies:** Groq API (fast, requires internet)

---

## Phase 2: Template Setup (5 seconds)

**Purpose:** Clone template and create project structure

**Actions:**
1. Clone selected template from GitHub
2. Create project directory: `/root/dreampilot/projects/website/{id}_{name}_{timestamp}/`
3. Verify frontend exists
4. Verify backend exists

**Directory Structure:**
```
{id}_{name}_{timestamp}/
├── frontend/           # React + Vite frontend
├── backend/            # FastAPI backend
├── database/           # Database schema/migrations
├── .env               # Environment variables
└── project.json        # Metadata
```

**Output:**
- Frontend template cloned
- Backend structure created
- `project.json` metadata saved

---

## Phase 3: Database Provisioning (5-10 seconds)

**Purpose:** Create isolated PostgreSQL database for each project

**Actions:**
1. Create PostgreSQL database: `{project_name}_db`
2. Create database user: `{project_name}_user`
3. Generate secure password
4. Grant privileges on database
5. Update backend `.env` with connection details

**Database Details:**
- **Host:** localhost
- **Port:** 5432
- **Database:** `{project_name}_db`
- **User:** `{project_name}_user`
- **Password:** Auto-generated (stored in `.env`)

**Master DB Protection:**
- `dreampilot` database is protected (never deleted)
- Project databases follow pattern: `{project_name}_db`
- Validation ensures master DB is never targeted

**Output:**
- PostgreSQL database created
- Database user created with privileges
- Backend `.env` configured with connection string

---

## Phase 4: Port Allocation (instant)

**Purpose:** Assign unique ports for frontend and backend

**Port Ranges:**
- **Frontend:** 3000-4000
- **Backend:** 8010-9000

**Allocation Logic:**
- Scan existing PM2 processes
- Find first available port in range
- Track allocation to prevent conflicts

**Example:**
```
Frontend: 3007
Backend: 8016
```

**Output:**
- `project.json` updated with allocated ports
- Frontend and backend ports assigned

---

## Phase 5: Service Setup (5-10 seconds)

**Purpose:** Start PM2 services for frontend and backend

**Actions:**

### 5.1 Backend Service
1. Create virtual environment (shared: `/root/clawd-backend/venv`)
2. Install dependencies: `uvicorn`, `fastapi`, `psycopg2`
3. Create PM2 config for backend
4. Start backend service with `uvicorn`
5. Verify health endpoint: `/health`

**Backend Details:**
- **Command:** `uvicorn backend.main:app --host 0.0.0.0 --port {backend_port}`
- **PM2 Name:** `{project_name}-backend`
- **Health Check:** GET `/health`

### 5.2 Frontend Service
1. Build frontend for production: `npm run build`
2. Create PM2 config for frontend
3. Start frontend service with `serve` package
4. Use `-s` flag for SPA routing support

**Frontend Details:**
- **Command:** `npx serve -s dist -l {frontend_port}`
- **PM2 Name:** `{project_name}-frontend`
- **Build Output:** `dist/` directory with optimized assets
- **SPA Routing:** `-s` flag serves `index.html` for all 404s

**Output:**
- Backend service running on allocated port
- Frontend service running on allocated port
- Both services verified as healthy

---

## Phase 6: Nginx Routing (5-10 seconds)

**Purpose:** Configure domain routing with SSL

**Actions:**

### 6.1 Nginx Configuration
1. Create nginx config: `/etc/nginx/sites-available/{domain}.conf`
2. Configure frontend proxy to frontend port
3. Configure backend proxy to backend port
4. Enable config with symlink: `/etc/nginx/sites-enabled/{domain}.conf`

**Nginx Config Structure:**
```nginx
# Frontend: {project_name}.dreambigwithai.com
server {
    listen 80;
    server_name {project_name}.dreambigwithai.com;

    location / {
        proxy_pass http://127.0.0.1:{frontend_port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# Backend: {project_name}-api.dreambigwithai.com
server {
    listen 80;
    server_name {project_name}-api.dreambigwithai.com;

    location / {
        proxy_pass http://127.0.0.1:{backend_port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
    }
}
```

### 6.2 SSL Certificate Generation
1. Run certbot for frontend domain
2. Run certbot for backend domain
3. Configure SSL for HTTPS

**SSL Details:**
- **Frontend:** `https://{project_name}.dreambigwithai.com`
- **Backend:** `https://{project_name}-api.dreambigwithai.com`
- **Certificates:** Stored in `/etc/letsencrypt/live/`

### 6.3 Nginx Reload
1. Test configuration: `nginx -t`
2. Reload nginx: `systemctl reload nginx`

**Server Names Hash:**
- `server_names_hash_bucket_size` set to 128
- Prevents issues with many subdomains

**Output:**
- Nginx config created and enabled
- Domains routing correctly
- SSL certificates generated (HTTP-only if certbot fails)

---

## Phase 7: DNS Provisioning (5-10 seconds)

**Purpose:** Create DNS A records for subdomains

**Actions:**
1. Check Hostinger DNS for existing records
2. Create A record for frontend: `{project_name}.dreambigwithai.com` → server IP
3. Create A record for backend: `{project_name}-api.dreambigwithai.com` → server IP
4. Log DNS changes

**DNS Details:**
- **Provider:** Hostinger
- **Type:** A records
- **TTL:** 300 seconds
- **Target IP:** 195.200.14.37 (DreamPilot server)

**DNS Propagation:**
- Typically 5-60 minutes
- Records may take time to become active

**Output:**
- Frontend DNS record created
- Backend DNS record created
- DNS metadata saved in `project.json`

---

## Phase 8: AI-Driven Frontend Refinement (5-10 minutes)

**Purpose:** Customize frontend using OpenClaw AI agent sessions

**Actions:**
1. Update project status to `ai_provisioning`
2. Spawn OpenClaw sub-agent session
3. Execute `phase8_openclaw.py` script
4. Agent reads project description and branding
5. Agent modifies frontend files:
   - Update navigation menu
   - Modify hero section
   - Remove demo content
   - Adjust UI terminology to match project domain
6. Verify build succeeds: `npm run build`
7. Restart frontend PM2 service

**AI Agent Details:**
- **Runtime:** OpenClaw session (not CrewAI)
- **Script:** `phase8_openclaw.py`
- **Prompt:** Built from project name and description
- **Timeout:** 30 minutes

**AI Tasks:**
- Understand project context from `project_name` and `description`
- Adapt pages intelligently based on project needs
- Rename components to reflect project domain
- Update routes logically if navigation changes
- Inject meaningful, realistic content
- Keep project minimal but real

**AI Restrictions:**
- Do NOT over-generate pages not implied by project
- Do NOT rewrite entire application blindly
- Do NOT delete core framework files
- Do NOT break the build process
- Do NOT modify backend files
- Do NOT modify infrastructure files

**Verification:**
- Build must succeed: `npm run build`
- All routes must work
- SPA navigation must function

**Output:**
- Frontend customized to project needs
- Build verified successful
- Frontend service restarted
- Project status updated to `ready` (if Phase 9 fails, still continues)

---

## Phase 9: ACP Controlled Frontend Editor (30-60 seconds)

**Purpose:** Integrate ACP (Agent Client Protocol) as final phase

**Actions:**
1. Initialize `ACPFrontendEditor` directly (no HTTP API)
2. Create ACP documentation file: `ACP_README.md`
3. Validate file paths:
   - Whitelist: Only `frontend/src/` allowed
   - Forbidden: Backend files protected
   - Forbidden: `components/ui/` protected
4. Create snapshot before modifications
5. Apply changes with ACP validation
6. Run build gate: `npm install` + `npm run build`
7. Create mutation log: `.acp_mutation_log.json`

**ACP Integration:**
- **Architecture:** Direct module import (no separate HTTP endpoint)
- **Phase:** Runs as final step (Phase 9/9)
- **Files Modified:** 1 (ACP_README.md)
- **Execution ID:** `acp_{random-12-chars}`

**ACP Safety Features:**
- ✅ Path validation (whitelist `frontend/src/`, forbid backend, forbid `components/ui/`)
- ✅ File limit (max 4 new files per execution)
- ✅ Snapshot system (backup before modifications)
- ✅ Automatic rollback (restore on validation or build failure)
- ✅ Build gate (`npm run build` must succeed)
- ✅ Mutation logging (full history tracked in `.acp_mutation_log.json`)

**ACP_README.md Contents:**
- ACP introduction and integration status
- Safety features list
- Project status (name, ID, completion time)
- Usage instructions for future ACP refinements

**Mutation Log Contents:**
- Execution ID and timestamp
- Files added/modified/removed
- Build result (success/failure, output)
- Rollback status (rolled_back, reason)
- Final status (success/failed)

**Output:**
- ACP documentation created
- Mutation log created
- Build verified successful
- Project status updated to `ready`

---

## Verification (5-10 seconds)

**Purpose:** Confirm all infrastructure is working

**Actions:**
1. Verify frontend port is listening
2. Verify backend port is listening
3. Check backend health endpoint
4. Verify overall deployment status

**Health Checks:**
- **Frontend:** `curl http://localhost:{frontend_port}/` → 200 OK
- **Backend:** `curl http://localhost:{backend_port}/health` → 200 OK
- **PM2:** Both services showing as "online"

**Output:**
- Frontend verified: ✅
- Backend verified: ✅
- Overall deployment: ✅

---

## Final Status Update

**Action:** Update project status in database

**Status Transitions:**
```
creating → infrastructure_provisioning → ai_provisioning → ready
                                       ↓
                                    failed (if any phase fails)
```

**Database Update:**
- PostgreSQL: `UPDATE projects SET status = 'ready' WHERE id = ?`
- Commit transaction
- Log status change

---

## Project Metadata

**Location:** `/root/dreampilot/projects/website/{id}_{name}_{timestamp}/project.json`

**Contents:**
```json
{
  "project_name": "Project Name",
  "ports": {
    "frontend": 3007,
    "backend": 8016
  },
  "domains": {
    "frontend": "project.dreambigwithai.com",
    "backend": "project-api.dreambigwithai.com"
  },
  "dns": {
    "frontend": true,
    "backend": true,
    "frontend_exists": false,
    "backend_exists": false,
    "skipped": false
  },
  "database": {
    "name": "Project Name_db",
    "user": "Project Name_user"
  },
  "service_name": "Project Name-backend",
  "status": "ready",
  "frontend_app_name": "Project Name-frontend"
}
```

---

## PM2 Process List

**Backend Service:**
- **Name:** `{project_name}-backend`
- **Command:** `uvicorn backend.main:app --host 0.0.0.0 --port {backend_port}`
- **Environment:** `venv` + `.env`
- **Logs:** `/root/dreampilot/projects/website/{id}_{name}_{timestamp}/backend/logs/`

**Frontend Service:**
- **Name:** `{project_name}-frontend`
- **Command:** `npx serve -s dist -l {frontend_port}`
- **Environment:** `PROJECT_NAME={project_name}`
- **Logs:** `/root/dreampilot/projects/website/{id}_{name}_{timestamp}/frontend/logs/`

---

## Error Handling

### Phase Failures

**If Phase 1-7 Fails:**
1. Rollback partial infrastructure
2. Update project status to `failed`
3. Log error details
4. Return error to API caller

**If Phase 8 Fails:**
1. Log error
2. Allow project to complete (Phase 9 still runs)
3. Warning: "AI frontend refinement may have issues"

**If Phase 9 Fails:**
1. Rollback snapshot (restore original frontend)
2. Log error
3. Allow project to complete (marked as ready)
4. Warning: "ACP integration failed, but project is functional"

### Database Errors

**Master DB Protection:**
- Validates database name before deletion
- Blocks any attempt to drop `dreampilot` database
- Error: "CRITICAL: Attempt to delete master database blocked!"

**Connection Errors:**
- Retries connection 3 times
- Fallback to SQLite if PostgreSQL unavailable (development mode)

### DNS Errors

**Certbot Failures:**
- Log warning: "SSL certificate generation failed, continuing with HTTP-only"
- Continue with HTTP routing (no SSL)
- No retry attempt

---

## Security Features

### Path Validation (Phase 8 & 9)
- Frontend changes limited to `frontend/src/`
- Backend files protected (read-only)
- `components/ui/` protected (shadcn components)
- Path traversal protection (symlink validation)

### Database Isolation
- Each project gets separate database
- Separate database user per project
- No cross-project data access
- Master DB protected from deletion

### Service Isolation
- Separate PM2 processes per project
- Separate ports per project
- No shared resources between projects

### DNS Validation
- Domain format validation (lowercase, alphanumeric, hyphens)
- DNS record existence check before creation
- Prevents duplicate subdomains

---

## Performance Metrics

**Total Time:** 30-45 seconds (excluding Phase 8 AI refinement)

**Breakdown:**
- Phase 1 (Analyze): 2 seconds
- Phase 2 (Template): 5 seconds
- Phase 3 (Database): 5-10 seconds
- Phase 4 (Ports): < 1 second
- Phase 5 (Services): 5-10 seconds
- Phase 6 (Nginx): 5-10 seconds
- Phase 7 (DNS): 5-10 seconds
- Phase 8 (AI): 5-10 minutes
- Phase 9 (ACP): 30-60 seconds

**Parallel Operations:**
- Frontend and backend services start simultaneously
- DNS checks run in parallel
- Build verification runs independently

---

## Monitoring & Logging

### PM2 Logs
- **Backend:** `/path/to/project/backend/logs/out.log` and `error.log`
- **Frontend:** `/path/to/project/frontend/logs/out.log` and `error.log`
- **Access:** Both services log HTTP requests

### Application Logs
- **Backend:** `uvicorn` logs to PM2 output
- **Frontend:** `serve` package logs HTTP requests
- **OpenClaw Wrapper:** Logs all phase progress to backend logs

### ACP Mutation Logs
- **Location:** `/path/to/frontend/.acp_mutation_log.json`
- **Contents:** Execution history, files changed, build results, rollback status

### Database Logs
- **PostgreSQL:** `/var/log/postgresql/` (if configured)
- **Application:** Database queries logged in backend logs

---

## API Endpoints

### Project Creation
**Endpoint:** `POST /projects`
**Request:**
```json
{
  "name": "Project Name",
  "domain": "subdomain",
  "description": "Project description",
  "user_id": 1,
  "typeId": 1
}
```

**Response:**
```json
{
  "id": 123,
  "name": "Project Name",
  "domain": "project-name",
  "project_path": "/root/dreampilot/projects/website/...",
  "status": "creating",
  "template_id": "saas",
  "created_at": "2026-03-03T00:00:00.000000"
}
```

### Project Status
**Endpoint:** `GET /projects/{id}/status`
**Response:**
```json
{
  "id": 123,
  "name": "Project Name",
  "status": "ready",
  "created_at": "2026-03-03T00:00:00.000000",
  "updated_at": "2026-03-03T00:05:00.000000"
}
```

### Project Deletion
**Endpoint:** `DELETE /projects/{id}?force=false`
**Response:**
```json
{
  "status": "deleted",
  "message": "Project deleted",
  "cleanup": {
    "infrastructure": {
      "steps": {
        "pm2": {...},
        "nginx": {...},
        "ssl": {...},
        "dns": {...},
        "database": {...},
        "directory": {...}
      }
    }
  }
}
```

---

## Maintenance

### Routine Checks

**Daily:**
- Verify all PM2 services are online
- Check disk space on `/root/dreampilot/`
- Review error logs for issues

**Weekly:**
- Clean up old project backups
- Verify PostgreSQL backups
- Check nginx configuration for syntax errors

**Monthly:**
- Review DNS propagation issues
- Update SSL certificates (auto-renewal usually handles this)
- Audit project directories for orphaned projects

### Scaling Considerations

**Port Exhaustion:**
- Current range: 3000-4000 (1000 ports), 8010-9000 (990 ports)
- Monitor port usage
- Extend ranges if needed

**Database Performance:**
- Monitor PostgreSQL connection pool size
- Add connection pooling if needed (PgBouncer)
- Implement database indexing for large projects

**Nginx Performance:**
- Monitor `server_names_hash_bucket_size` (currently 128)
- Increase to 256 if many subdomains
- Add caching headers for static assets

---

## Troubleshooting

### Common Issues

**Frontend Not Loading:**
1. Check PM2 status: `pm2 list`
2. Check frontend logs: `pm2 logs {project_name}-frontend`
3. Verify nginx config: `nginx -t`
4. Check port is listening: `netstat -tulpn | grep {frontend_port}`

**Backend Not Responding:**
1. Check PM2 status: `pm2 list`
2. Check backend logs: `pm2 logs {project_name}-backend`
3. Verify database connection: Check `.env` file
4. Test health endpoint: `curl http://localhost:{backend_port}/health`

**DNS Not Resolving:**
1. Check DNS records: Hostinger hPanel
2. Verify A record points to correct IP
3. Wait for DNS propagation (5-60 minutes)
4. Test with `nslookup {domain}`

**Phase 8 AI Refinement Issues:**
1. Check OpenClaw session status
2. Verify frontend build: `npm run build`
3. Review `phase8_openclaw.py` logs
4. Manual frontend edits if AI fails

**Phase 9 ACP Issues:**
1. Check mutation log: `.acp_mutation_log.json`
2. Verify snapshot rollback occurred
3. Check build output in log
4. Manual ACP_README.md creation if needed

### Debug Commands

**Check All Services:**
```bash
pm2 list
pm2 logs --lines 100 --nostream
```

**Verify Infrastructure:**
```bash
cd /root/dreampilot/projects/website/{id}_{name}_{timestamp}
cat project.json
```

**Test Frontend:**
```bash
curl -I http://localhost:{frontend_port}/
curl -I http://{project_name}.dreambigwithai.com/
```

**Test Backend:**
```bash
curl -I http://localhost:{backend_port}/health
curl -I http://{project_name}-api.dreambigwithai.com/health
```

**Check DNS:**
```bash
nslookup {project_name}.dreambigwithai.com
dig A {project_name}.dreambigwithai.com
```

---

## Future Enhancements

### Potential Improvements

**Phase 8 AI Refinement:**
- Add project-specific prompts for better customization
- Implement incremental refinement (multiple AI passes)
- Add user review step before accepting changes
- Fix syntax error issues in `App.tsx`

**Phase 9 ACP Integration:**
- Add CLI interface for manual ACP refinements
- Implement rollback to specific mutation point
- Add visual diff preview for changes
- Support for multiple simultaneous ACP sessions

**Infrastructure:**
- Implement containerization (Docker) for better isolation
- Add load balancing for high-traffic projects
- Implement automatic scaling based on traffic
- Add monitoring and alerting system

**Security:**
- Implement rate limiting on API endpoints
- Add JWT authentication for project management
- Implement audit logging for all changes
- Add CSRF protection for forms

---

## References

**Key Files:**
- `/root/clawd-backend/openclaw_wrapper.py` - Phase orchestration
- `/root/clawd-backend/infrastructure_manager.py` - Infrastructure provisioning
- `/root/clawd-backend/phase8_openclaw.py` - AI frontend refinement
- `/root/clawd-backend/acp_frontend_editor.py` - ACP controlled editing
- `/root/clawd-backend/app.py` - API endpoints

**Configuration:**
- `/root/clawd-backend/.env` - Environment variables
- `/etc/nginx/nginx.conf` - Nginx global configuration
- `/root/clawd-backend/template-selector.json` - Template registry

**Documentation:**
- `/root/dreampilot/website/frontend/strict-agent-rulebook.md`
- `/root/dreampilot/website/frontend/create-project-protocol.md`
- `/root/dreampilot/website/backend/rule.md`

---

**Document Maintained By:** DreamPilot Team
**Last Updated:** 2026-03-03
**Version:** 1.0
