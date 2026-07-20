#!/usr/bin/env python3
"""
Backend Build & Publish Script
Run from backend directory: python buildpublish.py [--skip-deps] [--no-restart]

IMPORTANT: Call this script AFTER making ANY changes to the backend code!
- If you modified any files in backend/, run: python3 buildpublish.py
- This will install deps and restart PM2 + nginx automatically
- Only skip restart with --no-restart if you're just testing locally

Steps:
1. Install Python dependencies (using shared venv)
2. Verify main.py exists
3. Run database migrations (if alembic.ini exists)
4. Restart PM2 + nginx (default, use --no-restart to skip)
"""

import subprocess
import sys
import os
import argparse
import re
from pathlib import Path


# Shared virtual environment path (same as infrastructure_manager.py)
SHARED_VENV_PATH = "/root/dreampilot/dreampilotvenv"


def _in_sandbox() -> bool:
    """Detect if we're running inside a bwrap sandbox or Docker container.

    Inside these environments:
      - pm2 binary is not on PATH (bwrap only mounts /usr + project dir)
      - --unshare-pid hides host processes (pm2 can't see/manage them)
      - sudo is unavailable (no setuid in container)

    When True, buildpublish.py should skip PM2/nginx restart — the platform
    running on the host handles those after the sandbox exits.
    """
    # bwrap sets this via the /.sandboxed marker file some distros use, but
    # the most reliable signal is the absence of pm2 on PATH + presence of
    # /.dockerenv (Docker) or /proc/1/sched naming.
    if Path("/.dockerenv").exists():
        return True
    # Check if pm2 is even reachable. If not, we're definitely sandboxed.
    try:
        subprocess.run(["pm2", "--version"], capture_output=True, timeout=3)
        return False  # pm2 works → not sandboxed (or running on host)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return True


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
    """Install Python dependencies using shared venv with caching"""
    print("\n" + "="*50)
    print("PIP INSTALL")
    print("="*50)
    
    # Check for requirements.txt
    if not Path("requirements.txt").exists():
        print("⚠ No requirements.txt found, skipping")
        return True
    
    # Determine venv path
    venv = venv_path or SHARED_VENV_PATH
    pip_path = Path(venv) / "bin" / "pip"
    
    # Check if venv exists
    if pip_path.exists():
        print(f"📦 Using shared venv: {venv}")
        pip_cmd = str(pip_path)
    else:
        print("⚠ Shared venv not found, using system pip")
        pip_cmd = "pip"
    
    # Install with caching options (optimized flags)
    # --prefer-binary: Use binary wheels (faster, no compilation)
    # --no-cache-dir: Disable cache to avoid stale packages (optional)
    return run(f"{pip_cmd} install --prefer-binary -r requirements.txt")


def verify_main():
    """Verify main.py exists"""
    main_path = Path("main.py")
    if not main_path.exists():
        print("✗ main.py not found")
        return False
    print(f"✓ main.py verified: {main_path.stat().st_size} bytes")
    return True


def restart_pm2(domain: str = None, backend_port: int = None):
    """Restart the PM2 backend process.

    Tries three strategies in order:
      1. Call the worker-api's internal /internal/pm2-restart endpoint
         (works inside containers/sandbox where PM2 isn't directly accessible)
      2. Direct `pm2 restart` (works on the host where dreampilot has PM2 access)
      3. `sudo pm2 restart` (last resort, requires sudo — unavailable in sandbox)

    After restart, optionally health-checks the backend port so the caller
    (Claude) can verify the new code is live immediately.

    Args:
        domain: Domain name (PM2 app name is {domain}-backend per infrastructure_manager.py)
        backend_port: If set, health-check this port after restart (waits up to 30s)
    """
    print("\n" + "="*50)
    print("PM2 RESTART")
    print("="*50)

    # Template placeholder - replaced by infrastructure_manager during provisioning
    if not domain:
        domain = "{project_name}"

    # PM2 app name convention: {domain}-backend (matches infrastructure_manager.py)
    app_name = f"{domain}-backend"
    print(f"📦 Restarting PM2 app: {app_name}")

    # Strategy 1: call worker-api internal endpoint (container/sandbox path).
    # The worker-api runs on the same host as PM2 and can restart it directly.
    worker_api_url = os.environ.get("DREAMPILOT_WORKER_API_URL")
    if worker_api_url:
        import json as _json
        import urllib.request as _urlreq
        endpoint = f"{worker_api_url}/internal/pm2-restart"
        payload = _json.dumps({"pm2_app_name": app_name, "expect_port": backend_port}).encode()
        print(f"→ Calling worker-api: POST {endpoint}")
        try:
            req = _urlreq.Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            with _urlreq.urlopen(req, timeout=60) as resp:
                result = _json.loads(resp.read().decode())
            if result.get("success"):
                print(f"✓ Worker-api restarted PM2 app '{app_name}'")
                if backend_port and result.get("restarted"):
                    print(f"✓ Backend health-checked on port {backend_port}")
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

    # Strategy 3: sudo pm2 restart (last resort — fails in sandbox/container)
    print("⚠ bare pm2 restart failed, trying with sudo (may fail in sandbox/container)")
    return run(f"sudo pm2 restart {app_name}")


def reload_nginx():
    """Reload nginx configuration"""
    print("\n" + "="*50)
    print("NGINX RELOAD")
    print("="*50)
    # Try without sudo first (sandbox/container compatible), fall back to sudo.
    if run("nginx -s reload"):
        return True
    return run("sudo nginx -s reload")


def run_migrations():
    """Run database migrations if alembic is configured"""
    print("\n" + "="*50)
    print("DATABASE MIGRATIONS")
    print("="*50)
    
    if Path("alembic.ini").exists():
        return run("alembic upgrade head")
    else:
        print("⚠ No alembic.ini found, skipping migrations")
        return True


def main():
    parser = argparse.ArgumentParser(description="Backend Build & Publish")
    parser.add_argument("--skip-deps", action="store_true", help="Skip pip install")
    parser.add_argument("--skip-migrations", action="store_true", help="Skip database migrations")
    parser.add_argument("--no-restart", action="store_true", help="Skip PM2 and nginx restart (restart is default)")
    parser.add_argument("--venv", type=str, help="Virtual environment path (default: /root/dreampilot/dreampilotvenv)")
    parser.add_argument("--project-name", type=str, default=None, help="Project domain (PM2 app name is {domain}-backend). If omitted, uses the hardcoded value in this file.")
    parser.add_argument("--domain", type=str, default=None, help="Alias for --project-name")
    parser.add_argument("--restart", action="store_true", help="Force restart even if build fails")
    args = parser.parse_args()

    # --domain is an alias for --project-name
    if args.domain and not args.project_name:
        args.project_name = args.domain

    # Ensure we're in backend directory
    if not Path("main.py").exists():
        print("✗ Error: Run this script from the backend directory")
        sys.exit(1)

    # Detect sandbox/container environment. Inside bwrap or Docker, PM2 and
    # nginx are NOT accessible (not mounted, PID namespace isolated). Trying
    # to restart them would fail and make the build look broken even though
    # the code is correctly in place. The platform restarts PM2 externally.
    sandboxed = _in_sandbox()
    if sandboxed:
        print("="*50)
        print("SANDBOX/CONTAINER DETECTED")
        print("="*50)
        print("ℹ PM2 and nginx are NOT accessible from this environment.")
        print("  Code changes are saved to disk. The platform will restart")
        print("  the PM2 service externally after this script completes.")
        print("  Skipping PM2/nginx restart steps.\n")

    success = True

    # Step 1: Install dependencies
    if not args.skip_deps:
        if not install_dependencies(args.venv):
            success = False

    # Step 2: Verify main.py
    if success:
        if not verify_main():
            success = False

    # Step 3: Run migrations (optional)
    if not args.skip_migrations and success:
        if not run_migrations():
            print("⚠ Migrations failed, continuing anyway")

    # Step 4: Restart services.
    # In sandbox/container, restart_pm2() calls the worker-api's internal
    # endpoint to restart PM2 on the host (where PM2 actually runs).
    # On the host, it tries direct pm2 / sudo pm2.
    # Either way, the restart happens BEFORE this script returns, so Claude
    # can verify the live site immediately after buildpublish.py exits.
    backend_port = None
    try:
        env_file = Path(".env")
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.strip().startswith("PORT=") or line.strip().startswith("BACKEND_PORT="):
                    backend_port = int(line.split("=", 1)[1].strip())
                    break
    except Exception:
        pass

    if not args.no_restart and success:
        restart_pm2(domain=args.project_name, backend_port=backend_port)
        if not sandboxed:
            reload_nginx()
    elif sandboxed and not args.no_restart:
        # Still try restart via worker-api even in sandbox
        restart_pm2(domain=args.project_name, backend_port=backend_port)
    

    
    print("\n" + "="*50)
    if success:
        print("✓ BUILD & PUBLISH COMPLETE")
    else:
        print("✗ BUILD FAILED")
    print("="*50)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
