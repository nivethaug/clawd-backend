#!/bin/bash
# Backend sandbox wrapper — isolates uvicorn via bubblewrap (bwrap).
#
# Usage: backend-sandbox.sh <venv_path> <backend_path> <port> [entry_point]
#
# What the backend CAN see:
#   - Own backend/ directory (read-write)
#   - Shared venv (read-only)
#   - System libraries under /usr (read-only, includes /lib /bin /sbin via symlinks)
#   - /etc/resolv.conf + /etc/hosts (DNS)
#   - /dev, /proc, /tmp
#   - localhost network (postgres, other services)
#
# What the backend CANNOT see:
#   - /root (platform source + secrets)
#   - /workspaces (other users)
#   - /etc/nginx, /etc/systemd (platform configs)
#   - /var/run/docker.sock
#
# Requires: apt install -y bubblewrap

set -euo pipefail

VENV="${1:?Missing venv_path}"
PROJECT_DIR="${2:?Missing backend_path}"
PORT="${3:?Missing port}"
ENTRY="${4:-main:app}"

cd "$PROJECT_DIR"

# On Debian 13, /lib /bin /sbin are symlinks into /usr. We must NOT
# mount them separately — only mount /usr (which contains everything).
# Also mount /lib64 (not a symlink on most x86_64 systems).
BWRAP_ARGS=(
  --die-with-parent
  --share-net
  --dev /dev
  --proc /proc
  --tmpfs /tmp
  --bind "$PROJECT_DIR" "$PROJECT_DIR"
  --ro-bind "$VENV" "$VENV"
  --ro-bind /usr /usr
  --ro-bind /etc/resolv.conf /etc/resolv.conf
  --ro-bind /etc/hosts /etc/hosts
)

# /lib64 is a real directory (not symlink) on x86_64 — needed for ld-linux
if [ -d /lib64 ] && [ ! -L /lib64 ]; then
  BWRAP_ARGS+=(--ro-bind /lib64 /lib64)
fi

# SSL certs for HTTPS
if [ -d /etc/ssl ]; then
  BWRAP_ARGS+=(--ro-bind /etc/ssl /etc/ssl)
fi
if [ -f /etc/ca-certificates.conf ]; then
  BWRAP_ARGS+=(--ro-bind /etc/ca-certificates.conf /etc/ca-certificates.conf)
fi

exec bwrap "${BWRAP_ARGS[@]}" \
  --setenv PYTHONPATH "$PROJECT_DIR" \
  -- \
  "$VENV/bin/python3" -m uvicorn "$ENTRY" \
  --host 0.0.0.0 \
  --port "$PORT"
