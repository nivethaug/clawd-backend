#!/bin/bash
# Certbot deploy hook — runs after every successful renewal of the
# dreamagent.cloud wildcard. Two jobs:
#   1. Sync the renewed certificate to the WORKER VPS (project subdomains
#      are served there) and reload its nginx.
#   2. Reload THIS host's nginx so the renewed cert is loaded into memory.
# Requires passwordless ssh to the worker (root@187.55.225.39).

set -u

WORKER="root@187.55.225.39"
LIVE_DIR="/etc/letsencrypt/live/dreamagent.cloud"

scp "$LIVE_DIR/fullchain.pem" "$LIVE_DIR/privkey.pem" \
    "$WORKER:/etc/letsencrypt/live/dreamagent.cloud/" \
    && ssh "$WORKER" "nginx -t && systemctl reload nginx" \
    && echo "[CERT-DEPLOY] worker cert synced + reloaded" \
    || echo "[CERT-DEPLOY] WARNING: worker sync failed — check manually"

systemctl reload nginx && echo "[CERT-DEPLOY] main nginx reloaded"
