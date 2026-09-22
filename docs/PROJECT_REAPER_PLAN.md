# Project Reaper — inactive project lifecycle (pause → grace → permanent delete)

Status: DESIGN (approved direction; not yet implemented)
Owner notes: folds in the 2026-09-22 requirements — PM2 delete, frontend-nginx
stop, grace window with restore, then permanent deletion — on top of the
original "inactive > 10 days → notify → wait → delete" design.

---

## 1. Goal

Reclaim worker resources (PM2 processes, nginx sites, disk, containers) from
projects nobody uses, without ever surprising a returning user:

- **Reversible first**: an idle project is *paused* (service stopped, site
  shows a "paused" page), never deleted, during the grace window.
- **One-click restore**: any activity or a Restore button brings the exact
  same service back in seconds — same PM2 app, same nginx site, same files.
- **Permanent delete only after**: two ignored notifications + a fully
  paused grace window, reusing the existing battle-tested
  `cleanup_infrastructure()` teardown.

## 2. What counts as "activity" (important)

`projects.last_used_at` exists in the schema but is **never written** —
do not trust it. Compute last activity per project instead:

```sql
SELECT p.id,
       GREATEST(
           COALESCE(p.updated_at,  p.created_at),
           COALESCE((SELECT MAX(s.last_used_at) FROM sessions s
                      WHERE s.project_id = p.id), p.created_at),
           COALESCE((SELECT MAX(m.created_at) FROM messages m
                      JOIN sessions s ON s.id = m.session_id
                     WHERE s.project_id = p.id), p.created_at),
           COALESCE((SELECT MAX(c.created_at) FROM commit_log c
                     WHERE c.project_id = p.id), p.created_at),
           COALESCE((SELECT MAX(t.created_at) FROM token_usage t
                     WHERE t.project_id = p.id), p.created_at)
       ) AS last_activity
FROM projects p
```

Any of these cancels/defers reaping: session-chat message, edit commit,
token usage (creation + chat + verification all write token_usage),
projects.updated_at (env edits, publishes).

## 3. Lifecycle state machine

```
                activity / Restore button
        ┌──────────────────────────────────────────────┐
        ▼                                              │
   ┌─────────┐   idle > 10d      ┌───────────┐  +2d    │
   │ ACTIVE  │ ────────────────► │ SCHEDULED │ ─────►  │
   └─────────┘  email #1         │ (warning  │ email #2│
                                   badge only,│         ▼
                                   still     │    ┌─────────┐  +3d
                                   running)  │    │ PAUSED  │ ─────► DELETE
                                   └───────────┘    │ pm2 stop│        (permanent,
                                                    │ nginx →│         existing
                                                    │ paused │         full cleanup)
                                                    │ page    │
                                                    └─────────┘
```

| Phase | Service | Nginx | Files/DB | Exit |
|---|---|---|---|---|
| SCHEDULED (day 10) | running | live | untouched | activity → ACTIVE; +2d → PAUSED |
| PAUSED (day 12) | `pm2 stop` | conf swapped to paused page (503) | untouched — workspace, PM2 app entry, env, certs all kept | Restore → ACTIVE (resume); +3d → DELETE |
| DELETE (day 15) | `pm2 delete` + `pm2 save` | conf + symlink removed, certs removed | workspace, DB cascade, container cleanup | gone |

Defaults (all env-tunable, §8): notify at **10d idle**, pause **2d later**,
delete **3d after pause** → a user gets **5 days** of warnings after the
first email, and the last 3 of those with the project visibly paused but
fully restorable.

## 4. Why pause instead of delete-on-day-12

- Restore must be **lossless and instant** (`pm2 start` + symlink swap,
  ~2s). After a real delete nothing survives.
- The paused page tells *visitors* the truth ("temporarily paused") instead
  of a raw 502 from a dead upstream.
- PM2 stop keeps the app entry (name, script, args, env) — exactly the
  metadata the v4 scrub relied on — so resume can never mis-rebuild a bot's
  args.

## 5. Components

### 5.1 DB (main, `database_postgres.py` migration)

```sql
ALTER TABLE projects ADD COLUMN reap_state TEXT DEFAULT 'active';
-- 'active' | 'scheduled' | 'paused'
ALTER TABLE projects ADD COLUMN reap_scheduled_at TIMESTAMPTZ;
ALTER TABLE projects ADD COLUMN reap_paused_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS projects_reap_state_idx ON projects (reap_state);

CREATE TABLE IF NOT EXISTS reap_events (
    id SERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL,
    action TEXT NOT NULL,      -- scheduled|paused|resumed|deleted|skipped|error
    detail JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

`reap_events` is append-only audit — every decision, skip reason, and error
gets a row (grep `[REAPER]` in PM2 logs for the live view).

### 5.2 Reaper loop — `scripts/project_reaper.py` on MAIN (new PM2 app)

Modeled on `scripts/container_reaper.py` (60s poll, SIGTERM-clean,
per-item isolation). Each cycle:

1. Compute last-activity (§2) for all projects.
2. **active → scheduled**: idle ≥ `REAP_IDLE_DAYS` and passes guards (§6).
   Send email #1, set `reap_state='scheduled'`, `reap_scheduled_at=now`.
3. **scheduled → paused**: scheduled ≥ `REAP_NOTIFY_DAYS` and still idle.
   Call worker `POST /internal/projects/{id}/pause-infrastructure`,
   set `reap_state='paused'`, `reap_paused_at=now`, send email #2
   ("paused — restore before {date} or it will be permanently deleted").
4. **paused → delete**: paused ≥ `REAP_GRACE_DAYS` and still idle.
   Run the delete path (5.4), send email #3 (confirmation).
5. Any project whose activity is fresh while in `scheduled`/`paused`:
   auto-resume (restore path) — **activity always wins**, even mid-grace.

Cap per cycle (`REAP_MAX_ACTIONS=20`) so a first run on a backlog can't
thundering-herd the worker; the rest rolls to the next cycle.

### 5.3 Worker internal routes (same file pattern as
`/internal/projects/{id}/cleanup-infrastructure`, app.py:5667)

- `POST /internal/projects/{project_id}/pause-infrastructure`
  Body: `{pm2_name, domain}` (pm2/nginx name = `frontend_domain or
  project_name`, same resolution as `cleanup_infrastructure`).
  1. `pm2 stop <pm2_name>` (keep entry; keep ecosystem/metadata).
  2. nginx: move `/etc/nginx/sites-available/<domain>.conf` →
     `<domain>.conf.reaped`, write minimal conf serving a 503
     "project paused" HTML page for the same server_names, `nginx -t`,
     `systemctl reload nginx`. Certs untouched (renewal keeps working).
  3. Bot/scheduler projects (no nginx site): step 2 is a no-op.
- `POST /internal/projects/{project_id}/resume-infrastructure`
  1. Restore the `.conf.reaped` file back over the paused conf, reload.
  2. `pm2 restart <pm2_name>` (PM2 restart uses the stored interpreter,
     script, and args — no rebuild).
- Guarded by `x-internal-secret` (`INTERNAL_API_SECRET`, both VPSes).

### 5.4 Delete — reuse, don't rewrite

Refactor `delete_project()` (app.py:5704) minimally:

- Extract its body into `_delete_project_core(project_id, *, force=False,
  source="user")` — the user endpoint calls it with owner auth; the reaper
  calls it with `source="reaper"` (skips owner check, still honors the
  active-session-chat 409 guard).
- It already does everything: DB cascade first, then forwards to worker
  `cleanup-infrastructure`, which runs `cleanup_pm2_services()` (pm2 delete
  + save), `cleanup_nginx_config()` (symlink → conf → reload; also certbot
  removal inside `cleanup_infrastructure()`), workspace delete, project DB
  drop, and `_cleanup_user_container_if_empty()`.

### 5.5 Restore endpoint + frontend

- `POST /projects/{project_id}/reap/restore` (owner auth):
  sets `reap_state='active'`, clears timestamps, calls worker
  resume-infrastructure, logs `reap_events(action='resumed',
  detail={source:'user'})`. Works from both SCHEDULED and PAUSED.
- Frontend (`muse-companion-app`):
  - Project card badge: "⚠️ Scheduled for deletion {date}" / "⏸ Paused —
    restore by {date}".
  - Banner + **Restore** button on the project page.
  - Email links land on `/app/projects` (badge + button already visible).
- Emails via existing `services/email_service.py` (add
  `send_reap_notice(kind, email, project, deadline, restore_url)` — plain
  text, no secrets, one CTA link).

## 6. Guards — who is never reaped

A project is skipped (logged `skipped` with reason) when any of:

1. Published to gallery (`gallery_projects` reference — confirm exact FK
   column during implementation; showcase stays up).
2. Younger than `REAP_MIN_AGE_DAYS=14` (don't shoot builds in progress).
3. Active session-chat run (same check the delete endpoint uses).
4. Owner has an active paid subscription
   (`services/billing_service.py`) — optional, decide at implementation.
5. Listed in `REAP_EXCLUDE_IDS` (emergency ops override).
6. `REAP_DRY_RUN=1` — compute and log everything, touch nothing.

## 7. Manual commands (today, before the automation exists)

```bash
# ---- stop (reversible) ----
pm2 stop <pm2_name>                       # e.g. dreamsong-hjwj59-…
rm /etc/nginx/sites-enabled/<domain>.conf # disable site, KEEP sites-available
nginx -t && systemctl reload nginx

# ---- restore ----
ln -s ../sites-available/<domain>.conf /etc/nginx/sites-enabled/<domain>.conf
nginx -t && systemctl reload nginx
pm2 restart <pm2_name>

# ---- permanent ----
pm2 delete <pm2_name> && pm2 save
rm /etc/nginx/sites-enabled/<domain>.conf /etc/nginx/sites-available/<domain>.conf
nginx -t && systemctl reload nginx
# ...plus workspace dir, project DB, container — prefer deleting via the
# app's DELETE /projects/{id} so DB rows + forwards happen correctly.
```

PM2/nginx name = `frontend_domain or project_name` (from the projects
row's `domain`/`name` — same rule `cleanup_infrastructure()` uses).

## 8. Configuration (env, all VPS-independent)

| Var | Default | Meaning |
|---|---|---|
| `REAP_IDLE_DAYS` | 10 | idle threshold → SCHEDULED |
| `REAP_NOTIFY_DAYS` | 2 | SCHEDULED → PAUSED after this |
| `REAP_GRACE_DAYS` | 3 | PAUSED → DELETE after this |
| `REAP_MIN_AGE_DAYS` | 14 | never reap younger projects |
| `REAP_MAX_ACTIONS` | 20 | per-cycle action cap |
| `REAP_DRY_RUN` | 1 | ship with dry-run ON; flip after review |
| `REAP_EXCLUDE_IDS` | "" | comma-separated project ids |
| `REAP_POLL_SECONDS` | 3600 | loop interval (hourly is plenty) |

## 9. Rollout

1. Migration (columns + audit table) — backward-compatible, ships inert.
2. Reaper loop with `REAP_DRY_RUN=1` for ≥ 3 days → review `reap_events`
   (expected skips, correct idle set vs. manual `pm2 ls` eyeball).
3. Enable notify-only (comment out the pause call) for 3 more days — real
   emails, zero infra action.
4. Full enable. Watch: restore click-through, paused→resume latency
   (< 5s), zero reaped projects with fresh activity.
5. Keep `container-reaper` as-is — it already handles the Docker layer
   this plan intentionally does not touch (pause ≠ container stop; the
   container idles out on its own 60s loop).

## 10. Test plan

- Unit: idle computation SQL against a fixture project set (fresh chat,
  old chat + fresh commit, gallery project, young project).
- Worker route tests: pause → `pm2 ls` shows stopped + paused page 503;
  resume → online + original conf byte-identical (diff before/after).
- E2E dry-run: seed `last_used_at`-equivalent history 11/13/16 days back,
  run `--once`, assert state transitions + emails + audit rows.
- Restore E2E: pause a real dev project, click Restore, verify bot answers
  `/dev/invoke` or website loads within 5s, `reap_state='active'`.
