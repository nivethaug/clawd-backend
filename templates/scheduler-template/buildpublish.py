#!/usr/bin/env python3
"""
Scheduler Build & Publish Script
Run from project root: python buildpublish.py [--skip-deps] [--no-restart]

IMPORTANT: Call this script AFTER making ANY changes to scheduler/executor.py!
The centralized clawd-scheduler process caches executor modules in memory
(importlib). Without a restart, the old executor code keeps running.

Steps:
1. Install Python dependencies (from requirements.txt)
2. Verify scheduler/executor.py exists
3. Clear Python cache (__pycache__, *.pyc)
4. Restart clawd-scheduler PM2 process (picks up new executor code)
"""

import subprocess
import sys
import os
import argparse
from pathlib import Path


SHARED_VENV_PATH = "/root/dreampilot/dreampilotvenv"


def run(cmd: str, cwd: str = None, env: dict = None) -> bool:
    """Run shell command, return True if success"""
    print(f"\n▶ {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd, env=env)
    if result.returncode != 0:
        print(f"✗ Failed: {cmd}")
        return False
    print(f"✓ Success: {cmd}")
    return True


def install_dependencies(venv_path: str = None):
    """Install Python dependencies using shared venv"""
    print("\n" + "="*50)
    print("PIP INSTALL")
    print("="*50)

    if not Path("requirements.txt").exists():
        print("⚠ No requirements.txt found, skipping")
        return True

    venv = venv_path or SHARED_VENV_PATH
    pip_path = Path(venv) / "bin" / "pip"

    if pip_path.exists():
        print(f"📦 Using shared venv: {venv}")
        pip_cmd = str(pip_path)
    else:
        print("⚠ Shared venv not found, using system pip")
        pip_cmd = "pip"

    return run(f"{pip_cmd} install --prefer-binary -r requirements.txt")


def verify_executor():
    """Verify scheduler/executor.py exists"""
    executor_path = Path("scheduler") / "executor.py"
    if not executor_path.exists():
        # Try flat structure
        executor_path = Path("executor.py")
        if not executor_path.exists():
            print("✗ executor.py not found (checked scheduler/executor.py and executor.py)")
            return False
    print(f"✓ executor.py verified: {executor_path} ({executor_path.stat().st_size} bytes)")
    return True


def clear_python_cache():
    """Clear __pycache__ and *.pyc files to ensure fresh code load"""
    print("\n" + "="*50)
    print("CLEAR PYTHON CACHE")
    print("="*50)

    cache_cleared = 0
    pyc_cleared = 0

    for pycache_dir in Path(".").rglob("__pycache__"):
        try:
            import shutil
            shutil.rmtree(pycache_dir)
            cache_cleared += 1
        except Exception as e:
            print(f"⚠ Failed to remove {pycache_dir}: {e}")

    for pyc_file in Path(".").rglob("*.pyc"):
        try:
            pyc_file.unlink()
            pyc_cleared += 1
        except Exception as e:
            print(f"⚠ Failed to remove {pyc_file}: {e}")

    print(f"✅ Cleared {cache_cleared} __pycache__ dirs, {pyc_cleared} .pyc files")
    return True


def restart_scheduler():
    """Restart the centralized clawd-scheduler PM2 process.

    The scheduler caches executor modules via importlib. A restart clears
    the cache so the new executor.py code is loaded on the next job run.

    Tries three strategies in order (same as backend/frontend buildpublish):
      1. Worker-api internal endpoint (container/sandbox path)
      2. Direct pm2 restart (host path, no sudo)
      3. sudo pm2 restart (last resort — fails in sandbox/container)
    """
    print("\n" + "="*50)
    print("SCHEDULER RESTART")
    print("="*50)

    app_name = "clawd-scheduler"
    print(f"📦 Restarting PM2 app: {app_name}")

    # Strategy 1: worker-api internal endpoint (container/sandbox path).
    worker_api_url = os.environ.get("DREAMPILOT_WORKER_API_URL")
    if worker_api_url:
        import json as _json
        import urllib.request as _urlreq
        endpoint = f"{worker_api_url}/internal/pm2-restart"
        payload = _json.dumps({"pm2_app_name": app_name}).encode()
        print(f"→ Calling worker-api: POST {endpoint}")
        try:
            req = _urlreq.Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            with _urlreq.urlopen(req, timeout=60) as resp:
                result = _json.loads(resp.read().decode())
            if result.get("success"):
                print(f"✓ Worker-api restarted '{app_name}'")
                return True
            else:
                print(f"✗ Worker-api restart failed: {result.get('error', 'unknown')}")
        except Exception as e:
            print(f"⚠ Worker-api call failed: {e} — falling back to direct pm2")
    else:
        print("ℹ DREAMPILOT_WORKER_API_URL not set — skipping worker-api path")

    # Strategy 2: direct pm2 restart (host path, no sudo)
    if run(f"pm2 restart {app_name} --update-env"):
        return True

    # Strategy 3: sudo pm2 restart (last resort)
    print("⚠ bare pm2 failed, trying with sudo (may fail in sandbox/container)")
    return run(f"sudo pm2 restart {app_name}")


def main():
    parser = argparse.ArgumentParser(description="Scheduler Build & Publish")
    parser.add_argument("--skip-deps", action="store_true", help="Skip pip install")
    parser.add_argument("--no-restart", action="store_true", help="Skip scheduler restart")
    parser.add_argument("--venv", type=str, help="Virtual environment path")
    args = parser.parse_args()

    # Ensure executor.py exists
    if not verify_executor():
        sys.exit(1)

    success = True

    # Step 1: Install dependencies
    if not args.skip_deps:
        if not install_dependencies(args.venv):
            success = False

    # Step 2: Clear Python cache
    if success:
        clear_python_cache()

    # Step 3: Restart scheduler (picks up new executor code)
    if not args.no_restart and success:
        if not restart_scheduler():
            print("⚠ Scheduler restart failed, but code is updated. "
                  "Jobs will use old code until scheduler is manually restarted.")

    print("\n" + "="*50)
    if success:
        print("✓ BUILD & PUBLISH COMPLETE")
    else:
        print("✗ BUILD FAILED")
    print("="*50)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
