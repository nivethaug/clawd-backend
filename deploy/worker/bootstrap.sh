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

echo "==> [1/5] Docker + host deps"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null || { echo "docker compose plugin missing"; exit 1; }
# rsync for artifact sync; openssh-client for the jump-host pulls
command -v rsync >/dev/null 2>&1 || apt-get update -qq && apt-get install -y -qq rsync openssh-client >/dev/null

echo "==> [2/5] Repo -> $WORKDIR"
mkdir -p "$WORKDIR"
if [ ! -d "$WORKDIR/clawd-backend/.git" ]; then
  git clone -b "$REPO_BRANCH" https://github.com/nivethaug/clawd-backend.git "$WORKDIR/clawd-backend"
else
  git -C "$WORKDIR/clawd-backend" fetch origin && git -C "$WORKDIR/clawd-backend" reset --hard "origin/$REPO_BRANCH"
fi

echo "==> [3/5] One-time host artifacts from the shared worker (via $MAIN_VPS)"
# /root/.claude (agent configs) and /root/dreampilot (website template + venv)
# are shared verbatim with project sandboxes — same absolute paths here.
SHARED_WORKER="${SHARED_WORKER:-187.55.225.39}"
mkdir -p /root/.claude /root/dreampilot /opt/wrapper
for ART in "/root/.claude" "/root/dreampilot"; do
  DST="$ART"
  if [ -z "$(ls -A "$DST" 2>/dev/null)" ]; then
    echo "    pulling $ART"
    ssh -o StrictHostKeyChecking=accept-new -J "root@$MAIN_VPS" "root@$SHARED_WORKER" \
      "tar -C $(dirname "$ART") -czf - $(basename "$ART")" | tar -C / -xz
  else
    echo "    $DST already populated — skipping"
  fi
done

# Wrapper-v2: pull SOURCE ONLY and build a fresh venv here. Python venvs are
# NOT relocatable (activate + shebangs hardcode the original path), so
# copying the shared worker's venv would break on import.
if [ -z "$(ls -A /opt/wrapper/src 2>/dev/null)" ]; then
  echo "    pulling wrapper source"
  ssh -o StrictHostKeyChecking=accept-new -J "root@$MAIN_VPS" "root@$SHARED_WORKER" \
    "tar -C /root -czf - wraper/src wraper/requirements.txt 2>/dev/null || tar -C /root -czf - wraper" \
    | tar -C /tmp -xz
  mkdir -p /opt/wrapper
  [ -d /tmp/wraper/src ] && cp -a /tmp/wraper/src /opt/wrapper/src
  [ -f /tmp/wraper/requirements.txt ] && cp -a /tmp/wraper/requirements.txt /opt/wrapper/
  rm -rf /tmp/wraper
  python3 -m venv /opt/wrapper/venv
  /opt/wrapper/venv/bin/pip install -q --upgrade pip
  /opt/wrapper/venv/bin/pip install -q -r /opt/wrapper/requirements.txt 2>/dev/null \
    || /opt/wrapper/venv/bin/pip install -q fastapi uvicorn httpx
  echo "    wrapper venv rebuilt at /opt/wrapper/venv"
else
  echo "    /opt/wrapper already populated — skipping"
fi

echo "==> [4/5] worker.env"
cd "$WORKDIR/clawd-backend/deploy/worker"
[ -f worker.env ] || cp worker.env.example worker.env
sed -i "s/^WORKER_NODE_ID=.*/WORKER_NODE_ID=$WORKER_NODE_ID/" worker.env
if ! grep -q '^DB_PASSWORD=..*' worker.env; then
  cat <<'EOF'
!! worker.env has an empty DB_PASSWORD (and possibly other secrets).
    Edit it now, then re-run this script to build and start.
EOF
  exit 1
fi

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
