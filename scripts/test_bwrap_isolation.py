#!/usr/bin/env python3
"""Test bubblewrap sandbox isolation — verifies a sandboxed backend cannot
read platform secrets or other users' files.

Usage:
    python3 scripts/test_bwrap_isolation.py <backend_path> <venv_path>

This script runs INSIDE the bwrap sandbox and reports which paths are
visible. Run it via:

    bwrap --ro-bind / / \
      --bind <backend_path> <backend_path> \
      --ro-bind <venv_path> <venv_path> \
      --dev /dev --proc /proc --tmpfs /tmp \
      --share-net --die-with-parent \
      -- <venv_path>/bin/python3 scripts/test_bwrap_isolation.py <backend_path>
"""
import os
import sys

results = {}

targets = {
    "/root/clawd-backend/.env.postgres": "Platform DB credentials",
    "/root/clawd-backend/app.py": "Platform source code",
    "/root/.claude/settings.json": "Claude settings",
    "/etc/nginx/nginx.conf": "Nginx config",
    "/var/run/docker.sock": "Docker socket",
    "/workspaces": "Other users workspaces",
}

for path, label in targets.items():
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                content = f.read(100)
            results[path] = f"!!! READABLE ({label}) !!!: {content[:30]}..."
        else:
            results[path] = "NOT FOUND (good)"
    except PermissionError:
        results[path] = "BLOCKED (good)"
    except FileNotFoundError:
        results[path] = "NOT FOUND (good)"
    except Exception as e:
        results[path] = f"BLOCKED ({type(e).__name__}) (good)"

# Can we list other users?
try:
    other = os.listdir("/workspaces")
    results["/workspaces"] = f"!!! LISTED: {other} !!!"
except Exception as e:
    results["/workspaces"] = f"BLOCKED ({type(e).__name__}) (good)"

# Can we read our own backend dir?
try:
    own = os.listdir(".")
    results["own_dir"] = f"OK: {len(own)} files (good - should work)"
except Exception as e:
    results["own_dir"] = f"FAILED: {e} (BAD - should work)"

# Try to execute commands
try:
    import subprocess
    r = subprocess.run(["ls", "/root/clawd-backend/"], capture_output=True, text=True, timeout=5)
    if r.returncode == 0 and r.stdout.strip():
        results["ls /root/clawd-backend"] = f"!!! ACCESSIBLE: {r.stdout[:50]} !!!"
    else:
        results["ls /root/clawd-backend"] = "empty or blocked (good)"
except Exception as e:
    results["ls /root/clawd-backend"] = f"BLOCKED ({type(e).__name__}) (good)"

print("=" * 50)
print("BWRAP SANDBOX ISOLATION TEST")
print("=" * 50)
for path, result in results.items():
    status = "PASS" if "(good)" in result else "FAIL"
    print(f"[{status}] {path}: {result}")
print("=" * 50)
fails = sum(1 for r in results.values() if "(good)" not in r and "OK" not in r)
if fails:
    print(f"RESULT: {fails} SECURITY FAILURES DETECTED")
    sys.exit(1)
else:
    print("RESULT: ALL CHECKS PASSED - sandbox is secure")
    sys.exit(0)
