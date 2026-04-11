#!/usr/bin/env python3
"""
Scheduler Template Copier - Copies scheduler-template to project directory.

Pattern: Same as services/telegram/template.py.
Source: templates/scheduler-template/
Target: {project_path}/scheduler/
"""

import shutil
from pathlib import Path
from typing import Tuple

from utils.logger import logger

# Template source path (relative to backend root)
TEMPLATE_SOURCE = Path(__file__).parent.parent.parent / "templates" / "scheduler-template"

# Critical files that must exist after copy
CRITICAL_FILES = [
    "scheduler/executor.py",
    "scheduler/__init__.py",
    "scheduler/job_manager.py",
    "services/api_client.py",
    "config.py",
    ".env.example",
    "requirements.txt",
]


def copy_scheduler_template(project_path: str) -> Tuple[bool, str]:
    """
    Copy scheduler template to project directory.

    Args:
        project_path: Base project path (e.g., /root/clawd-projects/10_my-scheduler/)

    Returns:
        (True, scheduler_path) on success
        (False, error_message) on failure
    """
    # Validate source template exists
    if not TEMPLATE_SOURCE.exists():
        error_msg = f"Scheduler template not found at {TEMPLATE_SOURCE}"
        logger.error(f"❌ {error_msg}")
        return False, error_msg

    # Target: {project_path}/scheduler/
    target_path = Path(project_path) / "scheduler"

    # Remove existing scheduler directory if exists
    if target_path.exists():
        logger.warning(f"Removing existing scheduler directory: {target_path}")
        shutil.rmtree(target_path)

    # Copy template
    try:
        shutil.copytree(str(TEMPLATE_SOURCE), str(target_path))
        logger.info(f"✅ Scheduler template copied to {target_path}")
    except Exception as e:
        error_msg = f"Failed to copy template: {e}"
        logger.error(f"❌ {error_msg}")
        return False, error_msg

    # Verify critical files
    missing = []
    for file_path in CRITICAL_FILES:
        full_path = target_path / file_path
        if not full_path.exists():
            missing.append(file_path)

    if missing:
        error_msg = f"Missing critical files after copy: {missing}"
        logger.error(f"❌ {error_msg}")
        return False, error_msg

    logger.info(f"✅ All critical files verified in {target_path}")
    return True, str(target_path)


def verify_template_structure() -> bool:
    """Verify the scheduler template source exists and has all critical files."""
    if not TEMPLATE_SOURCE.exists():
        logger.error(f"Template source not found: {TEMPLATE_SOURCE}")
        return False

    for file_path in CRITICAL_FILES:
        full_path = TEMPLATE_SOURCE / file_path
        if not full_path.exists():
            logger.error(f"Missing template file: {full_path}")
            return False

    return True
