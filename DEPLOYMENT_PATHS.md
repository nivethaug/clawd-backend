# Backend Deployment Paths & Architecture

## Overview

This document explains how we maintain separate deployments for **main** (production on port 8002) and **feature branches** (development on port 8001) for the FastAPI backend.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────┐
│  SOURCE CODE (/root/clawd-backend/)           │
│                                              │
│  ├─ main branch (stable)                 │
│  │  ├─ app.py                                    │
│  │  ├─ database.py                                │
│  │  ├─ chat_handlers.py                            │
│  │  ├─ project_manager.py                          │
│  │  ├─ image_handler.py                            │
│  │  ├─ file_utils.py                               │
│  │  └─ start-backend.sh                            │
│                                              │
│  └─ feature/* branches (development)       │
│     ├─ (modified Python files)                     │
│     └─ start-backend.sh (may use port 8001)      │
└──────────────────┬──────────────────────────────────┘
                   │
                   │ (No build step - Python runs in place)
                   ▼
┌─────────────────────────────────────────────────────┐
│  RUNNING APPLICATION (Python/FastAPI)         │
│  Serves source code directly from .py files       │
│  Uses: Uvicorn ASGI server                   │
│  Database: SQLite (clawdbot_adapter.db)      │
└──────────────────┬──────────────────────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
        │ PM2 Instance 1      │ PM2 Instance 2 (Optional)
        │                      │
        ▼                      ▼
┌──────────────┐      ┌─────────────────────┐
│ Port 8002    │      │ Port 8001           │
│ Production   │      │ Development           │
│              │      │                      │
│ Server: Uvicorn │      │ Server: Uvicorn       │
│ Process: main│      │ Process: feature/*   │
│ Branch: main  │      │ Branch: feature/*     │
│ Database:    │      │ Database:            │
│ clawdbot_     │      │ clawdbot_            │
│ adapter.db   │      │ adapter.db           │
│              │      │ (or separate DB)      │
│              │      │                      │
│ URL:          │      │ URL:                 │
│ http://       │      │ http://              │
│ localhost:    │      │ localhost:           │
│ 8002         │      │ 8001                 │
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
| **Database** | `/root/clawd-backend/clawdbot_adapter.db` |
| **Environment Variable** | `DB_PATH=/root/clawd-backend/clawdbot_adapter.db` |
| **Public URL** | http://195.200.14.37:8002 |

**Startup Commands:**
```bash
# Switch to main branch
cd /root/clawd-backend
git checkout main

# Restart PM2 process
pm2 restart clawd-backend

# Server runs on port 8002
```

**PM2 Configuration:**
```json
{
  "name": "clawd-backend",
  "script": "/root/clawd-backend/venv/bin/uvicorn",
  "args": "app:app --host 0.0.0.0 --port 8002",
  "cwd": "/root/clawd-backend",
  "env": {
    "DB_PATH": "/root/clawd-backend/clawdbot_adapter.db"
  }
}
```

**Startup Script:**
```bash
#!/bin/bash
# /root/clawd-backend/start-backend.sh

cd /root/clawd-backend
source venv/bin/activate
export DB_PATH="/root/clawd-backend/clawdbot_adapter.db"
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
| **Database** | `/root/clawd-backend/clawdbot_adapter.db` (shared) OR separate |
| **Environment Variable** | `DB_PATH=/root/clawd-backend/clawdbot_adapter.db` |
| **Public URL** | http://195.200.14.37:8001 (if running) |

**Startup Commands:**
```bash
# Switch to feature branch
cd /root/clawd-backend
git checkout feature/my-feature

# Option 1: Use port 8001 with separate PM2 process
pm2 start clawd-backend-dev -- --name "clawd-backend-dev" \
  --interpreter /root/clawd-backend/venv/bin/python \
  -- /root/clawd-backend/start-backend-dev.sh

# Option 2: Test locally with uvicorn directly
source venv/bin/activate
uvicorn app:app --host 0.0.0.0 --port 8001 --reload
```

**Optional Dev PM2 Configuration:**
```json
{
  "name": "clawd-backend-dev",
  "script": "/root/clawd-backend/venv/bin/uvicorn",
  "args": "app:app --host 0.0.0.0 --port 8001",
  "cwd": "/root/clawd-backend",
  "env": {
    "DB_PATH": "/root/clawd-backend/clawdbot_adapter.db"
  }
}
```

**Optional Dev Startup Script:**
```bash
#!/bin/bash
# /root/clawd-backend/start-backend-dev.sh

cd /root/clawd-backend
source venv/bin/activate
export DB_PATH="/root/clawd-backend/clawdbot_adapter.db"
exec venv/bin/uvicorn app:app --host 0.0.0.0 --port 8001 --reload
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

### Separate PM2 Instances (Port Separation)

| Instance | Port | Branch | Use Case |
|----------|-------|---------|-----------|
| `clawd-backend` | 8002 | `main` | Production (always running) |
| `clawd-backend-dev` | 8001 | `feature/*` | Development (optional, create when needed) |

**Port Isolation:**
- Production and development run simultaneously
- Different ports prevent conflicts
- Same code base, different running instances

---

## Deployment Rules

### Rule 1: Main Branch → Port 8002 Only

❌ **Never** run feature branches on port 8002
✅ Only `main` branch runs on port 8002
✅ Used by production frontend
✅ Production database

### Rule 2: Feature Branches → Port 8001 Only

❌ **Never** run main branch on port 8001
✅ Only feature/fix/dev branches use port 8001
✅ Used for testing API changes
✅ Can use same or separate database

### Rule 3: Branch Naming Convention

| Branch Type | Pattern | Port |
|-------------|----------|-------|
| **Feature** | `feature/<description>` | 8001 |
| **Fix** | `fix/<description>` | 8001 |
| **Development** | `development` | 8001 |
| **Main** | `main` | 8002 |

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
  -- /root/clawd-backend/venv/bin/uvicorn \
  -- app:app --host 0.0.0.0 --port 8001

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
pm2 start clawd-backend-dev -- ...
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

---

## File Permissions

### Production (Port 8002)
```bash
# PM2 runs as root user
# Source code: /root/clawd-backend/
# Database: /root/clawd-backend/clawdbot_adapter.db
# Virtual environment: /root/clawd-backend/venv/
```

### Development (Port 8001)
```bash
# Same permissions as production
# If separate database needed, ensure proper ownership
```

---

## Database Considerations

### Shared Database Approach

Both production and development can use the **same database**:
```
/root/clawd-backend/clawdbot_adapter.db
```

**Pros:**
- ✅ Tests use real production schema
- ✅ Can test with real data (careful!)
- ✅ Simple setup

**Cons:**
- ⚠️ Development can corrupt production data
- ⚠️ Not isolated testing environment

### Separate Database Approach (Recommended for Testing)

For safer testing, use a separate database:
```bash
# Production database
/root/clawd-backend/clawdbot_adapter.db

# Development database (optional)
/root/clawd-backend/clawdbot_adapter_dev.db

# Set in startup script
export DB_PATH="/root/clawd-backend/clawdbot_adapter_dev.db"
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
- DELETE /projects/{id}
- GET /projects/{id}/sessions
- POST /projects/{id}/sessions
- GET /sessions/{id}/messages
- POST /chat
- GET /health
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
| **Database** | clawdbot_adapter.db | Same or separate |
| **Public URL** | http://195.200.14.37:8002/ | http://195.200.14.37:8001/ |

---

## Troubleshooting

### Port Already in Use

```bash
# Check what's using the port
lsof -i :8002
lsof -i :8001

# Kill process if needed
pm2 delete clawd-backend
# Then restart
pm2 start /root/clawd-backend/ecosystem.backend.json
```

### Backend Not Responding

```bash
# Check PM2 status
pm2 status clawd-backend

# Check logs
pm2 logs clawd-backend --lines 50

# Check if port is listening
netstat -tlnp | grep 8002
```

### Database Locked

```bash
# Check if database is locked
ls -l /root/clawd-backend/clawdbot_adapter.db

# Check if multiple processes are running
ps aux | grep uvicorn

# Restart backend to release lock
pm2 restart clawd-backend
```

---

**Last Updated:** 2026-02-04

---

## Recent Changes

### Session Handling Fix (2026-02-04)

**Issue:** Session loss when `stream=false` with images

**Problem:**
- `stream=true` → Session correctly maintained
- `stream=false` with images → New session created per message
- OpenClaw gateway wasn't recognizing session due to wrong field

**Root Cause:**
`image_handler.py` was sending `"session_key"` field instead of `"user"` field to OpenClaw API. OpenClaw uses `"user"` field for session management, not `"session_key"`.

**Fix Applied:**
File: `image_handler.py`
```python
# Before (wrong):
request_body = {
    "model": "agent:main",
    "session_key": session_key,  # ← Incorrect field
    "messages": [...]
}

# After (correct):
user_field = f"adapter-session-{session_key}"
request_body = {
    "model": "agent:main",
    "user": user_field,  # ← Correct field for session continuity
    "messages": [...]
}
```

**Reference:** `SESSION_KEY_IMPLEMENTATION.md` (authoritative specification)

**Testing:**
- Development environment: Port 8001 (feature branch `fix/session-handling-stream-false`)
- Frontend: Port 3001 (mapped to backend 8001)
- Verified: Messages now maintain session across multiple requests
- Log confirmation: `[CHAT] Sending to OpenClaw with 'user' field: adapter-session-{uuid}`

**Impact:**
- All chat paths now use consistent session handling
- Memory/context persists correctly across messages
- No breaking API changes introduced
