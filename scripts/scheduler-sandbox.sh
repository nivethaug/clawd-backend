#!/bin/bash
# Scheduler executor sandbox — isolates a single execute_task(job) call via bwrap.
#
# Usage: scheduler-sandbox.sh <venv_path> <project_path>
#
# Protocol:
#   stdin  : one line of JSON — the job dict
#   stdout : one line of JSON — the result dict ({"status":..., "message":...})
#   stderr : human-readable diagnostics (forwarded to scheduler logs)
#   exit 0 : result line written (status may be "success" OR "failed")
#   exit 1 : runner failure (sandbox couldn't load executor, runner panic)
#
# What the executor CAN see:
#   - Own project directory (read-write — same as bot-sandbox.sh)
#   - Shared venv (read-only)
#   - System libraries under /usr (read-only)
#   - /etc/resolv.conf + /etc/hosts + /etc/ssl (DNS + TLS for outbound fetches)
#   - /dev, /proc (own PID namespace), /tmp (tmpfs)
#   - localhost network + internet (for API calls the executor makes)
#
# What the executor CANNOT see:
#   - /root (platform source + DATABASE_URL + secrets)
#   - /workspaces (other users)
#   - /var/run/docker.sock
#   - Host process table (own PID namespace → can't enumerate host PIDs)
#
# Why not --die-with-parent: same reason as backend-sandbox.sh / bot-sandbox.sh —
# the parent that calls subprocess.run is a thread inside the scheduler daemon,
# not a true parent process, so parent-death signals fire prematurely.
# The scheduler enforces timeout externally via subprocess.run(timeout=...).
#
# Requires: apt install -y bubblewrap

set -uo pipefail

VENV="${1:?Missing venv_path}"
PROJECT_DIR="${2:?Missing project_path}"

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

# Debug log — disable with SANDBOX_DEBUG=0 in env. Same convention as
# backend-sandbox.sh so failures are diagnosable when scheduler jobs vanish.
SANDBOX_DEBUG="${SANDBOX_DEBUG:-1}"
DEBUG_LOG="$PROJECT_DIR/.scheduler-sandbox-debug.log"
if [ "$SANDBOX_DEBUG" = "1" ]; then
  {
    echo "=== scheduler-sandbox.sh $(date -Is) ==="
    echo "VENV=$VENV"
    echo "PROJECT_DIR=$PROJECT_DIR"
    echo "PWD=$(pwd)"
    echo "whoami=$(whoami 2>&1)"
    echo "---"
  } >> "$DEBUG_LOG" 2>&1
fi

# Same mount conventions as bot-sandbox.sh / backend-sandbox.sh:
# - --unshare-pid: own PID namespace. bwrap spawns an init (PID 1) that reaps
#   zombies. Host process table is invisible → executor cannot read
#   /proc/<host_pid>/cmdline to find DATABASE_URL-holding processes.
# - --share-net: keep localhost (for the executor's API calls) + internet.
# - --bind PROJECT_DIR rw: executor.py and services/ live here; executor may
#   also write log/cache files inside its own project dir.
# - --ro-bind VENV: shared venv (requests, sqlalchemy, etc.) — read-only.
# - --ro-bind /usr + symlinks: dynamic linker + libc + ca-certificates.
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

# SSL certs for HTTPS fetches (executor's requests/smtplib need these).
if [ -d /etc/ssl ]; then
  BWRAP_ARGS+=(--ro-bind /etc/ssl /etc/ssl)
fi
if [ -f /etc/ca-certificates.conf ]; then
  BWRAP_ARGS+=(--ro-bind /etc/ca-certificates.conf /etc/ca-certificates.conf)
fi

# Runner lives next to this script. It reads job JSON from stdin, imports the
# project's scheduler/executor.py, calls execute_task(job), prints JSON result.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER="$SCRIPT_DIR/scheduler_runner.py"
if [ ! -f "$RUNNER" ]; then
  echo "FATAL: scheduler_runner.py not found at $RUNNER" >&2
  exit 6
fi

if [ "$SANDBOX_DEBUG" = "1" ]; then
  echo "--- launching bwrap scheduler_runner.py ---" >> "$DEBUG_LOG" 2>&1
fi

# NOTE: We deliberately do NOT --setenv platform secrets here. The only env
# the executor sees is what its own .env contains (loaded by config.py via
# load_dotenv) plus PATH/HOME from bwrap defaults. DATABASE_URL never enters
# the sandbox, closing the cross-project + platform-credential leak.
#
# PYTHONPATH=$PROJECT_DIR lets `from config import ...` and `from services
# import api_client` resolve exactly as they do in the in-process path
# (execution_engine.py inserts project_path at sys.path[0]).
exec bwrap "${BWRAP_ARGS[@]}" \
  --setenv PYTHONPATH "$PROJECT_DIR" \
  --setenv PYTHONUNBUFFERED "1" \
  -- \
  "$VENV/bin/python3" -u "$RUNNER" "$PROJECT_DIR"
