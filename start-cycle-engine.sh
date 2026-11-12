#!/bin/bash
# Dev Cycle engine startup — same pattern as start-scheduler.sh.
cd /root/clawd-backend
source venv/bin/activate 2>/dev/null || true
# Source BOTH env files: .env has provider keys (ZAI/OpenRouter),
# .env.postgres has DB creds.
for ENV_FILE in /root/clawd-backend/.env /root/clawd-backend/.env.postgres; do
    if [ -f "$ENV_FILE" ]; then
        set -a
        source "$ENV_FILE" 2>/dev/null
        set +a
    fi
done
export USE_POSTGRES=true
exec python dev_cycle_engine.py
