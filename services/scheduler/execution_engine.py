#!/usr/bin/env python3
"""
Execution Engine - Generic dynamic job executor.

Lives at the backend level (services/scheduler/) — NOT inside templates.
Loads project-specific executor.py via importlib.
Caches loaded modules in memory for performance.
Never crashes - all errors return structured failure results.

AI agents modify each project's executor.py, not this file.
"""

import os
import sys
import logging
import importlib.util
from typing import Dict, Any, Optional

logger = logging.getLogger('scheduler.execution_engine')

# In-memory cache: project_id -> loaded executor module
_executor_cache: Dict[int, Any] = {}


def execute_job(project: dict, job: dict) -> dict:
    """
    Execute a job using the project's executor.py.

    Args:
        project: {"id": int, "path": "/path/to/project/"}
        job: {"id": int, "task_type": str, "payload": dict, ...}

    Returns:
        {"status": "success"|"failed", "message": str}
    """
    project_id = project.get("id", 0)
    project_path = project.get("path", "")

    logger.info(f"Executing job {job.get('id')} for project {project_id} (task_type={job.get('task_type')})")

    # 1. Load executor (cached after first load)
    executor = _load_executor(project_id, project_path)
    if not executor:
        return {"status": "failed", "message": f"Executor not found at {project_path}"}

    # 2. Call execute_task
    try:
        result = executor.execute_task(job)

        # Validate result shape
        if not isinstance(result, dict) or "status" not in result:
            return {"status": "failed", "message": f"Invalid executor result shape: {type(result).__name__}"}

        return result

    except Exception as e:
        logger.error(f"Executor error (project={project_id}, job={job.get('id')}): {e}")
        return {"status": "failed", "message": str(e)}


def _load_executor(project_id: int, project_path: str) -> Optional[Any]:
    """
    Load and cache executor module from project path.

    Search order:
    1. {project_path}/scheduler/executor.py  (project with scheduler subfolder)
    2. {project_path}/executor.py            (flat project structure)

    Isolates imports by temporarily inserting project_path at sys.path[0]
    so that project-local modules (config, services.*, scheduler.*)
    take priority over the backend's own modules.
    """
    # Return cached if available
    if project_id in _executor_cache:
        return _executor_cache[project_id]

    # Find executor.py
    executor_path = None

    # Try 1: scheduler subfolder
    candidate = os.path.join(project_path, "scheduler", "executor.py")
    if os.path.exists(candidate):
        executor_path = candidate

    # Try 2: flat structure
    if not executor_path:
        candidate = os.path.join(project_path, "executor.py")
        if os.path.exists(candidate):
            executor_path = candidate

    if not executor_path:
        logger.error(f"No executor.py found for project {project_id} (searched: {project_path})")
        return None

    module_name = f"scheduler_executors.project_{project_id}"

    # Modules that conflict between the backend and project directories.
    # The backend has its own config.py, services/, and scheduler/ packages.
    # We must temporarily evict them from sys.modules so the project's versions load.
    saved_modules = {}
    evicted_keys = []
    for key in list(sys.modules.keys()):
        # Never evict the execution engine itself
        if key == "services.scheduler.execution_engine":
            continue
        # Evict: config, services, scheduler, and all their submodules
        if key == "config" or key == "services" or key == "scheduler" \
                or key.startswith("services.") or key.startswith("scheduler."):
            saved_modules[key] = sys.modules.pop(key)
            evicted_keys.append(key)

    # Insert project path at position 0 (highest priority)
    path_was_present = project_path in sys.path
    if not path_was_present:
        sys.path.insert(0, project_path)

    try:
        spec = importlib.util.spec_from_file_location(module_name, executor_path)
        if not spec or not spec.loader:
            logger.error(f"Failed to create module spec for {executor_path}")
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        # Validate it exposes execute_task
        if not hasattr(module, 'execute_task'):
            logger.error(f"executor.py missing execute_task() for project {project_id}")
            return None

        # Cache it
        _executor_cache[project_id] = module
        logger.info(f"Loaded executor for project {project_id} from {executor_path}")
        return module

    except Exception as e:
        logger.error(f"Failed to load executor for project {project_id}: {e}")
        return None

    finally:
        # Remove project path
        if not path_was_present and project_path in sys.path:
            sys.path.remove(project_path)
        # Restore evicted backend modules
        for key in evicted_keys:
            if key in saved_modules:
                sys.modules[key] = saved_modules[key]


def clear_cache(project_id: int = None):
    """
    Clear executor cache. Useful after AI modifies executor.py.

    Args:
        project_id: Clear specific project, or None to clear all
    """
    if project_id:
        module_name = f"scheduler_executors.project_{project_id}"
        _executor_cache.pop(project_id, None)
        sys.modules.pop(module_name, None)
        logger.info(f"Cleared executor cache for project {project_id}")
    else:
        _executor_cache.clear()
        # Clean up sys.modules
        for key in list(sys.modules.keys()):
            if key.startswith("scheduler_executors."):
                del sys.modules[key]
        logger.info("Cleared all executor cache")
