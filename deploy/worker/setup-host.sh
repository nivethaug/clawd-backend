#!/bin/bash
# Dedicated Worker — one-shot HOST-LEVEL setup (no Docker compose).
# Everything we learned from 15+ debugging iterations, applied up front.
# Run on a fresh Ubuntu 24.04 VPS with SSH access from main.

set -euo pipefail

MAIN_VPS="${MAIN_VPS:-195.200.14.37}"
SHARED_WORKER="${SHARED_WORKER:-187.55.225.39}"
WORKER_NODE_ID="${WORKER_NODE_ID:-ent-2}"
WORKER_IP="${WORKER_IP:?set WORKER_IP}"
DB_PASSWORD="${DB_PASSWORD:?set DB_PASSWORD}"
ZAI_KEY="${ZAI_KEY:?}"
OR_KEY="${OR_KEY:?}"
INTERNAL_SECRET="${INTERNAL_SECRET:?}"
NODE_SECRET="${NODE_SECRET:?}"

echo "==> [1/8] System packages + Node 22 + Docker"
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip python3.12-venv \
  git curl wget rsync bubblewrap nginx certbot python3-certbot-nginx \
  postgresql-client acl jq unzip sudo openssh-client >/dev/null
curl -fsSL https://deb.nodesource.com/setup_22.x | bash - >/dev/null 2>&1
apt-get install -y -qq nodejs >/dev/null
curl -fsSL https://get.docker.com | sh >/dev/null 2>&1
npm install -g pm2 @anthropic-ai/claude-code@2.1.27 pnpm >/dev/null 2>&1

echo "==> [2/8] Firewall"
ufw default deny incoming
ufw allow from $MAIN_VPS to any port 22 comment main
ufw allow from $MAIN_VPS to any port 8003 comment main-api
ufw allow 80,443/tcp
ufw --force enable

echo "==> [3/8] Host artifacts from shared worker (via main jump)"
mkdir -p /root/.claude /root/dreampilot /opt/wrapper /srv/cache /workspaces
chmod 777 /srv/cache
ssh -o StrictHostKeyChecking=accept-new -J root@$MAIN_VPS root@$SHARED_WORKER \
  "tar -C /root -czf - .claude dreampilot" | tar -C /root -xz
ssh -o StrictHostKeyChecking=accept-new -J root@$MAIN_VPS root@$SHARED_WORKER \
  "tar -C /root -czf - wraper/src" | tar -C /tmp -xz
cp -a /tmp/wraper/src /opt/wrapper/
rm -rf /tmp/wraper

echo "==> [4/8] Venvs"
# Bridge venv python3.12 symlink (shared worker's venv targets /usr/local/bin)
ln -sf /usr/bin/python3 /usr/local/bin/python3.12
# Backend venv
cd /opt && git clone -q https://github.com/nivethaug/clawd-backend.git worker
cd worker && git fetch -q origin main && git merge -q origin/main -m deploy
python3 -m venv /opt/worker/venv
/opt/worker/venv/bin/pip install -q --upgrade pip
/opt/worker/venv/bin/pip install -q -r requirements.txt requests sqlalchemy
# Wrapper venv
python3 -m venv /opt/wrapper/venv
/opt/wrapper/venv/bin/pip install -q fastapi uvicorn httpx

echo "==> [5/8] Environment file"
cat > /opt/worker/.env.postgres <<EOF
DB_HOST=$MAIN_VPS
DB_PORT=5432
DB_NAME=dreampilot
DB_USER=clawd_worker
DB_PASSWORD=$DB_PASSWORD
USE_POSTGRES=true
WORKER_NODE_ID=$WORKER_NODE_ID
EXECUTION_MODE=container
WORKSPACE_ROOT=/workspaces
INTERNAL_API_SECRET=$INTERNAL_SECRET
WORKER_INTERNAL_SECRET=$NODE_SECRET
TRUST_PROXY_AUTH=1
ZAI_API_KEY=$ZAI_KEY
OPENROUTER_API_KEY=$OR_KEY
SERVER_IP=$WORKER_IP
ANTHROPIC_BASE_URL=http://localhost:7861/anthropic-compat
ANTHROPIC_AUTH_TOKEN=$OR_KEY
ANTHROPIC_TIMEOUT=300000
CLAUDE_CODE_API_TIMEOUT=300000
EOF
cp /opt/worker/.env.postgres /opt/worker/.env

echo "==> [6/8] Nginx + certs + docker network + postgres container"
echo "server_names_hash_bucket_size 128;" > /etc/nginx/conf.d/00-hash.conf
systemctl start nginx && systemctl enable nginx
# Copy SSL certs
ssh -o StrictHostKeyChecking=accept-new -J root@$MAIN_VPS root@$SHARED_WORKER \
  "tar -C /etc -czf - letsencrypt" | tar -C /etc -xz
chmod -R 755 /etc/letsencrypt/live /etc/letsencrypt/archive
# Docker network for user containers
docker network create dreamagent-net 2>/dev/null || true
# Per-project postgres
docker run -d --name dreampilot-postgres --restart unless-stopped \
  -p 127.0.0.1:5432:5432 \
  -e POSTGRES_USER=admin -e POSTGRES_PASSWORD=StrongAdminPass123 -e POSTGRES_DB=defaultdb \
  postgres:15

echo "==> [7/8] Claude CLI config with timeout"
cat > /root/.claude/settings.json <<EOF
{
  "autoUpdaterStatus": "disabled",
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:7861/anthropic-compat",
    "ANTHROPIC_TIMEOUT": "300000",
    "CLAUDE_CODE_API_TIMEOUT": "300000"
  }
}
EOF

echo "==> [8/8] PM2 services (host-level, same as shared worker)"
# Wrapper
cd /opt/wrapper
ZAI_API_KEY=$ZAI_KEY OPENROUTER_API_KEY=$OR_KEY PYTHONPATH=/opt/wrapper/src \
  pm2 start /opt/wrapper/venv/bin/python --name clawd-wrapper -- \
  -m uvicorn wrapper_v2.api:app --host 0.0.0.0 --port 7861

# Worker API
cat > /opt/worker/start-api.sh <<'SCRIPT'
#!/bin/bash
source /opt/worker/.env.postgres
cd /opt/worker
exec /opt/worker/venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8003 --workers 2 --log-level info
SCRIPT
chmod +x /opt/worker/start-api.sh
pm2 start /opt/worker/start-api.sh --name clawd-worker-api

# Pollers (source env for all vars)
set -a; source /opt/worker/.env.postgres; set +a
cd /opt/worker
pm2 start /opt/worker/venv/bin/python --name clawd-session-chat-worker -- session_chat_worker.py
pm2 start /opt/worker/venv/bin/python --name clawd-project-creation-worker -- project_creation_worker.py

pm2 save
pm2 startup systemd -u root --hp /root >/dev/null 2>&1

echo "==> Verifying..."
sleep 10
curl -s -m 5 http://127.0.0.1:7861/health | head -c 30; echo
curl -s -m 5 -o /dev/null -w "api:%{http_code}\n" http://127.0.0.1:8003/models
pm2 ls --no-color | grep -c online
echo "SETUP COMPLETE"
