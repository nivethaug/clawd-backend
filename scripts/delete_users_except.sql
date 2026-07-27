-- ============================================================================
-- delete_users_except.sql
-- ============================================================================
-- Delete all users EXCEPT the keep-list (default: 24 and 26), plus all their
-- related data across every table that references them.
--
-- IMPORTANT — read before running:
--   1. TAKE A BACKUP FIRST:
--        docker exec dreampilot-postgres pg_dump -U admin dreampilot > backup_$(date +%Y%m%d_%H%M%S).sql
--   2. This ships with ROLLBACK at the end so it is a DRY RUN by default.
--      Run it, check the "Surviving users" output shows only 24 and 26,
--      then change ROLLBACK -> COMMIT (see bottom of file) and re-run.
--   3. Run it inside the postgres container:
--        docker exec -i dreampilot-postgres psql -U admin dreampilot < scripts/delete_users_except.sql
--   4. After committing, clean up Docker containers + workspace dirs for the
--      deleted users (see the comment block at the very bottom).
--
-- WHY projects.user_id is handled explicitly:
--   projects.user_id has NO foreign key to users, so DELETE FROM users does
--   NOT cascade to projects. We must drive project-tree cleanup bottom-up
--   ourselves; otherwise projects (and their sessions/messages/etc.) become
--   orphaned.
-- ============================================================================

-- The two user ids to KEEP. Edit this list if you need different survivors.
-- To keep more users, e.g. 24, 26, 30: change to (24, 26, 30) everywhere
-- below (the _doomed_users + _doomed_projects definitions).

BEGIN;

CREATE TEMP TABLE _doomed_users AS
  SELECT id FROM users WHERE id NOT IN (24, 26);

CREATE TEMP TABLE _doomed_projects AS
  SELECT id FROM projects WHERE user_id IN (SELECT id FROM _doomed_users);

-- ---- Bottom-up project-tree cleanup ----
-- (sessions and their children)
DELETE FROM session_chat_chunks
  WHERE run_id IN (
    SELECT id FROM session_chat_runs
    WHERE session_id IN (SELECT id FROM sessions WHERE project_id IN (SELECT id FROM _doomed_projects))
  );

DELETE FROM session_chat_runs
  WHERE session_id IN (SELECT id FROM sessions WHERE project_id IN (SELECT id FROM _doomed_projects));

DELETE FROM claude_session_resumes
  WHERE session_id IN (SELECT id FROM sessions WHERE project_id IN (SELECT id FROM _doomed_projects));

DELETE FROM messages
  WHERE session_id IN (SELECT id FROM sessions WHERE project_id IN (SELECT id FROM _doomed_projects));

DELETE FROM plans
  WHERE session_id IN (SELECT id FROM sessions WHERE project_id IN (SELECT id FROM _doomed_projects));

DELETE FROM sessions
  WHERE project_id IN (SELECT id FROM _doomed_projects);

-- (scheduler tree)
DELETE FROM scheduler_logs
  WHERE job_id IN (SELECT id FROM scheduler_jobs WHERE project_id IN (SELECT id FROM _doomed_projects));

DELETE FROM scheduler_jobs
  WHERE project_id IN (SELECT id FROM _doomed_projects);

-- (other project-scoped tables)
DELETE FROM custom_domains WHERE project_id IN (SELECT id FROM _doomed_projects);
DELETE FROM commit_log     WHERE project_id IN (SELECT id FROM _doomed_projects);

-- Now safe to remove the projects themselves
DELETE FROM projects WHERE id IN (SELECT id FROM _doomed_projects);

-- ---- User-scoped tables that lack a clean cascade path ----
-- project_creation_chunks reference runs; clean before the runs
DELETE FROM project_creation_chunks
  WHERE run_id IN (SELECT id FROM project_creation_runs WHERE user_id IN (SELECT id FROM _doomed_users));

-- ai_sessions are keyed by session_key (no user_id FK); clean stale entries
-- whose active_project_id matched a doomed project's domain
DELETE FROM ai_sessions
  WHERE active_project_id IN (
    SELECT domain FROM projects
    JOIN _doomed_projects dp ON projects.id = dp.id
  );

-- ---- User-scoped tables (most cascade from users; listed for auditability) ----
DELETE FROM token_usage           WHERE user_id IN (SELECT id FROM _doomed_users);
DELETE FROM projectchat           WHERE user_id IN (SELECT id FROM _doomed_users);
DELETE FROM user_credit_balances  WHERE user_id IN (SELECT id FROM _doomed_users);
DELETE FROM credit_transactions   WHERE user_id IN (SELECT id FROM _doomed_users);
DELETE FROM subscriptions         WHERE user_id IN (SELECT id FROM _doomed_users);
DELETE FROM user_containers       WHERE user_id IN (SELECT id FROM _doomed_users);
DELETE FROM gallery_projects      WHERE user_id IN (SELECT id FROM _doomed_users);
DELETE FROM templates             WHERE user_id IN (SELECT id FROM _doomed_users);
DELETE FROM project_creation_runs WHERE user_id IN (SELECT id FROM _doomed_users);

-- ---- Finally, the users themselves ----
DELETE FROM users WHERE id IN (SELECT id FROM _doomed_users);

-- ---- VERIFY: must show only 24 and 26 ----
\echo '=== Surviving users (must be only 24 and 26) ==='
SELECT id, email FROM users ORDER BY id;

ROLLBACK;
-- ^^^ DRY RUN. Once the survivors list above looks correct, change ROLLBACK
--     to COMMIT and re-run. To edit in place on the server:
--       sed -i 's/^ROLLBACK;/COMMIT;/' scripts/delete_users_except.sql
--     then re-run the same docker exec command.

-- ============================================================================
-- POST-DELETION CLEANUP (run on the shell, NOT in psql)
-- ============================================================================
-- After COMMIT, remove the orphaned Docker containers and workspace dirs for
-- the deleted users (run on every VPS that hosts project containers):
--
--   # Stop + remove project containers (everyone except 24, 26)
--   docker ps -a --filter "name=dreamagent-user-" --format '{{.Names}}' \
--     | grep -E '^dreamagent-user-[0-9]+$' \
--     | grep -vE '^dreamagent-user-(24|26)$' \
--     | while read -r cname; do docker rm -f "$cname"; done
--
--   # Remove workspace dirs (everyone except 24, 26)
--   for d in /workspaces/user_*; do
--     [ -d "$d" ] || continue
--     uid="${d#/workspaces/user_}"
--     case "$uid" in 24|26) ;; *) rm -rf "$d";; esac
--   done
-- ============================================================================
