#!/bin/bash
# Backend sandbox wrapper — isolates uvicorn via bubblewrap (bwrap).
#
# Usage: backend-sandbox.sh <venv_path> <backend_path> <port> [entry_point]
#
# What the backend CAN see:
#   - Own backend/ directory (read-write)
#   - Shared venv (read-only)
#   - System libraries: /usr /lib /bin /sbin (read-only)
#   - /etc/resolv.conf + /etc/hosts + /etc/ssl (DNS + TLS)
#   - /dev, /proc, /tmp
#   - localhost network (postgres, other services)
#
# What the backend CANNOT see:
#   - /root (platform source + secrets)
#   - /workspaces (other users)
#   - /etc/nginx, /etc/systemd (platform configs)
#   - /var/run/docker.sock
#   - Anything else on the host
#
# Requires: apt install -y bubblewrap

set -euo pipefail

VENV="${1:?Missing venv_path}"
PROJECT_DIR="${2:?Missing backend_path}"
PORT="${3:?Missing port}"
ENTRY="${4:-main:app}"

# Change to project dir BEFORE bwrap — bwrap inherits cwd from parent.
# Since $PROJECT_DIR is bind-mounted at the same path inside the sandbox,
# the cwd resolves correctly inside the namespace.
cd "$PROJECT_DIR"

# Build args dynamically — only mount directories that exist
# DO NOT mount / (rootfs) — that exposes everything.
# Only mount specific dirs needed for the backend to run.
BWRAP_ARGS=(
  --die-with-parent
  --share-net
  --dev /dev
  --proc /proc
  --tmpfs /tmp
  --bind "$PROJECT_DIR" "$PROJECT_DIR"
  --ro-bind "$VENV" "$VENV"
  --ro-bind /etc/resolv.conf /etc/resolv.conf
  --ro-bind /etc/hosts /etc/hosts
)

# Mount system libraries (different distros have different layouts)
# /usr/local is needed because the venv's python3.12 symlinks there
for dir in /usr /usr/local /lib /lib64 /bin /sbin; do
  if [ -d "$dir" ]; then
    BWRAP_ARGS+=(--ro-bind "$dir" "$dir")
  fi
done

# SSL certs for HTTPS from the backend
if [ -d /etc/ssl ]; then
  BWRAP_ARGS+=(--ro-bind /etc/ssl /etc/ssl)
fi
if [ -f /etc/ca-certificates.conf ]; then
  BWRAP_ARGS+=(--ro-bind /etc/ca-certificates.conf /etc/ca-certificates.conf)
fi

# Locale
if [ -d /usr/share/locale ]; then
  BWRAP_ARGS+=(--ro-bind /usr/share/locale /usr/share/locale)
fi

exec bwrap "${BWRAP_ARGS[@]}" \
  --setenv PYTHONPATH "$PROJECT_DIR" \
  -- \
  "$VENV/bin/uvicorn" "$ENTRY" \
  --host 0.0.0.0 \
  --port "$PORT"
