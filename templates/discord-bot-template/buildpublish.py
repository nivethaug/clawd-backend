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
    Publish the Discord bot using PM2 via the worker-api.

    The worker-api runs on the host with direct PM2 access + shared venv.
    This is the ONLY strategy — direct pm2 from inside the sandbox creates
    broken processes (wrong interpreter, no venv packages).
    """
    process_name = f"dc-bot-{project_id}"
    worker_api_url = os.environ.get("DREAMPILOT_WORKER_API_URL")

    if not worker_api_url:
        print("✗ DREAMPILOT_WORKER_API_URL not set — cannot publish")
        return False

    import json as _json
    import urllib.request as _urlreq
    endpoint = f"{worker_api_url}/internal/pm2-restart"
    payload = _json.dumps({"pm2_app_name": process_name}).encode()
    print(f"→ Calling worker-api: POST {endpoint}")

    # Retry once — the worker-api may be briefly busy installing deps.
    for attempt in range(2):
        try:
            req = _urlreq.Request(endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            with _urlreq.urlopen(req, timeout=120) as resp:
                result = _json.loads(resp.read().decode())
            if result.get("success"):
                print(f"✓ Worker-api restarted PM2 app '{process_name}'")
                print(f"Bot published as PM2 process: {process_name}")
                return True
            else:
                print(f"✗ Worker-api restart failed: {result.get('error', 'unknown')}")
                return False
        except Exception as e:
            if attempt == 0:
                print(f"⚠ Worker-api call failed: {e} — retrying...")
            else:
                print(f"✗ Worker-api failed after retry: {e}")
                return False

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
