#!/usr/bin/env python3
"""
Scheduler Template Copier - Copies scheduler-template contents to project directory.

Source: templates/scheduler-template/
Target: {project_path}/ (contents copied directly, not nested)

Result: executor.py ends up at {project_path}/scheduler/executor.py
"""

import shutil
from pathlib import Path
from typing import Tuple

import logging
from utils.logger import logger  # noqa: F811 — reassign below
logger = logging.getLogger("services.scheduler.template")

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


def copy_scheduler_template(project_path: str, template_name: str = "scheduler-template") -> Tuple[bool, str]:
    """
    Copy a scheduler-family template to the project directory.

    Copies the contents of templates/{template_name}/ directly into
    {project_path}/ so that executor.py lands at {project_path}/scheduler/executor.py.

    Args:
        project_path: Base project path (e.g., /root/dreampilot/projects/scheduler/10_my-scheduler/)
        template_name: "scheduler-template" (legacy type-5) or
                       "agent-template" (automation agents — adds the
                       capability layer: proxy_call, state, conditions).

    Returns:
        (True, project_path) on success
        (False, error_message) on failure
    """
    source = TEMPLATE_SOURCE.parent / template_name
    # Validate source template exists
    if not source.exists():
        error_msg = f"Template '{template_name}' not found at {source}"
        logger.error(f"❌ {error_msg}")
        return False, error_msg

    target_path = Path(project_path)

    # Copy each item from template into project root (avoids double-nesting)
    try:
        for item in source.iterdir():
            dest = target_path / item.name
            if item.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(str(item), str(dest))
            else:
                shutil.copy2(str(item), str(dest))

        logger.info(f"✅ Template '{template_name}' copied to {target_path}")
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


def verify_template_structure(template_name: str = "scheduler-template") -> bool:
    """Verify a template source exists and has all critical files."""
    source = TEMPLATE_SOURCE.parent / template_name
    if not source.exists():
        logger.error(f"Template source not found: {source}")
        return False

    for file_path in CRITICAL_FILES:
        full_path = source / file_path
        if not full_path.exists():
            logger.error(f"Missing template file: {full_path}")
            return False

    return True
