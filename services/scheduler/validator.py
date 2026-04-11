#!/usr/bin/env python3
"""
Scheduler Validator - Validates executor.py exists and has correct interface.
"""

from pathlib import Path
from typing import Tuple

from utils.logger import logger


def validate_scheduler_project(project_path: str) -> Tuple[bool, dict]:
    """
    Validate a scheduler project has the required structure.

    Args:
        project_path: Path to scheduler/ directory

    Returns:
        (is_valid, info_dict)
    """
    path = Path(project_path)
    info = {"project_path": str(path)}

    # Check executor.py exists
    executor_path = path / "scheduler" / "executor.py"
    if not executor_path.exists():
        executor_path = path / "executor.py"

    if not executor_path.exists():
        info["error"] = "executor.py not found"
        return False, info

    # Check execute_task function exists
    content = executor_path.read_text()
    if "def execute_task" not in content:
        info["error"] = "execute_task function not found in executor.py"
        return False, info

    info["executor_path"] = str(executor_path)
    info["has_execute_task"] = True

    logger.info(f"✅ Scheduler project validated: {project_path}")
    return True, info
