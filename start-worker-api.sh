#!/bin/bash
# Worker Internal API Launcher (Option B file-proxy)
#
# Runs the SAME FastAPI app as the main backend, but on a private port (8003)
# so the main VPS can reverse-proxy project-scoped requests (download ZIP,
# github-export, logs, build/publish, files, etc.) to where the project files
# actually live.
#
# This is NOT a public API. Firewall port 8003 to the main VPS IP only:
#   ufw allow from <MAIN_VPS_IP> to any port 8003 proto tcp
#
# PM2 example:
#   pm2 start start-worker-api.sh --name clawd-worker-api
#   pm2 save
#
# The app reuses /root/clawd-backend/.env.postgres for env (DB + provider keys),
# the same file the workers read.

cd /root/clawd-backend

# Activate the worker venv (Python 3.12)
source venv/bin/activate

# Load the same env file the workers use (DB creds, provider keys, etc.)
POSTGRES_ENV_FILE="/root/clawd-backend/.env.postgres"
if [ -f "$POSTGRES_ENV_FILE" ]; then
    set -a
    source "$POSTGRES_ENV_FILE"
    set +a
fi

# Mark this process so the app can detect it's running in worker-API mode
# (useful if any route needs to skip main-only side effects in future).
export DREAMAGENT_ROLE=worker-api

# Start uvicorn serving the existing app on the internal port.
# workers=2 handles concurrent proxied requests (download + build/publish).
exec venv/bin/uvicorn app:app --host 0.0.0.0 --port 8003 --workers 2
