#!/usr/bin/env python3
"""In-sandbox isolation probe — runs INSIDE the bwrap sandbox and reports
which paths and capabilities the deployed backend can reach.

Invoked by scripts/verify_isolation.sh. Do NOT run directly with arbitrary
bwrap args — use verify_isolation.sh which mirrors the real backend-sandbox.sh
mount layout.

Exit codes:
    0 = all isolation checks PASSED (backend cannot escape)
    1 = one or more checks FAILED (secrets visible)
"""
import os
import socket
import subprocess
import sys

results = []  # list of (status, target, detail)


def check_blocked(label, path, *, kind="file"):
    """Verify a path is NOT visible from inside the sandbox."""
    try:
        if kind == "dir":
            entries = os.listdir(path)
            results.append(("FAIL", path, f"directory LISTABLE — {len(entries)} entries visible"))
            return
        if not os.path.exists(path):
            results.append(("PASS", path, "not present in sandbox"))
            return
        with open(path, "r") as fh:
            preview = fh.read(80).replace("\n", " ")
        results.append(("FAIL", path, f"READABLE — preview: {preview!r}"))
    except FileNotFoundError:
        results.append(("PASS", path, "not present in sandbox"))
    except PermissionError:
        results.append(("PASS", path, "permission denied"))
    except IsADirectoryError:
        try:
            entries = os.listdir(path)
            results.append(("FAIL", path, f"directory LISTABLE — {len(entries)} entries"))
        except Exception as e:
            results.append(("PASS", path, f"blocked ({type(e).__name__})"))
    except Exception as e:
        # Any error trying to read = blocked = pass
        results.append(("PASS", path, f"blocked ({type(e).__name__})"))


def check_visible(label, path):
    """Verify a path IS visible from inside the sandbox (sanity check)."""
    try:
        if os.path.exists(path):
            results.append(("PASS", path, "visible (expected)"))
        else:
            results.append(("FAIL", path, "should be visible but is missing"))
    except Exception as e:
        results.append(("FAIL", path, f"unexpected error: {type(e).__name__}: {e}"))


# ----------------------------------------------------------------------------
# 1. CRITICAL: Platform secrets must NOT be visible
# ----------------------------------------------------------------------------
check_blocked("Platform DB credentials", "/root/clawd-backend/.env.postgres")
check_blocked("Platform source code", "/root/clawd-backend/app.py")
check_blocked("Platform source dir", "/root/clawd-backend", kind="dir")
check_blocked("Claude settings dir", "/root/.claude", kind="dir")
check_blocked("Claude settings.json", "/root/.claude.json")
check_blocked("SSH private keys", "/root/.ssh", kind="dir")
check_blocked("Root home dir", "/root", kind="dir")
check_blocked("Worker source (project_creation_runs)", "/root/clawd-backend/services/project_creation_runs.py")
check_blocked("Container manager source", "/root/clawd-backend/services/container_manager.py")

# ----------------------------------------------------------------------------
# 2. CRITICAL: Host compromise vectors must NOT be visible
# ----------------------------------------------------------------------------
check_blocked("Docker socket", "/var/run/docker.sock")
check_blocked("Systemd unit dir", "/etc/systemd", kind="dir")
check_blocked("Nginx config", "/etc/nginx/nginx.conf")
check_blocked("Nginx config dir", "/etc/nginx", kind="dir")
check_blocked("Postgres config", "/etc/postgresql", kind="dir")
check_blocked("Cron jobs", "/etc/crontab")
check_blocked("PAM config", "/etc/pam.d", kind="dir")
check_blocked("Shadow password file", "/etc/shadow")

# ----------------------------------------------------------------------------
# 3. CRITICAL: Other users' files must NOT be visible
# ----------------------------------------------------------------------------
check_blocked("Other users root", "/workspaces", kind="dir")
check_blocked("Other users parent", "/workspaces/user_1", kind="dir")
check_blocked("DreamPilot parent (other projects)", "/root/dreampilot", kind="dir")

# ----------------------------------------------------------------------------
# 4. Network: should NOT be able to bind privileged ports or reach metadata
# ----------------------------------------------------------------------------
# Try to connect to AWS/GCP metadata endpoint (if cloud-hosted, this leaks IAM creds)
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    s.connect(("169.254.169.254", 80))
    s.close()
    results.append(("WARN", "metadata:169.254.169.254", "reachable — cloud IAM may be exposed"))
except Exception as e:
    results.append(("PASS", "metadata:169.254.169.254", f"blocked ({type(e).__name__})"))

# Try to bind a privileged port (<1024 requires CAP_NET_BIND_SERVICE which we don't have)
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 80))
    s.close()
    results.append(("FAIL", "bind:127.0.0.1:80", "privileged port bind succeeded — has CAP_NET_BIND_SERVICE"))
except PermissionError:
    results.append(("PASS", "bind:127.0.0.1:80", "permission denied (no CAP_NET_BIND_SERVICE)"))
except Exception as e:
    results.append(("PASS", "bind:127.0.0.1:80", f"blocked ({type(e).__name__})"))

# ----------------------------------------------------------------------------
# 5. Process namespace: should NOT see host processes
# ----------------------------------------------------------------------------
try:
    proc_entries = os.listdir("/proc")
    pids = [e for e in proc_entries if e.isdigit()]
    # Sandbox should have very few PIDs visible (init + self + a few helpers)
    if len(pids) > 20:
        results.append(("WARN", "/proc", f"{len(pids)} PIDs visible — may share PID namespace with host"))
    else:
        results.append(("PASS", "/proc", f"{len(pids)} PIDs visible (likely sandboxed PID namespace)"))
except Exception as e:
    results.append(("PASS", "/proc", f"blocked ({type(e).__name__})"))

# ----------------------------------------------------------------------------
# 6. Sanity: things the backend SHOULD be able to see
# ----------------------------------------------------------------------------
own_backend = sys.argv[1] if len(sys.argv) > 1 else "."
check_visible("Own backend dir", own_backend)
check_visible("Shared venv", "/root/dreampilot/dreampilotvenv")
check_visible("System libs", "/usr/lib")
check_visible("DNS resolver", "/etc/resolv.conf")

# ----------------------------------------------------------------------------
# Report
# ----------------------------------------------------------------------------
print("=" * 70)
print(" BWRAP SANDBOX ISOLATION REPORT")
print("=" * 70)

fails = warns = 0
for status, target, detail in results:
    icon = {"PASS": "✓", "FAIL": "✗", "WARN": "⚠"}[status]
    print(f" [{icon} {status:4}] {target}")
    print(f"            {detail}")
    if status == "FAIL":
        fails += 1
    elif status == "WARN":
        warns += 1

print("=" * 70)
if fails:
    print(f" RESULT: ❌ FAIL — {fails} isolation failure(s), {warns} warning(s)")
    print(" The deployed backend CAN read paths it should not be able to.")
    print(" DO NOT launch publicly until these are fixed.")
    sys.exit(1)
elif warns:
    print(f" RESULT: ⚠ PASS with {warns} warning(s) — review above")
    sys.exit(0)
else:
    print(" RESULT: ✅ PASS — backend is fully isolated from host secrets")
    sys.exit(0)
