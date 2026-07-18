# Phase 0 — Container Migration Analysis

> **Status:** Phase 0 deliverable. Analysis only — no code changes in this phase.
> **Companion:** [container_isolation.md](./container_isolation.md) — approved architecture.

This document inventories every code path that executes user-influenced code on
the worker host today, the risks of moving each into a container, the smoke
tests that must pass before each phase is approved, and the manual regression
checklist reused from `worker_vps_setup.md`.

---

## 1. Dependency graph — every subprocess execution site

These are the call sites Phases 1–5 will route through `ProjectRuntimeManager`.
Line numbers verified against the current tree.

### A. Claude AI edit (Phase 4 target)

| File | Line | Call | cwd | Today's user |
|---|---|---|---|---|
| `claude_code_agent.py` | 825 | `asyncio.create_subprocess_exec([claude, ..., "-p", prompt, "--dangerously-skip-permissions", "--output-format","stream-json","--verbose"])` | `repo_path` (project root) | root → sudo -u dreampilot (line 802–809) |
| `claude_code_agent.py` | 295 | `asyncio.create_subprocess_shell` (legacy path, may be unused) | (varies) | root |
| `acp_chat_handler.py` | ~3319 | `subprocess.Popen(["stdbuf","-oL","acpx",...,"claude","exec",prompt])` with `--approve-all` | `frontend_src_path` | root |

**Coupling points:**
- `_find_claude_cli` (`claude_code_agent.py:322`) — `shutil.which("claude")` + hardcoded fallbacks `/usr/local/bin/claude`, `/usr/bin/claude`. Inside container these resolve to the image's installed claude.
- Env propagation (`claude_code_agent.py:760-773`) — `os.environ.copy()` + PATH prepend + `~/.claude/settings.json` merge. Inside container the settings live at `/home/dreampilot/.claude/settings.json` (baked into image).
- `_cleanup_project_serve_processes` (`claude_code_agent.py:237`) and `_cleanup_optional_global_helpers` (line 271) do host-global `ps` walks + `pkill`. Inside a container these naturally scope to the container's PID namespace — no change needed.
- `kill_orphan_processes` (`acp_chat_handler.py:2866`) and `_get_chrome_devtools_pids` (line 341) use `pgrep -f claude-agent-acp` / `pgrep -f chrome-devtools-mcp`. Same natural scoping inside container.

**Phase 4 change:** swap `sudo -u dreampilot claude ...` for `docker exec -u 1001:1001 -w <path> dreamagent-user-<id> claude ...`. Streaming JSON parsing unchanged.

### B. Build / publish (Phase 5 target)

| File | Line | Call | cwd | Notes |
|---|---|---|---|---|
| `buildpublish.py` | 69 | `subprocess.run([npm, "install", ...])` | frontend_path | npm install |
| `buildpublish.py` | 86 | `subprocess.run([npm, "run", "build"])` | frontend_path | npm build |
| `buildpublish.py` | 161 | `subprocess.run([pip, "install", ...])` | backend_path | pip install |
| `buildpublish.py` | 215 | `subprocess.run([pm2, "jlist"])` | (host) | **stays on host** (PM2 lives on host in v1) |
| `buildpublish.py` | 224 | `subprocess.run([pm2, "restart", ...])` | (host) | **stays on host** |
| `buildpublish.py` | 255 | `subprocess.run([pm2, "list"])` | (host) | **stays on host** |
| `buildpublish.py` | 267 | `subprocess.run([nginx, "-s", "reload"])` | (host) | **stays on host** |
| `infrastructure_manager.py` | 760 (comment), 2342 (npm ci call in phase 5) | `subprocess.run([npm, "ci", ...])` | frontend_path | initial build (phase 5 of pipeline) |
| `infrastructure_manager.py` | 2342+ | `subprocess.run([npm, "run", "build"])` | frontend_path | initial build |
| `infrastructure_manager.py` | 2149 | `_claude_fix_build_error` via `ClaudeCodeAgent` | project_path | auto-fix loop (uses Phase 4 path) |

**Phase 5 change:** npm/pip/build call sites route through `ContainerManager.exec()`. PM2 + nginx calls stay on host (preview is static in v1). Bind-mount means dist/ written by container is immediately visible to host nginx.

### C. Not moved in v1 (but tracked)

| File | Line | Call | Why deferred |
|---|---|---|---|
| `apps_service.py` | 60, 70, 499 | `subprocess.run([pm2, ...])` | PM2 lifecycle stays on host (preview is static) |
| `env_manager.py` | 453, 487 | `subprocess.run([pm2, "restart", ...])` | Same |
| `services/scheduler/execution_engine.py` | 170 | `importlib` load of user `executor.py` | Deferred — scheduler isolation is a separate project |
| `github_service.py` | 216–404 | `git`/`gh` subprocess in `project_path` | Token-leak risk via `.git/config` (lines 396–401); fix independent of containers — `github_export_service.py` REST path is safe |
| `export_service.py` | 361 | `os.walk(project_path)` | Runs on host today; Phase 3 of future work will move to in-container tar |

### D. Database provisioning (NOT moved in v1)

| File | Line | Call | Notes |
|---|---|---|---|
| `infrastructure_manager.py` | 263 | `subprocess.run([docker, "exec", dreampilot-postgres, psql, ...])` | Stays unchanged. Per-project DB isolation is already correct. |

---

## 2. Path constants that must become user-aware

| File | Line | Current | After Phase 2 |
|---|---|---|---|
| `project_manager.py` | 14 | `BASE_PROJECTS_DIR = "/root/dreampilot/projects"` | env-driven; `EXECUTION_MODE=container` → `/workspaces/user_<id>/{type}/...` |
| `project_manager.py` | 106 | `build_type_based_path(project_id, name, type_id)` | add `user_id` param; branch on EXECUTION_MODE |
| `buildpublish.py` | 32 | `PROJECTS_BASE_PATH = Path("/root/dreampilot/projects/website")` | read from project record's `project_path` (already DB-stored) |
| `acp_chat_handler.py` | 52 | `ALLOWED_PROJECTS_BASE = "/root/dreampilot/projects/website"` | extend allowlist to include `/workspaces/user_<id>/website` |
| `acp_frontend_editor_v2.py` | 47 | same | same |
| `app.py` | 3209 | `dreampilot_root = "/root/dreampilot/projects/website"` | resolve from project_path |
| `context_injector.py` | 17 | `PROJECT_BASE_PATH = "/root/dreampilot/projects"` | same |
| `infrastructure_manager.py` | 97 | `SHARED_VENV_PATH = "/root/dreampilot/dreampilotvenv"` | **stays on host** — deployed backend PM2 processes use it (v1 backends stay on host) |

---

## 3. Risk report

### High risk

**R1. Streaming regression in Claude path.**
`asyncio.create_subprocess_exec` reads stdout as a pipe. `docker exec` stdout is
also a pipe, but the docker CLI adds its own buffering layer. Risk: SSE chunks
arrive in bursts instead of streaming smoothly, breaking the chat UX.
**Mitigation:** Phase 4 must verify streaming latency is unchanged. Use
`stdbuf -oL` wrapper or `--tty=false` if buffering appears. Test with a real
chat session, not just a one-shot prompt.

**R2. Path resolution breakage.**
Hardcoded paths in 7 files (see §2). Any one of these not updated will silently
write to `/root/dreampilot/projects/...` for a containerized project, causing
files to land in the wrong place (container can't see them, host nginx can't
serve them).
**Mitigation:** Phase 2 is purely a path refactor — no Docker yet. Run the full
manual regression checklist in BOTH `EXECUTION_MODE=local` and
`EXECUTION_MODE=container` before approving Phase 2.

**R3. UID/GID mismatch on bind-mount.**
Container runs as uid 1001; host directory must be chowned 1001:1001. If
`ensure_workspace()` doesn't chown correctly, Claude inside container gets
EACCES on every write — same bug we hit during the original worker migration
(fixed by `_fix_project_ownership` in `services/project_creation_runs.py:491`).
**Mitigation:** `ensure_workspace` always `chown -R 1001:1001`. Add a write-test
probe after workspace creation.

### Medium risk

**R4. Claude settings.json + .claude.json inside container.**
The `wrapper-v2` proxy URL, MCP servers, and onboarding state live in
`/etc/claude/settings.json` + `~/.claude.json` on host. Inside container, these
must be baked into the image (Phase 3 Dockerfile) so Claude doesn't say "Not
logged in" (Gotcha #8 from worker_vps_setup.md).
**Mitigation:** Image build script copies both files in. Verify with
`docker exec ... claude --version` returning clean output.

**R5. MCP servers (chrome-devtools) unreachable inside container.**
The chrome-devtools MCP connects to `http://127.0.0.1:9222` on host. Inside
container, `127.0.0.1` is the container itself.
**Mitigation:** Either (a) disable chrome-devtools MCP in containerized Claude
(acceptable — verification phase can run on host after build), or (b) mount the
host's 9222 via `--add-host=host.docker.internal:host-gateway` and rewrite the
MCP URL. Recommend (a) for v1; chrome verification is a nice-to-have, not
required for the edit/build flow.

**R6. Concurrent edits to same project.**
`SessionLockService` already prevents this at the DB level. Containerization
doesn't change the lock semantics, but the container must be the same one for
all edits to a user's projects (it is — one container per user, not per
project).
**Mitigation:** No change needed. Verify lock still works after Phase 4.

### Low risk

**R7. PM2 cache pollution.**
`apps_service.get_pm2_processes()` returns all PM2 apps host-wide. Already a
known cross-user visibility issue, not caused or worsened by containerization.
**Mitigation:** Document as pre-existing; address separately.

**R8. Reaper stopping a container mid-edit.**
15-min idle threshold could in theory fire during a long Claude generation.
**Mitigation:** Reaper only stops containers with `last_used_at < now - 900s`.
Every `ensure_container` call bumps `last_used_at`, and Claude runs bump it on
chunk receipt. A 5-min generation bumps the timestamp many times — won't be
reaped mid-run.

**R9. Container image version drift.**
If `dreamagent/user-workspace:latest` is rebuilt with a new Claude version,
existing containers don't pick it up until recreated.
**Mitigation:** Document image-update runbook in Phase 3 (manual `docker rm -f`
+ next `ensure_container` recreates with new image).

---

## 4. Smoke tests (automated, mandatory before each phase gate)

These 6 tests must be automated and must pass after every phase. They live in
`tests/container_smoke/` (created in Phase 1, expanded per phase).

### S1. Project creation

```
POST /projects (EXECUTION_MODE=<current>)
  → assert project row created
  → assert project_path starts with expected root (/root/dreampilot OR /workspaces/user_X)
  → assert folder exists on disk
  → assert folder owned by 1001:1001 (container mode) OR dreampilot:dreampilot (local mode)
```

### S2. AI generation (Claude)

```
POST /chat/stream with a simple "create a hello world React component" prompt
  → assert SSE stream opens
  → assert ≥1 chunk received within 30s
  → assert file written under project_path/frontend/src/
  → assert no errors in worker logs
```

### S3. Claude file edit

```
POST /chat/stream with "add a button to App.tsx"
  → assert chunk stream includes "has_writes" indicator
  → assert file modified
  → assert git commit created (if auto-commit enabled)
```

### S4. Build

```
POST /projects/{id}/editor/build-publish
  → assert dist/index.html exists
  → assert no build errors
  → assert nginx serves the new dist (HTTP 200 on {project}.dreamagent.cloud)
```

### S5. Database provisioning

```
Trigger project creation
  → assert docker exec dreampilot-postgres psql -c "\\l" shows <domain>_db
  → assert <domain>_user exists
  → assert project backend .env contains DATABASE_URL=...@localhost:5432/<domain>_db
```

### S6. Project deletion

```
DELETE /projects/{id}
  → assert project row removed
  → assert folder removed from disk
  → assert PM2 apps stopped + removed
  → assert nginx config removed
  → assert DB + user dropped
  → (container mode) assert user container removed IF this was user's last project
```

---

## 5. Manual regression checklist (every phase)

Extracted and expanded from `worker_vps_setup.md` Phase 10. Run by hand after
every phase, in BOTH `EXECUTION_MODE=local` and `EXECUTION_MODE=container`
(once container mode exists).

### Critical paths

- [ ] **Authentication** — login, token issuance, token validation
- [ ] **Project creation** — new website project, completes in <6 min, status reaches `running`
- [ ] **AI generation** — Claude produces a working frontend
- [ ] **AI edit** — chat message modifies a file, streaming works
- [ ] **Build** — `npm run build` succeeds, `dist/` produced
- [ ] **Preview** — `{project}.dreamagent.cloud` returns HTTP 200 with built site
- [ ] **Database** — project backend connects to its DB, CRUD works
- [ ] **Git** — auto-commit after edit pushes to GitHub
- [ ] **Delete** — project + folder + PM2 + nginx + DB all cleaned up

### Secondary paths

- [ ] **Files API** — `GET /projects/{id}/files` returns tree; `PUT` writes file
- [ ] **Logs** — `GET /projects/{id}/logs` returns PM2 logs
- [ ] **Download ZIP** — `GET /projects/{id}/download` streams valid ZIP
- [ ] **GitHub export** — `POST /projects/{id}/github-export` creates repo + pushes
- [ ] **Env vars** — read/write/reveal via env_manager
- [ ] **Apps action** — start/stop/restart via `POST /apps/{id}/action`
- [ ] **Commits** — `GET /projects/{id}/commits` shows history; rollback works
- [ ] **Queue** — durable queue claims + heartbeats visible in DB
- [ ] **Scheduler** — `clawd-scheduler` runs jobs (only if scheduler enabled — currently deferred)
- [ ] **Dashboard** — admin dashboard loads, shows project list
- [ ] **Project proxy** — main → worker forwarding works for file-dependent endpoints

### Container-specific (only when EXECUTION_MODE=container)

- [ ] Container created for user on first action
- [ ] Container restarted (not recreated) on second action
- [ ] Container stopped after 15 min idle (verify via `docker ps`)
- [ ] Container restarted on next action after idle-stop
- [ ] `docker exec ... ls /root` → permission denied or no such file
- [ ] `docker exec ... ls /workspaces/user_OTHER` → not visible
- [ ] `docker exec ... cat /etc/shadow` → permission denied
- [ ] `docker exec ... docker ps` → no docker binary in container
- [ ] Resource limits applied: `docker inspect --format='{{.HostConfig.Memory}}'` shows 2g

---

## 6. Phase sequence (locked)

| Phase | Scope | Touches | Gate |
|---|---|---|---|
| **0** | This document. Analysis only. | none | approval |
| **1** | `ProjectRuntimeManager` + `ContainerManager` classes. Route ONE call site (Claude in `claude_code_agent.py`) through it. `EXECUTION_MODE=local` everywhere → behavior identical. | `services/runtime_manager.py` (new), `services/container_manager.py` (stub), `claude_code_agent.py` (one refactor) | S1–S6 + manual checklist, local mode only |
| **2** | Workspace path abstraction. `/workspaces/user_<id>/` layout, `ContainerStorage` interface. `project_manager.build_type_based_path` accepts `user_id`. Legacy paths still work. No Docker. | `services/container_storage.py` (new), `project_manager.py`, path constants in 7 files | S1–S6 + manual checklist, both modes |
| **3** | Docker image + ContainerManager impl + resource limits + cheap hardening + idle reaper + network + DB table. Containers can be created/started/stopped manually. Nothing uses them in production paths yet. | `docker/Dockerfile.user` (new), `scripts/build_user_image.sh` (new), `scripts/container_reaper.py` (new), `services/container_manager.py` (full impl), `database_postgres.py` (user_containers table) | manual container lifecycle tests; full regression in local mode (nothing changed for users) |
| **4** | Claude execution → `docker exec`. Gated by `EXECUTION_MODE=container`. | `claude_code_agent.py` (docker exec branch), `services/session_chat_runs.py` (ensure_container before run) | S1–S4 + manual checklist, container mode |
| **5** | Build (npm/pip) → `docker exec`. | `buildpublish.py`, `infrastructure_manager.py` build functions | S4 + manual checklist, container mode |
| **6** | Cleanup. Remove `EXECUTION_MODE=local` Claude/build branches (only after stable period). Update docs. | `claude_code_agent.py`, `buildpublish.py`, docs | full S1–S6 + full manual checklist |

---

## 7. Stop conditions (every phase)

Do not continue to the next phase unless:

- ✅ All 6 automated smoke tests pass
- ✅ Manual regression checklist passes (both modes, once container mode exists)
- ✅ No existing feature behaves differently when `EXECUTION_MODE=local`
- ✅ Architecture review passes (this document + `container_isolation.md`)

If a phase introduces instability:
1. Stop immediately
2. Fix the issue
3. Re-run all smoke + regression tests
4. Continue only after explicit approval

**The objective is not to finish quickly. The objective is to reach the new
architecture while preserving the current stable user experience at every step.**

---

## 8. Open questions for Phase 1 kickoff

These don't block Phase 0 approval but should be resolved before Phase 1 starts:

1. **Test runner location** — `tests/container_smoke/` inside `clawd-backend`,
   or a separate `clawd-backend-tests/` repo? Recommend inside, as a new
   `tests/` dir (none exists today).
2. **Smoke test auth** — tests need an admin token. Reuse the `ADMIN_METRICS_TOKEN`
   pattern (long-lived env-var token), or create a dedicated `SMOKE_TEST_TOKEN`?
3. **Phase 4 default mode** — flip `EXECUTION_MODE=container` on for NEW projects
   only, or for all? Recommend new-only (existing projects keep their stored
   `project_path` and continue to work locally).
4. **Reaper hosting** — PM2 process or systemd timer? Recommend PM2 (matches
   existing pattern, survives reboots via `pm2 startup`).
