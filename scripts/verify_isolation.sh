#!/bin/bash
# Verify bwrap sandbox isolation against the ACTUAL sandbox layout used by
# backend-sandbox.sh. Runs the in-sandbox probe (test_bwrap_isolation.py)
# with the exact same bwrap mounts a deployed backend sees, then reports
# PASS/FAIL for each isolation target.
#
# Usage:
#   scripts/verify_isolation.sh <backend_path> [venv_path]
#
# If venv_path is omitted, defaults to /root/dreampilot/dreampilotvenv.
#
# Exit code:
#   0 = all isolation checks passed (backend cannot escape)
#   1 = one or more isolation checks failed (BACKEND CAN READ SECRETS)
#
# What we verify the sandboxed backend CANNOT see:
#   - /root/clawd-backend/.env.postgres  (platform DB creds — POSTGRES_PASSWORD etc)
#   - /root/clawd-backend/app.py         (platform source)
#   - /root/.claude/                     (Claude settings + auth tokens)
#   - /etc/nginx/nginx.conf              (platform nginx config)
#   - /var/run/docker.sock               (docker socket — host compromise)
#   - /workspaces                        (other users' files)
#   - /root/.ssh                         (SSH keys — host compromise)
#   - /etc/postgresql                    (postgres config + hba)
#   - /root/dreampilot                   (other deployed projects)
#
# And CAN see (sanity):
#   - its own backend/ dir
#   - the shared venv (read-only)
#   - /usr (system libs)
#   - /etc/resolv.conf + /etc/hosts (DNS)

set -uo pipefail

BACKEND_PATH="${1:?Usage: verify_isolation.sh <backend_path> [venv_path]}"
VENV_PATH="${2:-/root/dreampilot/dreampilotvenv}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$BACKEND_PATH" ]; then
  echo "FATAL: backend_path not found: $BACKEND_PATH" >&2
  exit 2
fi
if [ ! -d "$VENV_PATH" ]; then
  echo "FATAL: venv not found: $VENV_PATH" >&2
  exit 2
fi
if ! command -v bwrap >/dev/null 2>&1; then
  echo "FATAL: bwrap not installed" >&2
  exit 2
fi

# Copy the test probe into the backend dir temporarily so it's visible
# inside the sandbox (only $BACKEND_PATH is bind-mounted).
PROBE_NAME=".isolation_probe.py"
cp "$SCRIPT_DIR/test_bwrap_isolation.py" "$BACKEND_PATH/$PROBE_NAME"
trap 'rm -f "$BACKEND_PATH/$PROBE_NAME"' EXIT

# Mirror the EXACT bwrap layout from backend-sandbox.sh so this test
# reflects what a deployed backend actually sees.
BWRAP_ARGS=(
  --unshare-pid
  --share-net
  --dev /dev
  --proc /proc
  --tmpfs /tmp
  --bind "$BACKEND_PATH" "$BACKEND_PATH"
  --ro-bind "$VENV_PATH" "$VENV_PATH"
  --ro-bind /usr /usr
  --symlink usr/lib /lib
  --symlink usr/bin /bin
  --symlink usr/sbin /sbin
  --symlink usr/lib64 /lib64
  --ro-bind /etc/resolv.conf /etc/resolv.conf
  --ro-bind /etc/hosts /etc/hosts
)
if [ -d /etc/ssl ]; then
  BWRAP_ARGS+=(--ro-bind /etc/ssl /etc/ssl)
fi
if [ -f /etc/ca-certificates.conf ]; then
  BWRAP_ARGS+=(--ro-bind /etc/ca-certificates.conf /etc/ca-certificates.conf)
fi

echo "================================================================"
echo "BWRAP ISOLATION VERIFICATION"
echo "  backend: $BACKEND_PATH"
echo "  venv:    $VENV_PATH"
echo "================================================================"

# Run the probe inside the sandbox. Use the venv's python3 like a real backend.
bwrap "${BWRAP_ARGS[@]}" \
  --setenv PYTHONPATH "$BACKEND_PATH" \
  -- \
  "$VENV_PATH/bin/python3" "$BACKEND_PATH/$PROBE_NAME" "$BACKEND_PATH"
RC=$?

echo "================================================================"
if [ "$RC" = "0" ]; then
  echo "OVERALL: PASS — sandbox isolates backend from host secrets"
else
  echo "OVERALL: FAIL — sandbox leaks secrets (rc=$RC)"
fi
echo "================================================================"
exit $RC
