#!/bin/bash
# Bot sandbox wrapper — isolates Telegram/Discord bots via bubblewrap (bwrap).
#
# Usage: bot-sandbox.sh <venv_path> <bot_dir>
#
# What the bot CAN see:
#   - Own bot directory (read-write)
#   - Shared venv (read-only)
#   - System libraries (read-only)
#   - /etc/resolv.conf + /etc/hosts + /etc/ssl
#   - /dev, /proc, /tmp
#   - Network (Telegram/Discord API + postgres)
#
# What the bot CANNOT see:
#   - /root (platform source + secrets)
#   - /workspaces (other users)
#   - Docker socket, nginx configs
#
# Requires: apt install -y bubblewrap

set -euo pipefail

VENV="${1:?Missing venv_path}"
BOT_DIR="${2:?Missing bot_dir}"

cd "$BOT_DIR"

BWRAP_ARGS=(
  --unshare-all
  --share-net
  --die-with-parent
  --dev /dev
  --proc /proc
  --tmpfs /tmp
  --bind "$BOT_DIR" "$BOT_DIR"
  --ro-bind "$VENV" "$VENV"
  --ro-bind /etc/resolv.conf /etc/resolv.conf
  --ro-bind /etc/hosts /etc/hosts
)

for dir in /usr /usr/local /lib /lib64 /bin /sbin; do
  if [ -d "$dir" ]; then
    BWRAP_ARGS+=(--ro-bind "$dir" "$dir")
  fi
done

if [ -d /etc/ssl ]; then
  BWRAP_ARGS+=(--ro-bind /etc/ssl /etc/ssl)
fi

exec bwrap "${BWRAP_ARGS[@]}" -- \
  "$VENV/bin/python" "$BOT_DIR/main.py"
