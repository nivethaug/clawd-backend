# Worker VPS Setup Guide

> **Authoritative, step-by-step reference** for provisioning a new worker VPS that runs the
> full project-creation pipeline (AI generation + deploy + serving) independently of the main API VPS.
>
> Distilled from a real migration (July 2026). Every "Gotcha" below is a problem we actually hit —
> read them before you start, not after.
>
> Companion docs:
> - [worker_vps_migration.md](./worker_vps_migration.md) — architecture and rationale
> - `VALIDATION_worker_vps_migration.md` (repo root) — validation of the plan against the code
> - `WORKER_VPS_REQUIREMENTS.md` (repo root) — requirements checklist by layer

---

## Architecture (two-VPS split)

| | Main VPS | Worker VPS |
|---|---|---|
| **Role** | Public API, frontend, webhooks, auth, billing | AI generation + project deploy + serving |
| **Runs** | `clawd-backend` (FastAPI), frontend static, Telegram/Discord/Slack webhooks | `clawd-session-chat-worker`, `clawd-project-creation-worker`, `wrapper-v2` (Claude proxy), Chrome (devtools), per-project PM2 + nginx |
| **Postgres** | `dreampilot` DB — the **master/app DB** (users, projects, billing, sessions, credits) | `dreampilot-postgres` container — **one DB per project** (tenant data) |
| **Project files** | (legacy projects, if any) | `/root/dreampilot/projects/{type}/{id}_{name}_{ts}/` |
| **Public traffic** | `dreamagent.cloud`, `api.dreamagent.cloud` | `{project}.dreamagent.cloud`, `{project}-api.dreamagent.cloud` (per-project A records) |

The worker polls the master DB (on main) for queued runs via `FOR UPDATE SKIP LOCKED`, executes them
locally (Claude + build + deploy), and writes results back. Users never talk to the worker directly
for the API — only for deployed project sites.

---

## Phase 0 — Preconditions on the main VPS

Before provisioning the worker, the main VPS must expose postgres to the worker:

```bash
# 1. Rebind postgres container to 0.0.0.0 (was 127.0.0.1)
docker stop dreampilot-postgres && docker rm dreampilot-postgres
docker run -d --name dreampilot-postgres --restart unless-stopped \
  -p 0.0.0.0:5432:5432 -v dreampilot_pgdata:/var/lib/postgresql/data \
  -e POSTGRES_USER=admin -e POSTGRES_PASSWORD='<DB_PASSWORD>' -e POSTGRES_DB=defaultdb \
  postgres:15

# 2. Firewall: allow ONLY the worker's IP
ufw allow from <WORKER_IP> to any port 5432 proto tcp
```

> ⚠️ **Hostinger cloud firewall:** UFW is OS-level. If the VPS provider has a separate cloud firewall
> in its panel, open 5432 there too (to the worker IP only). Verify from the worker before proceeding.

---

## Phase 1 — Base system (on the worker)

### 1.1 OS + build tools

```bash
apt update && apt upgrade -y
apt install -y python3 python3-venv python3-dev build-essential libpq-dev git nginx curl ufw \
  postgresql-client rsync acl
```

### 1.2 Python 3.12 (MUST match main exactly)

> 🚨 **Gotcha #1 — Python version mismatch breaks everything.**
> Main runs Python 3.12.x. If the worker's default `python3` is a different version (e.g. Debian 13
> ships 3.13), compiled wheels (`psycopg2-binary`, `pydantic-core`) built on 3.12 will fail to import
> on the worker. **Build Python 3.12 from source** to match main. Do NOT use `--enable-optimizations`
> (it runs the test suite twice and takes 10+ min; unnecessary for a worker).

```bash
apt install -y wget libssl-dev zlib1g-dev libncursesw5-dev libreadline-dev libsqlite3-dev \
  libffi-dev libbz2-dev liblzma-dev uuid-dev libgdbm-dev
cd /usr/src
wget https://www.python.org/ftp/python/3.12.3/Python-3.12.3.tgz
tar xzf Python-3.12.3.tgz && cd Python-3.12.3
./configure            # NO --enable-optimizations
make -j$(nproc)
make altinstall        # installs /usr/local/bin/python3.12, does NOT touch system python3
python3.12 --version   # must print Python 3.12.3
```

### 1.3 Node + pnpm (match main versions)

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
apt install -y nodejs
npm install -g pnpm@10
node -v; pnpm -v
```

### 1.4 Docker (for the per-project postgres container)

> 🚨 **Gotcha #2 — Debian's `docker.io` package is often absent or stale.** Use the Docker CE repo.

```bash
apt install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
```

---

## Phase 2 — Users, permissions, paths

### 2.1 The `dreampilot` user

Claude Code runs as `dreampilot` (NOT root) for isolation — it has full filesystem/code access via
`--dangerously-skip-permissions`, so it must not be root.

```bash
useradd -u 1001 -m -G sudo,users -s /bin/bash dreampilot
echo 'dreampilot ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/dreampilot
chmod 440 /etc/sudoers.d/dreampilot
visudo -c   # must print "parsed OK"
usermod -aG docker dreampilot
```

> ⚠️ **Security note:** `NOPASSWD:ALL` is broad (matches main). For tighter isolation later, restrict
> this to only the commands Claude actually needs. Out of scope for initial migration.

### 2.2 Project tree + traversal

> 🚨 **Gotcha #3 — `/root` is `0700` by default; dreampilot can't traverse into `/root/dreampilot/...`.**

```bash
mkdir -p /root/dreampilot/projects/{website,telegram,discord,scheduler}
mkdir -p /root/dreampilot/dreampilotvenv
chown -R dreampilot:dreampilot /root/dreampilot
chmod 711 /root     # traversable by dreampilot, not listable

# Verify dreampilot can reach + write
sudo -u dreampilot ls /root/dreampilot/projects/website
sudo -u dreampilot bash -c 'touch /root/dreampilot/projects/website/.test && rm /root/dreampilot/projects/website/.test && echo WRITE_OK'
```

---

## Phase 3 — Code + Python venvs

### 3.1 Clone the backend

```bash
cd /root
gh repo clone nivethaug/clawd-backend   # or git clone + PAT
cd clawd-backend
git checkout <release-branch>
```

### 3.2 Worker venv (Python 3.12, explicit interpreter)

> 🚨 **Gotcha #4 — always create venvs with `python3.12` explicitly**, never bare `python3`
> (which may be 3.13 on Debian). And use the venv's absolute `pip` path when installing, so you
> never accidentally install into the wrong venv.

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
# Undeclared deps used by the worker code path (NOT in requirements.txt):
pip install requests sqlalchemy
```

### 3.3 Shared project venv (for deployed project backends)

> 🚨 **Gotcha #5 — the hardcoded path `/root/dreampilot/dreampilotvenv`.**
> `infrastructure_manager.py:97` sets `SHARED_VENV_PATH = "/root/dreampilot/dreampilotvenv"`. Every
> deployed project backend's PM2 config runs uvicorn from this venv. It MUST exist at that exact path
> with the full dep set project backends import.
>
> 🚨 **Gotcha #6 — do NOT create this venv inside a dir containing a `logging.py`** (or any module
> that shadows stdlib). `python -m venv` imports stdlib `logging` during creation; a local `logging.py`
> breaks it with `AttributeError: module 'logging' has no attribute 'getLogger'`. Create from `/root`.

The shared venv needs the **full** set of packages main's shared venv has (project backends import
many: anthropic, sqlalchemy, browser-use, apscheduler, etc.). The fastest, parity-guaranteed way is
to **rsync main's venv** (same OS arch + same Python version = binary-compatible):

```bash
# On MAIN VPS — copy the shared venv, EXCLUDING broken ~-prefixed installs
rsync -avz --delete --exclude='~*' --exclude='__pycache__' \
  /root/dreampilot/dreampilotvenv/ root@<WORKER_IP>:/root/dreampilot/dreampilotvenv/
```

Then **on the worker**, repoint the venv's Python symlinks at the local 3.12.3:

> 🚨 **Gotcha #7 — rsync'd venv symlinks point at the SOURCE machine's Python.** Main (Ubuntu) has
> `/usr/bin/python3` = 3.12.3; the worker (Debian 13) has `/usr/bin/python3` = 3.13.5. The copied
> venv's `bin/python3.12 → python3 → /usr/bin/python3` resolves to 3.13.5 on the worker, and all
> 3.12-compiled C extensions fail to load. **Repoint the symlinks + `pyvenv.cfg` at
> `/usr/local/bin/python3.12`** (the source-built 3.12.3).

```bash
cd /root/dreampilot/dreampilotvenv/bin
rm -f python python3 python3.12
ln -s /usr/local/bin/python3.12 python3.12
ln -s python3.12 python3
ln -s python3.12 python

cat > /root/dreampilot/dreampilotvenv/pyvenv.cfg <<'EOF'
home = /usr/local/bin
include-system-site-packages = false
version = 3.12.3
executable = /usr/local/bin/python3.12
command = /usr/local/bin/python3.12 -m venv /root/dreampilot/dreampilotvenv
EOF

# Verify
/root/dreampilot/dreampilotvenv/bin/python3.12 --version   # Python 3.12.3
/root/dreampilot/dreampilotvenv/bin/uvicorn --version
/root/dreampilot/dreampilotvenv/bin/python3.12 -c "import fastapi, uvicorn, sqlalchemy, psycopg2, anthropic, openai; print('FULL PARITY')"
```

---

## Phase 4 — Claude Code + the proxy

### 4.1 Install Claude Code (match main version)

```bash
npm install -g @anthropic-ai/claude-code@<main's-version>   # e.g. 2.1.83
claude --version
sudo -u dreampilot claude --version   # dreampilot can invoke it
```

### 4.2 Claude settings (global, shared via symlink)

Claude routes all calls through the local `wrapper-v2` proxy (not Anthropic directly). Configure
this in `/etc/claude/settings.json` and symlink it into dreampilot's home:

```bash
mkdir -p /etc/claude
cat > /etc/claude/settings.json <<'EOF'
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:7861/anthropic-compat",
    "ANTHROPIC_AUTH_TOKEN": "<OPENROUTER_KEY>",
    "ANTHROPIC_API_KEY": "",
    "ANTHROPIC_MODEL": "z-ai/glm-4.7-flash",
    "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "true"
  },
  "mcpServers": {
    "zai-mcp-server": {
      "type": "stdio", "command": "npx", "args": ["-y", "@z_ai/mcp-server"],
      "env": { "Z_AI_API_KEY": "<ZAI_KEY>", "Z_AI_MODE": "ZAI" }
    },
    "chrome-devtools": {
      "type": "stdio", "command": "npx",
      "args": ["-y", "chrome-devtools-mcp@latest", "--browserUrl", "http://127.0.0.1:9222"]
    }
  }
}
EOF
chmod 600 /etc/claude/settings.json

mkdir -p /home/dreampilot/.claude
ln -sf /etc/claude/settings.json /home/dreampilot/.claude/settings.json
chown -R dreampilot:dreampilot /home/dreampilot/.claude
```

> 🚨 **Gotcha #8 — Claude 2.1.83 gates everything behind a one-time login, even with
> `ANTHROPIC_AUTH_TOKEN` set.** A fresh install says "Not logged in". The login state lives in
> `~/.claude.json` (fields `userID`, `hasCompletedOnboarding`). **Copy `.claude.json` from main**
> (it's config state, not credentials — the actual auth token is in settings.json):
> `scp main:/home/dreampilot/.claude.json worker:/home/dreampilot/.claude.json` then `chown dreampilot:dreampilot`.

> 🚨 **Gotcha #9 — `--dangerously-skip-permissions` refuses to run as root.** Claude invokes must be
> as the dreampilot user. The worker handles this: `claude_code_agent.py:808` wraps with
> `sudo -E -H -u dreampilot`. Verify env propagation: `ANTHROPIC_AUTH_TOKEN=test sudo -E -H -u dreampilot bash -c 'echo $ANTHROPIC_AUTH_TOKEN'` must print `test`.

### 4.3 The wrapper-v2 proxy (`:7861`)

> 🚨 **Gotcha #10 — package layout matters.** `wrapper_v2` uses relative imports (`from .logging`),
> so it MUST be imported as a package (`wrapper_v2.api:app`), with `PYTHONPATH` pointing at the
> **parent** dir. If `PYTHONPATH` points at the package dir itself, `wrapper_v2/logging.py` shadows
> stdlib `logging` and crashes on startup.

Clone to `/root/wraper/` (matching main's layout), build the venv from `/root` (to avoid the
`logging.py` shadow during venv creation), install `uvicorn fastapi httpx pydantic`:

```bash
cd /root && python3.12 -m venv /root/wraper/venv
/root/wraper/venv/bin/pip install uvicorn fastapi httpx pydantic
cd /root/wraper && pm2 start ecosystem.config.js && pm2 save
```

The ecosystem config: `cwd: "/"`, `PYTHONPATH: "/root/wraper/src"`,
`args: "-m uvicorn wrapper_v2.api:app --host 0.0.0.0 --port 7861"`.

Verify: `curl -s http://localhost:7861/` returns HTTP 404 (alive — no route at `/`).

---

## Phase 5 — Project postgres (per-project DBs)

> The worker runs its OWN postgres container for **project tenant databases**. This is separate from
> the master `dreampilot` DB on main. `_execute_sql` uses `docker exec dreampilot-postgres psql ...`,
> so the container MUST be named `dreampilot-postgres` with matching credentials.

```bash
docker volume create dreampilot_pgdata_worker
docker run -d --name dreampilot-postgres --restart unless-stopped \
  -p 5432:5432 -v dreampilot_pgdata_worker:/var/lib/postgresql/data \
  -e POSTGRES_USER=admin -e POSTGRES_PASSWORD='<DB_PASSWORD>' -e POSTGRES_DB=defaultdb \
  postgres:15

# THE test — this is the exact command _execute_sql runs in Phase 6
docker exec dreampilot-postgres psql -U admin -d postgres -c "SELECT 1;"
```

> ⚠️ The password MUST match `DB_PASSWORD` in the worker's `.env.postgres` (which the workers use to
> reach the **master** DB on main). Same value, two purposes — keep them in sync on rotation.

---

## Phase 6 — Chrome (for the devtools MCP verification phase + scraping API)

Claude uses the `chrome-devtools` MCP to verify built sites. The platform
also runs a web scraping API (`/internal/scrape`) that uses Chrome to render
pages. Chrome needs to run headless with remote debugging on port 9222.

### Worker VPS: Chrome for chat verification

The worker VPS Chrome is used by Claude's MCP during chat/project creation
to verify built frontends. Each Docker container connects to it via the
Docker bridge gateway (`172.17.0.1:9223`).

```bash
# Install Chrome (worker VPS — for Claude chat verification)
wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
apt install -y /tmp/chrome.deb && rm /tmp/chrome.deb

# Systemd service (runs as dreampilot, matches main)
cat > /etc/systemd/system/chrome-devtools.service <<'EOF'
[Unit]
Description=Chrome DevTools Headless
After=network.target

[Service]
User=dreampilot
Group=dreampilot
ExecStart=/usr/bin/google-chrome --headless=new --no-sandbox --disable-dev-shm-usage \
  --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 \
  --user-data-dir=/tmp/context-chrome-debug about:blank
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now chrome-devtools.service
curl -s http://127.0.0.1:9222/json/version | head -1   # JSON with "Browser": "Chrome/..."
```

### Main VPS: Chrome Headless Shell (for scraping API)

The main VPS runs Chrome Headless Shell for the `/internal/scrape` endpoint.
This is a lighter build (~50MB) with no GUI code — purpose-built for
headless automation. Scheduler jobs and bots call this via the API.

```bash
# Install Chrome Headless Shell (main VPS — for /internal/scrape)
cd /tmp
JSON=$(curl -s https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions-with-downloads.json)
URL=$(echo "$JSON" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for x in d['channels']['Stable']['downloads']['chrome-headless-shell']:
    if 'linux' in x.get('platform', ''):
        print(x['url'])
        break
")
wget -q "$URL" -O chromium.zip
unzip -q chromium.zip -d /opt/
ln -sf /opt/chrome-headless-shell-linux64/chrome-headless-shell /usr/bin/chromium
chmod +x /opt/chrome-headless-shell-linux64/chrome-headless-shell

# Install required shared libraries
apt install -y unzip libnss3 libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 \
  libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
  libgbm1 libpango-1.0-0 libasound2t64

# Verify
/usr/bin/chromium --version

# Systemd service
cat > /etc/systemd/system/chrome-devtools.service <<'EOF'
[Unit]
Description=Chrome Headless Shell (DevTools + scraping API)
After=network.target

[Service]
ExecStart=/usr/bin/chromium --no-sandbox --disable-dev-shm-usage \
  --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome-debug-profile about:blank
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now chrome-devtools
sleep 3
curl -s http://127.0.0.1:9222/json/version | python3 -m json.tool

# Test the scraping endpoint
curl -s -X POST http://localhost:8002/internal/scrape \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","extract_js":"return document.title"}' | python3 -m json.tool
# Expected: {"success": true, "data": "Example Domain", "rendered": false}
```

---

## Phase 7 — SSL certificate + nginx

### 7.1 Copy the wildcard cert from main

> 🚨 **Gotcha #11 — wildcard cert covers the apex via SAN, but renewal needs the original method.**
> The `*.dreamagent.cloud` cert includes `dreamagent.cloud` as a SAN, so one cert covers everything.
> Copy `live/` + `archive/` + `renewal/` from main. If main used `authenticator = manual` (DNS-01),
> **neither VPS auto-renews** — schedule a manual renewal before expiry, or switch to an automated
> DNS plugin (`dns-cloudflare` etc.) if your DNS provider supports it.

```bash
# On MAIN VPS
ssh root@<WORKER_IP> 'mkdir -p /etc/letsencrypt/live/dreamagent.cloud /etc/letsencrypt/archive/dreamagent.cloud /etc/letsencrypt/renewal'
rsync -avz /etc/letsencrypt/live/dreamagent.cloud/ root@<WORKER_IP>:/etc/letsencrypt/live/dreamagent.cloud/
rsync -avz /etc/letsencrypt/archive/dreamagent.cloud/ root@<WORKER_IP>:/etc/letsencrypt/archive/dreamagent.cloud/
rsync -avz /etc/letsencrypt/renewal/dreamagent.cloud.conf root@<WORKER_IP>:/etc/letsencrypt/renewal/
```

```bash
# On WORKER
apt install -y certbot
chown -R root:root /etc/letsencrypt/
chmod -R 700 /etc/letsencrypt/live/ /etc/letsencrypt/archive/
nginx -t   # must pass — proves nginx can read the cert
```

### 7.2 DNS — per-project A records (NOT a wildcard move)

> 🚨 **Gotcha #12 — there is NO wildcard DNS record to "move".** Each project gets an explicit A
> record created at deploy time by `dns_manager` via the Hostinger API. The record's IP comes from
> `SERVER_IP` (`domain_config.py:23`). **Set `SERVER_IP` to the worker's IP** so new projects
> deployed on the worker get records pointing at the worker automatically.

```bash
# In the worker's .env.postgres
echo "SERVER_IP=<WORKER_IP>" >> /root/clawd-backend/.env.postgres
```

Keep `dreamagent.cloud` and `api.dreamagent.cloud` as explicit records → main. New project records
→ worker. No wildcard precedence conflicts.

---

## Phase 8 — Worker `.env.postgres`

The workers read `.env.postgres` from disk (via `load_dotenv`), NOT a PM2 env block. Create it:

```env
# Master DB (on MAIN VPS — reached over the network)
DB_HOST=<MAIN_VPS_IP>
DB_PORT=5432
DB_NAME=dreampilot
DB_USER=admin
DB_PASSWORD=<DB_PASSWORD>
USE_POSTGRES=true

# Worker's own IP — project DNS A records point here
SERVER_IP=<WORKER_IP>

# AI providers
ANTHROPIC_BASE_URL=http://localhost:7861/anthropic-compat
ANTHROPIC_AUTH_TOKEN=<OPENROUTER_KEY>
ANTHROPIC_MODEL=z-ai/glm-4.7-flash
ZAI_API_KEY=<ZAI_KEY>
OPENROUTER_API_KEY=<OPENROUTER_KEY>

# Build/publish
HOSTINGER_API_TOKEN=<HOSTINGER_TOKEN>
GITHUB_TOKEN=<GITHUB_TOKEN>

# Sentry (use a VALID DSN — must contain @o<org>.ingest.sentry.io)
SENTRY_DSN=<VALID_DSN>
SENTRY_ENVIRONMENT=production
```

> 🚨 **Gotcha #13 — do NOT copy secrets between machines without rotating.** The `.claude.json` and
> any copied config may contain old keys. Rotate DB password, OpenRouter, ZAI, Hostinger, GitHub,
> and Sentry DSN at their providers, then update both VPSes, then revoke the old values.

> 🚨 **Gotcha #14 — PM2 env quirks.** `pm2 restart` does NOT pick up ecosystem file changes; use
> `pm2 reload <file> --update-env`. `pm2 set name:KEY val` doesn't survive plain restarts. For the
> workers, `.env.postgres` is the durable source (re-sourced every start), so prefer it over PM2 env.

---

## Phase 9 — Start the workers

```bash
cd /root/clawd-backend
pm2 start session_chat_worker.py --name clawd-session-chat-worker \
  --interpreter /root/clawd-backend/venv/bin/python3.12
pm2 start project_creation_worker.py --name clawd-project-creation-worker \
  --interpreter /root/clawd-backend/venv/bin/python3.12
pm2 save
pm2 startup systemd   # run the command it prints
```

Verify health:
```bash
pm2 logs clawd-session-chat-worker --lines 30 | grep -iE "STARTUP-ENV|started worker_id|ERROR"
# Expect: [SESSION-WORKER] started worker_id=<worker-hostname>:<pid>
# Expect: [STARTUP-ENV] Sentry ENABLED (if DSN is valid)
```

---

## Phase 10 — Validate end-to-end

Create a project from the UI. Watch the pipeline:

```bash
pm2 logs clawd-project-creation-worker --lines 250 | \
  grep -iE "claimed|ownership|Phase|ACPX|BUILD|DEPLOY|Backend service started|A record|completed|failed"
```

Expected phase sequence (all must pass):
1. `claimed run=N` — worker picked it up
2. `ownership transferred to dreampilot` — the `_fix_project_ownership` fix ran
3. `ACPX: completed` — Claude generated the frontend (~2-6 min)
4. `Phase 6 Service Setup` — `✓ Backend service started` (uvicorn from shared venv)
5. `Phase 7 Deploy` — `Creating A record: <project>.dreamagent.cloud → <WORKER_IP>`
6. `completed`

Then verify the site is live:
```bash
dig +short <project>.dreamagent.cloud          # → worker IP
curl -sk https://<project>.dreamagent.cloud/ -w "\nHTTP %{http_code}\n" -o /dev/null   # 200
```

---

## The complete gotcha index (quick reference)

| # | Gotcha | Fix |
|---|---|---|
| 1 | Python version mismatch breaks compiled wheels | Build 3.12 from source, no `--enable-optimizations` |
| 2 | Debian `docker.io` absent/stale | Use Docker CE repo |
| 3 | `/root` is 0700; dreampilot can't traverse | `chmod 711 /root` |
| 4 | Bare `python3` may be wrong version | Always `python3.12 -m venv` |
| 5 | Shared venv path is hardcoded | `/root/dreampilot/dreampilotvenv` must exist |
| 6 | `logging.py` shadows stdlib during venv creation | Create venv from `/root`, not inside the package |
| 7 | rsync'd venv symlinks point at source's Python | Repoint at local `/usr/local/bin/python3.12` + fix `pyvenv.cfg` |
| 8 | Claude 2.1.83 requires one-time login | Copy `.claude.json` from main (config state, not creds) |
| 9 | `--dangerously-skip-permissions` refuses root | Run claude as dreampilot via `sudo -E -H -u` |
| 10 | `PYTHONPATH` at package dir shadows stdlib | Point at the parent, import as a package |
| 11 | Wildcard cert renewal needs original method | Manual DNS-01, or switch to automated DNS plugin |
| 12 | No wildcard DNS record exists | Per-project A records via `SERVER_IP` env var |
| 13 | Copied configs contain old keys | Rotate at providers, update both VPSes, revoke old |
| 14 | PM2 env doesn't survive plain restart | Use `.env.postgres` (re-sourced each start) |

---

## Rollback

DB-backed claiming makes rollback safe — stop the worker VPS processes, start main's workers:

```bash
# Worker VPS
pm2 stop clawd-session-chat-worker clawd-project-creation-worker

# Main VPS
pm2 start clawd-session-chat-worker clawd-project-creation-worker
```

`recover_stale_runs` on main's next startup cleans up any `interrupted` runs (20-min heartbeat timeout).

---

## Operational notes

- **One worker per queue** until multi-worker load-testing is done.
- **Provider tokens on the worker should be rotated independently** from main (a worker compromise
  shouldn't expose the API's tokens).
- **Sentry:** keep `SENTRY_DSN` on the worker, tagged by service (`session-chat-worker` /
  `project-creation-worker`). Worker errors land in the same Sentry project.
- **Project DBs** live on the worker's postgres container (tenant isolation); the master `dreampilot`
  DB stays on main (single source of truth). Keep `DB_PASSWORD` in sync between the worker's
  `.env.postgres` (master access) and the worker's postgres container env.
- **PM2 logs stay on** — Sentry is for errors, not a replacement for operational logs.
- **Postgres is the source of truth** for run state. If the worker dies, no work is lost — only delayed.
