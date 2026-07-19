#!/bin/bash
# Frontend sandbox wrapper — isolates npx serve via bubblewrap (bwrap).
#
# Usage: frontend-sandbox.sh <frontend_path> <port>
#
# What the frontend server CAN see:
#   - Own frontend directory (read-only — only serves dist/)
#   - System libraries + node_modules (read-only)
#   - /tmp (tmpfs)
#   - localhost network (for HTTP serving)
#
# What the frontend server CANNOT see:
#   - Other users' projects
#   - /root/clawd-backend (platform source + secrets)
#   - Backend source code
#   - Docker socket
#
# Requires: apt install -y bubblewrap

set -euo pipefail

FRONTEND="${1:?Missing frontend_path}"
PORT="${2:?Missing port}"

cd "$FRONTEND"

exec bwrap \
  --ro-bind / / \
  --ro-bind "$FRONTEND" "$FRONTEND" \
  --dev /dev \
  --proc /proc \
  --tmpfs /tmp \
  --share-net \
  --die-with-parent \
  -- \
  npx serve -s dist -l "$PORT"
