#!/bin/bash
# Clawd Scheduler Startup Script
#
# Loads DB credentials from .env.postgres (same pattern as start-backend.sh)
# before exec'ing the scheduler daemon. This lets ecosystem.scheduler.json
# declare only scheduler-specific env vars (SCHEDULER_*, EXECUTION_MODE) while
# the DB connection details come from the same source-of-truth file the
# backend uses.
#
# Why this exists:
#   `pm2 restart --update-env` re-reads env from the launching shell, which
#   doesn't have DB credentials. PM2 ecosystem env vars also shouldn't hold
#   secrets (the file is committed). Sourcing .env.postgres here gives the
#   scheduler a stable, secret-free-in-git startup path that matches the
#   backend's.

cd /root/clawd-backend

# Activate virtual environment (same venv the backend uses)
source venv/bin/activate 2>/dev/null || true

# Load PostgreSQL credentials — same file start-backend.sh sources.
POSTGRES_ENV_FILE="/root/clawd-backend/.env.postgres"
if [ -f "$POSTGRES_ENV_FILE" ]; then
    set -a
    source "$POSTGRES_ENV_FILE"
    set +a
    export USE_POSTGRES=true
    echo "[start-scheduler] Loaded DB config: host=$DB_HOST port=$DB_PORT db=$DB_NAME user=$DB_USER"
else
    echo "[start-scheduler] WARNING: $POSTGRES_ENV_FILE not found — DB connection may fail"
fi

# Hand off to the scheduler daemon (in the activated venv).
exec python -c "from services.scheduler.scheduler import run_scheduler; run_scheduler()"
