#!/usr/bin/env bash
# Dedicated Worker — one-shot bootstrap on a fresh Ubuntu 24.04 host.
#
# Usage:
#   MAIN_VPS=195.200.14.37 WORKER_NODE_ID=ent-1 bash bootstrap.sh
#
# What this does (mirrors WORKER_VPS_MIGRATION_RUNBOOK.md):
#   1. installs Docker (if missing)
#   2. clones the backend repo (branch container-migration by default)
#   3. pulls the one-time host artifacts from the shared worker via the
#      MAIN VPS jump host: /root/.claude, /root/dreampilot (template+venv),
#      /opt/wrapper (wrapper-v2 + its venv)
#   4. copies worker.env.example → worker.env (fill secrets BEFORE the build,
#      or edit afterwards and `docker compose up -d` again)
#   5. builds the image and brings the stack up
#
# Host firewall (do once, manually):
#   ufw default deny incoming
#   ufw allow from $MAIN_VPS to any port 22   # or your admin IP for 22
#   ufw allow from $MAIN_VPS to any port 8003
#   ufw allow 80,443/tcp                      # deployed project domains
#   ufw enable
# And on the MAIN VPS:
#   ufw allow from <THIS_WORKER_IP> to any port 5432

set -euo pipefail

MAIN_VPS="${MAIN_VPS:-195.200.14.37}"
WORKER_NODE_ID="${WORKER_NODE_ID:?set WORKER_NODE_ID, e.g. ent-1}"
REPO_BRANCH="${REPO_BRANCH:-container-migration}"
WORKDIR="${WORKDIR:-/opt/worker}"

echo "==> [1/5] Docker"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null || { echo "docker compose plugin missing"; exit 1; }

echo "==> [2/5] Repo -> $WORKDIR"
mkdir -p "$WORKDIR"
if [ ! -d "$WORKDIR/clawd-backend/.git" ]; then
  git clone -b "$REPO_BRANCH" https://github.com/nivethaug/clawd-backend.git "$WORKDIR/clawd-backend"
else
  git -C "$WORKDIR/clawd-backend" fetch origin && git -C "$WORKDIR/clawd-backend" reset --hard "origin/$REPO_BRANCH"
fi

echo "==> [3/5] One-time host artifacts from the shared worker (via $MAIN_VPS)"
# /root/.claude (agent configs), /root/dreampilot (website template + venv),
# /opt/wrapper (wrapper-v2 source + venv). These are shared verbatim with
# project sandboxes — they must live at the SAME absolute paths on this host.
mkdir -p /root/.claude /root/dreampilot /opt/wrapper
for ART in "/root/.claude:." "/root/dreampilot:." "/root/wraper:."; do
  SRC="${ART%%:*}"; : # wraper (sic) is the shared worker's wrapper dir
  DST="/opt/wrapper"
  [ "$SRC" = "/root/.claude" ] && DST="/root/.claude"
  [ "$SRC" = "/root/dreampilot" ] && DST="/root/dreampilot"
  if [ -z "$(ls -A "$DST" 2>/dev/null)" ]; then
    echo "    pulling $SRC -> $DST"
    ssh -o StrictHostKeyChecking=accept-new -J "root@$MAIN_VPS" "root@187.55.225.39" \
      "tar -C $(dirname "$SRC") -czf - $(basename "$SRC")" | tar -C / -xz
    # wrapper lands at /root/wraper — move into place with its venv
    if [ "$SRC" = "/root/wraper" ] && [ -d /root/wraper ]; then
      rsync -a /root/wraper/ "$DST"/ && rm -rf /root/wraper
    fi
  else
    echo "    $DST already populated — skipping"
  fi
done

echo "==> [4/5] worker.env"
cd "$WORKDIR/clawd-backend/deploy/worker"
[ -f worker.env ] || cp worker.env.example worker.env
sed -i "s/^WORKER_NODE_ID=.*/WORKER_NODE_ID=$WORKER_NODE_ID/" worker.env
grep -q '^DB_PASSWORD=.\+' worker.env || cat <<'EOF'
!! worker.env has an empty DB_PASSWORD (and possibly other secrets).
    Edit it now, then re-run this script to build and start.
EOF

echo "==> [5/5] Build + start"
docker compose build
docker compose up -d
docker compose ps

cat <<EOF

Worker stack is up. Next:
  1. Verify:  curl -s http://127.0.0.1:7861/health          (wrapper)
               docker compose logs session-chat-worker | tail (claims idle)
  2. From the MAIN VPS: curl -s http://<this-ip>:8003/health-adjacent-route
  3. Register the node (on main):
       POST /api/admin/workers {"id":"$WORKER_NODE_ID","name":"...","api_url":"http://<ip>:8003","server_ip":"<ip>","region":"eu","is_shared":false}
  4. It now appears in the dedicated-worker pool (Billing page card).
EOF
