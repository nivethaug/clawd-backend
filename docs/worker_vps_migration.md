# Worker VPS Migration Plan

> Goal: move Claude Code, ACPX, project creation, and selected-session execution away from the public DreamAgent API VPS without breaking current user flows.
>
> Status: planning/runbook.

## Recommended Target Architecture

Keep the main VPS as the only public product API. Move long-running and user-code execution to a private worker VPS.

| Main VPS | Worker VPS |
| --- | --- |
| `clawd-backend` FastAPI public API | `clawd-session-chat-worker` |
| Frontend/static hosting | `clawd-project-creation-worker` |
| Auth, users, billing, webhooks | Claude Code / ACPX / OpenClaw execution |
| Telegram/Discord/Slack webhook endpoints | Build/publish execution |
| Project/session APIs and status/chunk reads | Project file workspace |
| Postgres primary, or managed Postgres endpoint | Optional `clawd-scheduler` if scheduler executes project code |

The frontend and bot webhooks should continue calling `api.dreamagent.cloud`. The worker VPS should pull work from durable DB tables and write results back. Users should never talk to the worker directly.

## Why This Is Low-Risk

The current durable run model already supports this split:

- `/chat` and selected-session chat enqueue or track session chat runs.
- Project creation is represented through durable project creation runs.
- Status/chunk APIs read persisted state instead of relying only on FastAPI memory.
- Session locks and processing flags are DB-backed.

This means the main API can validate requests, ownership, credits, and locks, while the worker VPS performs the dangerous/long-running work.

## Communication Model

Use database-backed pull execution first. Avoid API-to-worker HTTP for long-running work.

1. User calls main API.
2. Main API validates auth, ownership, credits, and lock rules.
3. Main API inserts or updates a durable run row.
4. Worker VPS polls and claims queued work with DB row locks.
5. Worker runs Claude Code / ACPX / OpenClaw.
6. Worker writes chunks, status, final messages, token usage, and commit metadata to DB.
7. Main API serves status/chunks/results to web, Telegram, Discord, and Slack.

Direct worker API calls should be reserved for future internal-only controls, such as health, drain, or admin diagnostics.

## Phase 0: Preconditions

Before moving traffic, confirm:

- `clawd-session-chat-worker` runs independently of `clawd-backend`.
- `clawd-project-creation-worker` runs independently of `clawd-backend`.
- Backend restart does not kill active worker jobs.
- Project creation and session chat run state is persisted in DB.
- Billing/token finalization is handled once per completed run.
- `has_writes=true` still triggers commit/push after worker completion.
- Stale run cleanup unlocks interrupted sessions.
- `/chat/status`, `/chat/chunks`, and project creation status read DB state.

## Phase 1: Prepare the Worker VPS

Provision a new VPS with:

- Same OS family and Python version as the current backend VPS.
- Node.js, pnpm/npm, git, PM2, Claude Code/ACPX dependencies.
- Access to the same model/provider environment variables required by Claude/OpenClaw.
- Access to Postgres through a private network, VPN, SSH tunnel, or IP allowlist.
- Access to GitHub/Hostinger/domain provider only if the worker will build, publish, and deploy.
- Project workspace storage with enough disk for generated projects and node modules.

Recommended filesystem paths:

```text
/root/clawd-backend
/root/dreampilot/projects
/root/clawd-projects
/root/.claude
```

Keep paths compatible where possible. If paths must change, add env variables rather than hardcoding path rewrites.

## Phase 2: Split Environment Configuration

Main VPS should keep public/API-facing env:

```env
INSTANCE_ROLE=api
ENABLE_PUBLIC_API=true
ENABLE_WORKERS=false
DATABASE_URL=...
CLAWDBOT_TOKEN=...
LEMONSQUEEZY_...
TELEGRAM_...
DISCORD_CONTROL_...
SLACK_...
SENTRY_DSN=...
```

Worker VPS should use worker-focused env:

```env
INSTANCE_ROLE=worker
ENABLE_PUBLIC_API=false
ENABLE_WORKERS=true
DATABASE_URL=...
DB_HOST=...
DB_PORT=...
DB_NAME=...
DB_USER=...
DB_PASSWORD=...

PROJECTS_ROOT=/root/dreampilot/projects
CLAWD_PROJECTS_ROOT=/root/clawd-projects

ANTHROPIC_API_KEY=...
OPENROUTER_API_KEY=...
ZAI_API_KEY=...
HOSTINGER_API_TOKEN=...
GITHUB_TOKEN=...

SENTRY_DSN=...
SENTRY_ENVIRONMENT=production
SENTRY_RELEASE=...
```

Do not copy public webhook secrets to the worker unless a worker process genuinely needs them.

## Phase 3: Network and Security Controls

Recommended firewall posture:

- Main VPS public inbound: `80`, `443`, SSH from admin IPs only.
- Worker VPS public inbound: SSH from admin IPs only.
- Worker VPS should not expose FastAPI publicly.
- Postgres should allow connections only from main VPS and worker VPS private IPs.
- Provider tokens should exist only on the process that needs them.

If using an internal worker API later:

```env
WORKER_API_URL=https://worker-api.internal.dreamagent.cloud
WORKER_INTERNAL_TOKEN=...
```

Protect it with:

- Firewall allowlist from main VPS only.
- Internal bearer token.
- No browser CORS access.
- No public DNS unless necessary.

## Phase 4: Deploy Worker Code

On worker VPS:

```bash
cd /root/clawd-backend
git pull
source venv/bin/activate
pip install -r requirements.txt
python -m py_compile session_chat_worker.py project_creation_worker.py services/project_creation_runs.py
```

Start only workers:

```bash
pm2 start session_chat_worker.py --name clawd-session-chat-worker --interpreter /root/clawd-backend/venv/bin/python
pm2 start project_creation_worker.py --name clawd-project-creation-worker --interpreter /root/clawd-backend/venv/bin/python
pm2 save
```

Optional scheduler move:

```bash
pm2 start ecosystem.scheduler.json
pm2 save
```

Only move `clawd-scheduler` if scheduler execution loads project code and you want that isolated with Claude/user projects.

## Phase 5: Drain Main VPS Workers

Do not abruptly kill in-progress worker jobs.

1. Stop accepting new worker claims on the main VPS.
2. Let existing active jobs finish.
3. Confirm no active processing sessions/runs remain on main VPS workers.
4. Stop main VPS worker PM2 processes.
5. Start worker VPS PM2 processes.

Suggested order:

```bash
# Main VPS
pm2 stop clawd-session-chat-worker
pm2 stop clawd-project-creation-worker

# Worker VPS
pm2 start clawd-session-chat-worker
pm2 start clawd-project-creation-worker
```

If both old and new workers run at the same time, DB row locking must prevent duplicate claims. Still, use a short overlap only for testing.

## Phase 6: Project File Storage Strategy

### Option A: Worker Owns Project Files

Best isolation, simplest security boundary.

- New projects are created on the worker VPS.
- Build/publish runs on the worker VPS.
- Main API reads project metadata from DB only.
- Code editor/file APIs need a bridge if users edit files from the main API.

Use this when all file operations are already worker-driven or can be proxied safely.

### Option B: Shared Storage

Useful during migration.

- Mount the same project directory on main and worker VPS using NFS, SSHFS, or block storage.
- Main API can still serve file/code APIs.
- Worker runs Claude and build tasks against the shared path.

Risks:

- Shared filesystem permissions must be strict.
- Network storage latency may affect builds.
- Bad mounts can break active jobs.

### Option C: Worker Syncs Files Back

Safer than shared mounts, more work.

- Worker creates/edits project files locally.
- Worker pushes changes to Git or uploads artifacts.
- Main API pulls or reads published artifacts.

Use this later if moving toward multiple workers.

Recommended first migration: **Option B for smooth transition**, then move toward **Option A** after code editor/file APIs are worker-aware.

## Phase 7: Main API Changes to Avoid

For a smooth move, do not change:

- Public API domains.
- Frontend request URLs.
- Telegram/Discord/Slack webhook URLs.
- Auth token format.
- Billing/webhook flow.
- Project/session DB schema unless required.
- User-facing project/session routes.

Avoid asking the frontend to call the worker VPS. That creates CORS, auth, and tenant-isolation risk.

## Phase 8: Health Checks

Add or verify checks for:

- Worker DB connectivity.
- Claude Code executable availability.
- Project root writable.
- Git available and authenticated.
- Node/pnpm/npm available.
- Hostinger/GitHub provider tokens available where needed.
- Worker can claim a queued dry-run job.
- Sentry service tag identifies `session-chat-worker` and `project-creation-worker`.

Example manual checks:

```bash
pm2 logs clawd-session-chat-worker --lines 50
pm2 logs clawd-project-creation-worker --lines 50
python -m py_compile session_chat_worker.py project_creation_worker.py
```

## Phase 9: Rollout Test Plan

Run these before disabling workers on the main VPS permanently:

1. Create a new website project.
2. Confirm the worker VPS claims the project creation run.
3. Confirm project status moves from `creating` to `running`.
4. Open the generated project.
5. Create a project edit session from web.
6. Send a session chat edit.
7. Restart only `clawd-backend` on the main VPS during the edit.
8. Confirm chunks/status continue through DB-backed polling.
9. Confirm final message is saved.
10. Confirm token usage and billing update once.
11. Confirm commit history appears when `has_writes=true`.
12. Test Telegram selected-session edit.
13. Test Discord `/chat`.
14. Test Slack `/dream-chat` or selected-session command.
15. Confirm duplicate messages are blocked while a run is processing.

## Rollback Plan

Rollback should not require code changes.

1. Stop worker VPS processes:

```bash
pm2 stop clawd-session-chat-worker
pm2 stop clawd-project-creation-worker
```

2. Start main VPS workers:

```bash
pm2 start clawd-session-chat-worker
pm2 start clawd-project-creation-worker
```

3. Let stale-run cleanup unlock interrupted jobs if the worker died mid-run.
4. Manually inspect active runs and project statuses.

If shared storage was used, no project file copy-back should be required.

## Operational Notes

- Keep one worker active per queue until multi-worker claim behavior has been load-tested.
- Use DB row locks as the source of truth for claim ownership.
- Do not run public webhooks on the worker VPS.
- Do not store user project secrets in prompts or logs.
- Rotate worker provider tokens independently from main API tokens.
- Keep Sentry enabled on both worker services with service tags.
- Keep PM2 logs enabled; Sentry is for errors, not a replacement for operational logs.

## Future Improvements

- Add `worker_nodes` table for health, capacity, and drain state.
- Add queue assignment by project type.
- Add artifact storage for generated ZIPs/builds.
- Add worker autoscaling.
- Add per-user or per-project worker isolation.
- Move generated project runtimes to a separate app-hosting VPS or container pool.

## Release Recommendation

The safest production path is:

1. Keep public API and webhooks on the main VPS.
2. Move only durable workers and Claude/project execution to the worker VPS.
3. Use DB-backed queue communication.
4. Start with shared project storage for migration speed.
5. Later move file APIs/build artifacts to worker-owned storage when the worker boundary is mature.

