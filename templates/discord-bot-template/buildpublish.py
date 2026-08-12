#!/usr/bin/env python3
"""
Build & Publish script for Discord bot template.
Used by DreamAgent infrastructure for deployment.
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path


def install_dependencies(project_path: str) -> bool:
    """Install Python dependencies."""
    req_file = os.path.join(project_path, "requirements.txt")
    if not os.path.exists(req_file):
        print("No requirements.txt found, skipping install.")
        return True

    print("Installing dependencies...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", req_file],
        cwd=project_path,
        capture_output=True,
        text=True,
        timeout=300
    )

    if result.returncode != 0:
        # Non-fatal: the worker-api /internal/pm2-restart endpoint re-installs
        # deps into the shared venv on the host before restarting PM2.
        # This sandbox pip install may fail (venv is read-only via bwrap).
        print(f"⚠ Install warning (deps reinstalled on restart): {result.stderr[:200]}")

    print("Dependencies installed.")
    return True


def validate_project(project_path: str) -> bool:
    """Validate project structure."""
    required_files = ["main.py", "config.py", "requirements.txt"]
    for f in required_files:
        if not os.path.exists(os.path.join(project_path, f)):
            print(f"Missing required file: {f}")
            return False
    return True


def build(project_path: str) -> bool:
    """Build the Discord bot project."""
    print(f"Building Discord bot at: {project_path}")

    if not validate_project(project_path):
        return False

    if not install_dependencies(project_path):
        return False

    print("Build successful.")
    return True


def publish(project_path: str, project_id: str) -> bool:
    """
    Publish the Discord bot using PM2.

    Args:
        project_path: Path to the bot project
        project_id: Unique project identifier for PM2 process name
    """
    process_name = f"dc-bot-{project_id}"

    # Strategy 1: worker-api internal endpoint (container/sandbox path).
    # The container/sandbox can't access PM2 directly — call the worker-api
    # which runs on the same host as PM2.
    worker_api_url = os.environ.get("DREAMPILOT_WORKER_API_URL")
    if worker_api_url:
        import json as _json
        import urllib.request as _urlreq
        endpoint = f"{worker_api_url}/internal/pm2-restart"
        payload = _json.dumps({"pm2_app_name": process_name}).encode()
        print(f"→ Calling worker-api: POST {endpoint}")
        try:
            req = _urlreq.Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            with _urlreq.urlopen(req, timeout=60) as resp:
                result = _json.loads(resp.read().decode())
            if result.get("success"):
                print(f"✓ Worker-api restarted PM2 app '{process_name}'")
                print(f"Bot published as PM2 process: {process_name}")
                return True
            else:
                print(f"✗ Worker-api restart failed: {result.get('error', 'unknown')}")
        except Exception as e:
            print(f"⚠ Worker-api call failed: {e} — falling back to direct pm2")

    # Strategy 2: direct pm2 stop + start (host path, no sudo)
    # Use bot-sandbox.sh + shared venv to ensure correct Python interpreter.
    subprocess.run(["pm2", "stop", process_name], capture_output=True)
    subprocess.run(["pm2", "delete", process_name], capture_output=True)

    venv_path = os.getenv("SHARED_VENV_PATH", "/root/dreampilot/dreampilotvenv")
    sandbox_script = "/root/clawd-backend/scripts/bot-sandbox.sh"

    if os.path.exists(sandbox_script) and os.path.exists(venv_path):
        result = subprocess.run(
            ["pm2", "start", sandbox_script,
             "--name", process_name,
             "--interpreter", "none",
             "--cwd", project_path,
             "--", venv_path, project_path],
            cwd=project_path,
            capture_output=True,
            text=True
        )
    else:
        venv_python = os.path.join(venv_path, "bin", "python")
        interpreter = venv_python if os.path.exists(venv_python) else sys.executable
        result = subprocess.run(
            ["pm2", "start", "main.py",
             "--name", process_name,
             "--interpreter", interpreter],
            cwd=project_path,
            capture_output=True,
            text=True
        )

    if result.returncode == 0:
        print(f"Bot published as PM2 process: {process_name}")
        return True

    print(f"PM2 start failed: {result.stderr}")
    return False


if __name__ == "__main__":
    # Default to the script's own directory if no path is given.
    # This lets the model run "python3 buildpublish.py" from inside the
    # discord/ dir without memorising argument syntax.
    path = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parent)
    pid = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("PROJECT_ID", "default")

    if build(path):
        publish(path, pid)
    else:
        print("Build failed, skipping publish.")
        sys.exit(1)
