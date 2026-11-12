-- Migration 004 (audit T10/T11) — apply manually; never run automatically.
-- Safe to re-run (IF NOT EXISTS everywhere).
--
-- BEFORE APPLYING the unique domain index: check for existing duplicate rows:
--   SELECT lower(domain), COUNT(*) FROM projects
--   WHERE domain IS NOT NULL AND domain <> ''
--   GROUP BY lower(domain) HAVING COUNT(*) > 1;
-- Resolve any duplicates first or the index creation will fail.

-- T10: idempotency for POST /projects (Idempotency-Key header, 10-minute window)
CREATE TABLE IF NOT EXISTS project_create_idempotency (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    key         VARCHAR(64) NOT NULL,
    project_id  INTEGER NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_project_create_idempotency
    ON project_create_idempotency (user_id, key);

-- T11: case-insensitive domain uniqueness at the database level
CREATE UNIQUE INDEX IF NOT EXISTS uq_projects_domain_lower
    ON projects (lower(domain))
    WHERE domain IS NOT NULL AND domain <> '';
