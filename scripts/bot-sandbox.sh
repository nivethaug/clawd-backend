#!/bin/bash
# Bot sandbox wrapper — isolates Telegram/Discord bots via bubblewrap (bwrap).
#
# Usage: bot-sandbox.sh <venv_path> <bot_dir>
#
# What the bot CAN see:
#   - Own bot directory (read-write)
#   - Shared venv (read-only)
#   - System libraries under /usr (read-only)
#   - /etc/resolv.conf + /etc/hosts (DNS)
#   - /dev, /proc, /tmp
#   - localhost network + internet (for Telegram/Discord API calls)
#
# What the bot CANNOT see:
#   - /root (platform source + secrets)
#   - /workspaces (other users)
#   - /var/run/docker.sock
#
# Requires: apt install -y bubblewrap

set -euo pipefail

VENV="${1:?Missing venv_path}"
BOT_DIR="${2:?Missing bot_dir}"

cd "$BOT_DIR"

# On Debian 13, /lib /bin /sbin /lib64 are symlinks into /usr.
# NOTE: No --die-with-parent — PM2 owns lifecycle (see backend-sandbox.sh).
BWRAP_ARGS=(
  --share-net
  --dev /dev
  --proc /proc
  --tmpfs /tmp
  --bind "$BOT_DIR" "$BOT_DIR"
  --ro-bind "$VENV" "$VENV"
  --ro-bind /usr /usr
  --symlink usr/lib /lib
  --symlink usr/bin /bin
  --symlink usr/sbin /sbin
  --symlink usr/lib64 /lib64
  --ro-bind /etc/resolv.conf /etc/resolv.conf
  --ro-bind /etc/hosts /etc/hosts
)

# SSL certs
if [ -d /etc/ssl ]; then
  BWRAP_ARGS+=(--ro-bind /etc/ssl /etc/ssl)
fi
if [ -f /etc/ca-certificates.conf ]; then
  BWRAP_ARGS+=(--ro-bind /etc/ca-certificates.conf /etc/ca-certificates.conf)
fi

exec bwrap "${BWRAP_ARGS[@]}" \
  -- \
  "$VENV/bin/python" "$BOT_DIR/main.py"
