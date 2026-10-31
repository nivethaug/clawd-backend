# Dedicated Worker Image — the full worker stack in one container image.
#
# Runs as a "system container" (docker.sock + host network + SYS_ADMIN for
# bwrap user-namespace sandboxes) because the worker:
#   - spawns project containers on the HOST docker daemon (docker exec ...)
#   - must be reachable at localhost:7861 from project containers (host net)
#   - uses absolute paths (/workspaces, /root/.claude) shared with the host
#
# Build context = the clawd-backend repo root:
#   docker build -t clawd-worker -f deploy/worker/Dockerfile .

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ── System layer: everything the manual runbook installs ──────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-pip \
        nodejs npm \
        git curl wget ca-certificates gnupg lsb-release \
        bubblewrap util-linux \
        nginx-light certbot python3-certbot-nginx \
        docker.io \
        postgresql-client \
        acl \
        jq unzip \
        tini \
    && rm -rf /var/lib/apt/lists/*

# pnpm (build tooling for generated projects)
RUN npm install -g pnpm@latest && npm cache clean --force

# ── Backend layer ──────────────────────────────────────────────────────────
WORKDIR /opt/clawd-backend
COPY requirements.txt ./
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt
ENV PATH="/opt/venv/bin:${PATH}"

# App code (baked in; mount a fresh checkout over it for live updates)
COPY . /opt/clawd-backend

# dreampilot runtime dirs (template + venv are bind-mounted from the host —
# they are per-install artifacts shared with project sandboxes)
RUN mkdir -p /workspaces /root/.claude /root/dreampilot /var/log/clawd

# Non-root executor for generated code — matches the shared worker (uid 1001)
RUN useradd -m -u 1001 -s /bin/bash dreampilot \
    && usermod -aG sudo dreampilot \
    && echo 'dreampilot ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/dreampilot \
    && chmod 0440 /etc/sudoers.d/dreampilot

# Wrapper source is bind-mounted at /opt/wrapper (see docker-compose.yml) —
# the wrapper repo ships separately from the backend repo.

EXPOSE 8003 7861 80 443

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/bin/bash", "-c", "echo 'worker image — run via docker-compose services'"]
