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

set -uo pipefail

VENV="${1:?Missing venv_path}"
PROJECT_DIR="${2:?Missing backend_path}"
PORT="${3:?Missing port}"
ENTRY="${4:-main:app}"

# Validate required inputs FIRST so subsequent debug logging can write.
if [ ! -d "$VENV" ]; then
  echo "FATAL: venv not found: $VENV" >&2
  exit 3
fi
if [ ! -d "$PROJECT_DIR" ]; then
  echo "FATAL: project dir not found: $PROJECT_DIR" >&2
  exit 4
fi
if ! command -v bwrap >/dev/null 2>&1; then
  echo "FATAL: bwrap not installed" >&2
  exit 5
fi

cd "$PROJECT_DIR" || {
  echo "FATAL: cannot cd to $PROJECT_DIR" >&2
  exit 2
}

# Debug log — write startup diagnostics so the "PM2-empty-logs" failure mode
# is diagnosable. Disable with SANDBOX_DEBUG=0 in env.
SANDBOX_DEBUG="${SANDBOX_DEBUG:-1}"
DEBUG_LOG="$PROJECT_DIR/.sandbox-debug.log"
if [ "$SANDBOX_DEBUG" = "1" ]; then
  {
    echo "=== backend-sandbox.sh $(date -Is) ==="
    echo "VENV=$VENV"
    echo "PROJECT_DIR=$PROJECT_DIR"
    echo "PORT=$PORT"
    echo "ENTRY=$ENTRY"
    echo "PWD=$(pwd)"
    echo "whoami=$(whoami 2>&1)"
    echo "args=$*"
    echo "DATABASE_URL_set=${DATABASE_URL:+yes}"
    echo "---"
  } >> "$DEBUG_LOG" 2>&1
fi

# On Debian 13, /lib /bin /sbin /lib64 are symlinks into /usr.
# We mount /usr (which contains everything) and recreate the symlinks
# at the sandbox root so ELF binaries can find their dynamic linker.
#
# NOTE: We intentionally do NOT use --die-with-parent. When PM2 spawns this
# script, PM2's launcher thread exits after fork/exec, which would trigger
# parent-death signal and kill the sandbox before uvicorn binds the port.
# PM2 itself owns the lifecycle (it restarts on crash, stops on delete).
#
# --unshare-pid gives the sandbox its own PID namespace so the backend
# cannot enumerate host processes via /proc. Without it, the backend can
# read /proc/<pid>/cmdline for every process on the worker VPS (Claude,
# PM2 workers, other users' containers) — a real leak vector. bwrap
# auto-launches an init process inside the new PID namespace (PID 1) that
# reaps zombies. The venv python + uvicorn workers all run as PIDs 2..N
# inside the namespace; host sees them via translated PIDs but backend
# sees ONLY its own processes.
BWRAP_ARGS=(
  --unshare-pid
  --share-net
  --dev /dev
  --proc /proc
  --tmpfs /tmp
  --bind "$PROJECT_DIR" "$PROJECT_DIR"
  --ro-bind "$VENV" "$VENV"
  --ro-bind /usr /usr
  --symlink usr/lib /lib
  --symlink usr/bin /bin
  --symlink usr/sbin /sbin
  --symlink usr/lib64 /lib64
  --ro-bind /etc/resolv.conf /etc/resolv.conf
  --ro-bind /etc/hosts /etc/hosts
)

# SSL certs for HTTPS
if [ -d /etc/ssl ]; then
  BWRAP_ARGS+=(--ro-bind /etc/ssl /etc/ssl)
fi
if [ -f /etc/ca-certificates.conf ]; then
  BWRAP_ARGS+=(--ro-bind /etc/ca-certificates.conf /etc/ca-certificates.conf)
fi

if [ "$SANDBOX_DEBUG" = "1" ]; then
  echo "--- preflight: test bwrap can spawn python+uvicorn ---" >> "$DEBUG_LOG" 2>&1
fi

# Preflight: verify the sandbox can actually import uvicorn from the venv.
# If this fails we get a clean error in the debug log + stderr instead of
# PM2 swallowing the failure and producing empty logs downstream.
PREFLIGHT=$(bwrap "${BWRAP_ARGS[@]}" -- "$VENV/bin/python3" -c 'import sys,uvicorn; print("py_ok", sys.version.split()[0], "uvicorn", uvicorn.__version__)' 2>&1)
PREFLIGHT_RC=$?
if [ "$SANDBOX_DEBUG" = "1" ]; then
  echo "preflight_rc=$PREFLIGHT_RC" >> "$DEBUG_LOG" 2>&1
  echo "preflight_out=$PREFLIGHT" >> "$DEBUG_LOG" 2>&1
fi
if [ "$PREFLIGHT_RC" != "0" ]; then
  echo "FATAL: bwrap preflight failed (rc=$PREFLIGHT_RC):" >&2
  echo "$PREFLIGHT" >&2
  exit 6
fi

if [ "$SANDBOX_DEBUG" = "1" ]; then
  echo "--- launching bwrap uvicorn on port $PORT ---" >> "$DEBUG_LOG" 2>&1
fi

# exec replaces this shell with bwrap. PM2 then tracks the bwrap process.
# Unbuffered python (-u) ensures uvicorn output flushes to PM2's log capture.
exec bwrap "${BWRAP_ARGS[@]}" \
  --setenv PYTHONPATH "$PROJECT_DIR" \
  --setenv PYTHONUNBUFFERED "1" \
  -- \
  "$VENV/bin/python3" -u -m uvicorn "$ENTRY" \
  --host 0.0.0.0 \
  --port "$PORT"
