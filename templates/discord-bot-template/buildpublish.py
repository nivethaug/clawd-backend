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
        print(f"Install failed: {result.stderr}")
        return False

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

    # Stop existing process if running
    subprocess.run(
        ["pm2", "stop", process_name],
        capture_output=True
    )
    subprocess.run(
        ["pm2", "delete", process_name],
        capture_output=True
    )

    # Start with PM2
    result = subprocess.run(
        ["pm2", "start", "main.py",
         "--name", process_name,
         "--interpreter", sys.executable],
        cwd=project_path,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print(f"PM2 start failed: {result.stderr}")
        return False

    print(f"Bot published as PM2 process: {process_name}")
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python buildpublish.py <project_path> [project_id]")
        sys.exit(1)

    path = sys.argv[1]
    pid = sys.argv[2] if len(sys.argv) > 2 else "default"

    if build(path):
        publish(path, pid)
    else:
        print("Build failed, skipping publish.")
        sys.exit(1)
