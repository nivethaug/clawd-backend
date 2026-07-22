# Scheduler Service

Centralized job scheduler for recurring tasks (crypto alerts, weather, news, web scraping, etc.).

## Architecture

```
User UI → POST /api/scheduler/projects/{id}/jobs (backend API)
  → INSERT INTO scheduler_jobs (main DB)

clawd-scheduler daemon (worker VPS, PM2)
  → polls scheduler_jobs every SCHEDULER_INTERVAL seconds
  → for each due job: spawns bwrap sandbox subprocess
    → scheduler-sandbox.sh → scheduler_runner.py
      → imports project's scheduler/executor.py
      → executor.execute_task(job)
        → fetches data (JSON API or scraping API)
        → sends notification (email, telegram, discord)
      → prints JSON result to stdout
    → bwrap process exits
  → logs result to scheduler_logs (main DB)
```

### Key design decisions

1. **One scheduler process for ALL projects** — the `clawd-scheduler` daemon polls a single `scheduler_jobs` table. No per-project scheduler processes.
2. **bwrap sandbox per job** — each `execute_task()` call runs in a fresh subprocess isolated by bwrap. Executor crashes don't take down the scheduler. Executor code (Claude-generated) cannot read platform secrets.
3. **Jobs in main DB, executors on disk** — `scheduler_jobs`/`scheduler_logs` tables live in the main `dreampilot` database. The executor code (`executor.py`) lives in each project's directory on the worker VPS filesystem.
4. **No DATABASE_URL in executor** — the sandbox passes only whitelisted env vars (PROJECT_ID, channel tokens, SMTP, BACKEND_URL). The platform DB is invisible to executor code.

## Executor isolation (bwrap sandbox)

Each `execute_task(job)` call runs inside `scripts/scheduler-sandbox.sh`:
- `--unshare-pid` — own PID namespace (can't see host processes)
- `--share-net` — localhost + internet (for API calls)
- `--bind $PROJECT_DIR` — project directory read-write
- `--ro-bind $VENV` — shared venv read-only
- `--ro-bind /usr` — system libraries read-only
- `--ro-bind /etc/ssl` — SSL certs for HTTPS
- Whitelisted env only — NO `DATABASE_URL`, NO platform tokens

**Engaged when** `EXECUTION_MODE=container` (set in `ecosystem.scheduler.json`).
When unset, falls back to in-process importlib (local dev only).

### What the sandbox blocks

| Resource | Blocked? |
|---|---|
| `/root` (platform source + secrets) | ✅ |
| `/workspaces` (other users' projects) | ✅ |
| Host PID table | ✅ |
| `DATABASE_URL` env var | ✅ |
| `os.environ` platform tokens | ✅ |
| Own project directory | ❌ (read-write) |
| Network (API calls) | ❌ (allowed) |
| Venv + system libs | ❌ (read-only) |

### Files

| File | Purpose |
|---|---|
| `scripts/scheduler-sandbox.sh` | bwrap wrapper — mounts, network, PID isolation |
| `scripts/scheduler_runner.py` | Runs inside sandbox — reads job JSON from stdin, loads executor.py, calls `execute_task()`, prints JSON result |
| `services/scheduler/execution_engine.py` | `execute_job()` → spawns sandbox subprocess with `subprocess.run(timeout=120)`. Falls back to importlib when `EXECUTION_MODE != container` |
| `services/scheduler/scheduler.py` | Daemon loop — `ThreadPoolExecutor`, polls DB, submits jobs |

### Runtime

`ecosystem.scheduler.json`:
```json
{
  "name": "clawd-scheduler",
  "script": "/root/clawd-backend/start-scheduler.sh",
  "env": {
    "EXECUTION_MODE": "container",
    "SHARED_VENV_PATH": "/root/dreampilot/dreampilotvenv",
    "SCHEDULER_ENABLED": "true",
    "SCHEDULER_INTERVAL": "10",
    "SCHEDULER_MAX_WORKERS": "10"
  }
}
```

`start-scheduler.sh` sources `.env.postgres` for DB credentials (same pattern as `start-backend.sh`).

| Variable | Default | Description |
|---|---|---|
| `SCHEDULER_ENABLED` | `true` | Enables polling loop |
| `SCHEDULER_INTERVAL` | `10` | Poll interval in seconds |
| `SCHEDULER_MAX_WORKERS` | `10` | Parallel job workers (ThreadPoolExecutor) |
| `SCHEDULER_JOB_TIMEOUT` | `120` | Per-job subprocess timeout (seconds) |
| `EXECUTION_MODE` | `local` | `container` = bwrap sandbox, `local` = importlib |

## Scheduler API auth bypass (worker VPS)

The executor's `job_manager.py` calls `/api/scheduler/*` on the backend to create/list/manage jobs. It has no user JWT.

**Solution**: IP allowlist via `SCHEDULER_INTERNAL_ALLOWLIST` env on the main VPS backend. Requests from the worker VPS IP bypass JWT auth:

```
# /root/clawd-backend/.env (main VPS)
SCHEDULER_INTERNAL_ALLOWLIST=<worker_vps_ip>
```

The bypass still enforces project-scoping — the executor can only touch its own project's jobs (via `PROJECT_ID` env).

Pair with `SCHEDULER_BACKEND_URL` so new projects get the correct URL:

```
# /root/clawd-backend/.env (main VPS)
SCHEDULER_BACKEND_URL=https://api.dreamagent.cloud
```

`env_injector.py` writes this into each project's `.env` as `BACKEND_URL`.

## Web scraping API

Scheduler executors can scrape websites via the platform scraping API — no local Chrome needed.

### Endpoint

```
POST /internal/scrape
Content-Type: application/json

{
  "url": "https://example.com",
  "extract_js": "return document.title",
  "render": false,           // false = fast HTML (default), true = Chrome CDP
  "wait_for_selector": null,  // CSS selector to wait for
  "wait_ms": 2000,           // additional wait for JS rendering
  "timeout": 15              // seconds
}
```

**Response**:
```json
{"success": true, "data": "Example Domain", "rendered": false}
```

### Tiered scraping

| Tier | Method | Speed | RAM | When |
|---|---|---|---|---|
| 1. JSON API | `api_client.get_crypto_price()` etc. | ~200ms | 0MB | CoinGecko, weather, news |
| 2. Fast HTML | `api_client.fetch_page(url, extract_js)` | ~200ms | ~5MB | Static pages (news, products) |
| 3. Chrome CDP | `web_scraper.scrape_url(ScrapeConfig(scroll=True))` | ~2-5s | ~50MB/tab | JS-rendered SPAs, scroll |

**`render=false`** (default): `httpx` fetches HTML → BeautifulSoup parses → CSS selectors applied. No Chrome needed.

**`render=true`**: Chrome Headless Shell renders the page via CDP (websocket). JS executes fully. Each request gets its own isolated tab (concurrent-safe, capped at 10 tabs).

### Template usage

```python
from services import api_client

# Tier 2: fast HTML scrape
result = api_client.fetch_page("https://example.com", "return document.title")

# Tier 3: full Chrome render (for JS-heavy pages)
from services.web_scraper import scrape_url, ScrapeConfig
result = scrape_url(ScrapeConfig(
    url="https://example.com",
    scroll=True,
    fields={"title": "h1", "price": ".price"}
))
```

**Chrome runs on the main VPS** as a systemd service (`chrome-headless-shell` on port 9222). The scraping API reaches it via `127.0.0.1:9222` (CDP over websocket). Callers (bwrap sandboxes, Docker containers) reach the API via `BACKEND_URL/internal/scrape`.

### Files

| File | Purpose |
|---|---|
| `services/cdp_scraper.py` | Async CDP-over-websocket client (opens tab, navigates, evaluates JS, closes tab) |
| `app.py POST /internal/scrape` | Endpoint — IP-guarded, branches on `render` flag |
| `templates/*/services/api_client.py` | `fetch_page()` helper — calls `/internal/scrape` with `render=false` |
| `templates/*/services/web_scraper.py` | `scrape_url()` — calls `/internal/scrape`, auto-selects render mode |

## Database tables

| Table | Description |
|---|---|
| `scheduler_jobs` | Job definitions, schedule, status, payload, last/next run |
| `scheduler_logs` | Per-run success/failure log entries |

Both live in the main `dreampilot` database. Written by:
- **Backend API** (`api/scheduler_router.py`) — job CRUD via REST
- **Scheduler daemon** (`services/scheduler/scheduler.py`) — job execution + logging
- **NOT by executors** — the sandboxed executor has no DB access

## Related

- [container_isolation.md](./container_isolation.md) — Docker + bwrap isolation overview
- [worker_vps_setup.md](./worker_vps_setup.md) — Worker VPS deployment guide
- [project_creation.md](./project_creation.md) — Project creation pipeline
