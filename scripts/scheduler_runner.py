#!/usr/bin/env python3
"""
Scheduler executor runner — runs INSIDE the bwrap sandbox.

Protocol:
    argv[1] : project_path (the on-disk project root)
    stdin   : one line of JSON — the job dict
              {"id": int, "task_type": str, "payload": dict, ...}
    stdout  : exactly one line of JSON — the result dict
              {"status": "success"|"failed", "message": str}
    stderr  : human-readable diagnostics (forwarded to scheduler logs)
    exit 0  : always — even on executor failure (status="failed" carries the
              error message). Exit != 0 indicates a runner-level panic that
              the parent cannot interpret as a job result.

Why this exists:
    The centralized clawd-scheduler process used to load each project's
    executor.py via importlib in-process. That gave every Claude-generated
    executor direct access to os.environ (including DATABASE_URL), the host
    filesystem (/root, /workspaces), and the host process table. This runner
    is invoked from a bwrap sandbox (scheduler-sandbox.sh) so the executor
    sees only its own project dir + a minimal env. A crash here kills only
    this subprocess — the scheduler daemon is unaffected.

Module resolution:
    PYTHONPATH is set to project_path by scheduler-sandbox.sh, so the same
    imports work as in the old in-process path:
        from config import ...           # {project_path}/config.py
        from services import api_client  # {project_path}/services/api_client.py
        from scheduler import executor   # {project_path}/scheduler/executor.py
    We import executor.py by file path (not package import) so the project's
    own scheduler/ package doesn't have to be importable as a top-level name.
"""

import json
import os
import sys
import traceback
import importlib.util
from pathlib import Path


def _read_job() -> dict:
    """Read exactly one JSON line from stdin. Empty stdin → empty dict."""
    line = sys.stdin.readline()
    if not line:
        return {}
    return json.loads(line)


def _load_executor(project_path: str):
    """Load {project_path}/scheduler/executor.py by file path.

    Returns the module object, or raises FileNotFoundError if missing.
    Falls back to {project_path}/executor.py for flat projects.
    """
    candidates = [
        Path(project_path) / "scheduler" / "executor.py",
        Path(project_path) / "executor.py",
    ]
    executor_path = next((p for p in candidates if p.exists()), None)
    if executor_path is None:
        raise FileNotFoundError(
            f"executor.py not found under {project_path} "
            f"(searched: {[str(p) for p in candidates]})"
        )

    # Import by file path so we don't depend on the project's scheduler/
    # package being importable as a top-level name (some projects have
    # scheduler/__init__.py with side effects we don't want to trigger
    # twice — job_manager.py connects to the DB, etc.).
    spec = importlib.util.spec_from_file_location("_scheduler_executor", executor_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not create module spec for {executor_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "execute_task"):
        raise AttributeError(
            f"{executor_path} does not define execute_task(job: dict) -> dict"
        )
    return module


def _emit(result: dict) -> None:
    """Write one JSON line to stdout and flush. Parent reads exactly one line."""
    sys.stdout.write(json.dumps(result, default=str) + "\n")
    sys.stdout.flush()


def main() -> int:
    if len(sys.argv) < 2:
        _emit({"status": "failed", "message": "scheduler_runner: missing project_path argv"})
        return 0

    project_path = sys.argv[1]

    # Defensive: ensure project_path is on sys.path even if PYTHONPATH was
    # stripped (some bwrap configs don't forward it). The sandbox script sets
    # PYTHONPATH=$PROJECT_DIR but we don't rely on it. This mirrors the
    # in-process loader which did sys.path.insert(0, project_path).
    if project_path not in sys.path:
        sys.path.insert(0, project_path)

    job = _read_job()

    try:
        executor = _load_executor(project_path)
    except Exception as e:
        # Load failure → still emit a structured result so the scheduler can
        # log_job(status='failed'). Don't exit non-zero — that would be
        # indistinguishable from a runner panic at the parent.
        _emit({"status": "failed", "message": f"executor load failed: {e}"})
        return 0

    try:
        result = executor.execute_task(job)
        if not isinstance(result, dict) or "status" not in result:
            _emit({
                "status": "failed",
                "message": f"executor returned invalid result shape: {type(result).__name__}",
            })
            return 0
        _emit(result)
        return 0

    except Exception as e:
        # Catch executor exceptions here so a buggy Claude-generated handler
        # surfaces as status=failed (logged) rather than crashing the runner.
        tb = traceback.format_exc(limit=3)
        sys.stderr.write(f"[scheduler_runner] executor raised: {e}\n{tb}\n")
        _emit({"status": "failed", "message": f"{type(e).__name__}: {e}"})
        return 0


if __name__ == "__main__":
    # Always exit 0 — the result line (success OR failed) is the contract.
    # Non-zero exit is reserved for runner panics that the parent can't
    # interpret (e.g. python import error before this main() runs).
    sys.exit(main())
