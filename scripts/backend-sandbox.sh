#!/bin/bash
# Backend sandbox wrapper — isolates uvicorn via bubblewrap (bwrap).
#
# Usage: backend-sandbox.sh <venv_path> <backend_path> <port> [entry_point]
#
# What the backend CAN see:
#   - Own backend/ directory (read-write)
#   - Shared venv (read-only)
#   - System libraries /usr /lib /bin (read-only)
#   - /tmp (tmpfs, ephemeral)
#   - localhost network (postgres, other services)
#
# What the backend CANNOT see:
#   - Other users' projects
#   - /root/clawd-backend (platform source + secrets)
#   - .env.postgres (DB passwords)
#   - Docker socket
#   - nginx/PM2 configs
#
# Requires: apt install -y bubblewrap

set -euo pipefail

VENV="${1:?Missing venv_path}"
PROJECT_DIR="${2:?Missing backend_path}"
PORT="${3:?Missing port}"
ENTRY="${4:-main:app}"

exec bwrap \
  --ro-bind / / \
  --bind "$PROJECT_DIR" "$PROJECT_DIR" \
  --ro-bind "$VENV" "$VENV" \
  --dev /dev \
  --proc /proc \
  --tmpfs /tmp \
  --share-net \
  --die-with-parent \
  -- \
  "$VENV/bin/uvicorn" "$ENTRY" \
  --host 0.0.0.0 \
  --port "$PORT"
