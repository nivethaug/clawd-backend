#!/bin/bash
# Bot sandbox wrapper — isolates Telegram/Discord bots via bubblewrap (bwrap).
#
# Usage: bot-sandbox.sh <venv_path> <bot_dir>
#
# What the bot CAN see:
#   - Own bot directory (read-write)
#   - Shared venv (read-only)
#   - System libraries (read-only)
#   - /tmp (tmpfs)
#   - localhost network + internet (for Telegram/Discord API calls)
#
# What the bot CANNOT see:
#   - Other users' projects
#   - /root/clawd-backend (platform source + secrets)
#   - .env.postgres (DB passwords)
#   - Docker socket
#
# Requires: apt install -y bubblewrap

set -euo pipefail

VENV="${1:?Missing venv_path}"
BOT_DIR="${2:?Missing bot_dir}"

cd "$BOT_DIR"

exec bwrap \
  --ro-bind / / \
  --bind "$BOT_DIR" "$BOT_DIR" \
  --ro-bind "$VENV" "$VENV" \
  --dev /dev \
  --proc /proc \
  --tmpfs /tmp \
  --share-net \
  --die-with-parent \
  -- \
  "$VENV/bin/python" "$BOT_DIR/main.py"
