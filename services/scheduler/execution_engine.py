#!/usr/bin/env python3
"""
Execution Engine — runs each project's executor.py in an isolated bwrap sandbox.

Lives at the backend level (services/scheduler/) — NOT inside templates.
Each job runs in a fresh subprocess wrapped by scripts/scheduler-sandbox.sh,
which gives the executor only its own project directory + a minimal env.

ARCHITECTURE
------------
execute_job(project, job)
  → subprocess.run([scheduler-sandbox.sh, venv, project_path],
                   input=json.dumps(job), timeout=JOB_TIMEOUT_SECONDS)
    → scheduler_runner.py (inside bwrap)
      → import executor.py from project_path/scheduler/
      → executor.execute_task(job)
      → print(json.dumps(result)) to stdout

The scheduler daemon (this process) stays alive forever. Executor crashes,
infinite loops, and rogue Claude-generated code (os.system, open('/root/...'),
subprocess.run(['pm2','list'])) are confined to the sandbox:
  - filesystem: only sees its own project dir
  - processes: own PID namespace (cannot enumerate host PIDs)
  - env: no DATABASE_URL, no platform tokens (config.py loads only project .env)

FALLBACK
--------
When EXECUTION_MODE != 'container' (local dev) OR the sandbox script / bwrap
binary is missing, we fall back to in-process importlib execution so dev
environments without bwrap still work. The fallback is logged loudly.

AI agents modify each project's executor.py, not this file.
"""

import json
import logging
import os
import subprocess
from typing import Any, Dict, Optional

logger = logging.getLogger('scheduler.execution_engine')

# Resolve the sandbox script path once. Lives next to this file:
#   services/scheduler/execution_engine.py
#   scripts/scheduler-sandbox.sh
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SANDBOX_SCRIPT = os.path.join(_BACKEND_ROOT, "scripts", "scheduler-sandbox.sh")

# Shared venv — same env var convention as services/discord/pm2_manager.py:15
# and services/telegram/pm2_manager.py. Default matches the prod worker VPS.
_SHARED_VENV = os.getenv("SHARED_VENV_PATH", "/root/dreampilot/dreampilotvenv")

# Per-job hard timeout (seconds). Matches the previous future.result(timeout=120)
# in scheduler.py, but now this is a REAL subprocess timeout — bwrap + the
# executor get SIGKILLed when it fires. Old code could not kill a hung executor.
JOB_TIMEOUT_SECONDS = int(os.getenv("SCHEDULER_JOB_TIMEOUT", "120"))

# Static: always container mode — bot-sandbox.sh uses shared venv Python
_USE_SANDBOX = os.path.exists(_SANDBOX_SCRIPT)

# Env var keys the executor is allowed to see. The project's .env (loaded by
# config.py via load_dotenv) is the source of truth for these — we explicitly
# do NOT pass platform env (DATABASE_URL, etc.) into the sandbox subprocess.
_SCHEDULER_ENV_KEYS = {
    'PROJECT_ID', 'PROJECT_PATH', 'BACKEND_URL',
    'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID',
    'DISCORD_WEBHOOK_URL',
    'SMTP_HOST', 'SMTP_PORT', 'SMTP_USER', 'SMTP_PASS', 'SMTP_FROM', 'EMAIL_TO',
    'API_ENDPOINT',
    # Managed-integration keys (services/integrations/catalog.py) — without
    # an entry here the sandbox silently drops the key.
    'OPENAI_API_KEY', 'OPENROUTER_API_KEY', 'ANTHROPIC_API_KEY', 'GEMINI_API_KEY',
    'GITHUB_TOKEN', 'STRIPE_SECRET_KEY', 'RAZORPAY_KEY_ID', 'RAZORPAY_KEY_SECRET',
    'RESEND_API_KEY', 'SLACK_WEBHOOK_URL', 'COINGECKO_API_KEY', 'SERPER_API_KEY',
    'TELEGRAM_BOT_TOKEN', 'DISCORD_TOKEN',
    # Nango OAuth access tokens (short-lived, minted fresh per job run by
    # _inject_oauth_tokens; see services/integrations/nango_client.py).
    'YOUTUBE_ACCESS_TOKEN', 'GITHUB_ACCESS_TOKEN', 'DISCORD_ACCESS_TOKEN',
    'NOTION_ACCESS_TOKEN', 'TWITTER_ACCESS_TOKEN', 'GOOGLE_SHEETS_ACCESS_TOKEN',
    'SLACK_ACCESS_TOKEN', 'STRIPE_ACCESS_TOKEN',
    # Path/Home are required for the venv python + ssl to resolve correctly.
    'PATH', 'HOME', 'LANG', 'LC_ALL',
}


def execute_job(project: dict, job: dict) -> dict:
    """Execute one job via the project's executor.py.

    Args:
        project: {"id": int, "path": "/path/to/project/"}
        job:     {"id": int, "task_type": str, "payload": dict, ...}

    Returns:
        {"status": "success"|"failed", "message": str}

    Never raises — all failure modes return a structured result so the
    scheduler loop can log_job() and move on.
    """
    project_id = project.get("id", 0)
    project_path = project.get("path", "")

    logger.info(
        f"Executing job {job.get('id')} for project {project_id} "
        f"(task_type={job.get('task_type')}, sandbox={_USE_SANDBOX})"
    )

    if _USE_SANDBOX:
        return _execute_in_sandbox(project_id, project_path, job)
    return _execute_in_process(project_id, project_path, job)


# ---------------------------------------------------------------------------
# Sandbox path (prod) — subprocess + bwrap
# ---------------------------------------------------------------------------

def _inject_oauth_tokens(project_id: int, env: dict) -> None:
    """Add fresh OAuth access tokens for the project owner's Nango
    connections (services/integrations/nango_client.py ENABLED_PROVIDERS
    defines the env-key mapping, e.g. youtube → YOUTUBE_ACCESS_TOKEN).

    Tokens are short-lived Google/provider access tokens minted server-side;
    refresh tokens never leave Nango. No-op when Nango is unconfigured.
    """
    from services.integrations import nango_client

    if not nango_client.is_configured():
        return
    from database_adapter import get_db
    with get_db() as conn:
        row = conn.execute(
            "SELECT user_id FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
    if not row:
        return
    owner_id = (dict(row) if not isinstance(row, dict) else row)["user_id"]

    with get_db() as conn:
        rows = conn.execute(
            "SELECT provider_config_key, connection_id FROM nango_connections "
            "WHERE user_id = ?",
            (owner_id,),
        ).fetchall()
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        key = d.get("provider_config_key")
        meta = nango_client.ENABLED_PROVIDERS.get(key)
        if not meta or not d.get("connection_id"):
            continue
        token = nango_client.get_access_token(d["connection_id"], key)
        if token:
            env[meta["env_token_key"]] = token
            logger.info("[EXEC-ENGINE] injected %s for project %s", meta["env_token_key"], project_id)


def _sync_from_container(project_id: int, project_path: str) -> bool:
    """Sync project files from Docker container to host if missing.

    The scheduler runs on the host (worker VPS) and looks for executor.py at
    the host bind-mount path (/workspaces/user_{id}/...). If the path is
    missing (project created from a different VPS, bind mount stale, etc.),
    this function copies the files from the Docker container where Claude
    created them.

    Returns True if path exists after sync attempt, False if still missing.
    """
    executor_path = os.path.join(project_path, "scheduler", "executor.py")
    if os.path.isfile(executor_path):
        return True  # Already exists, nothing to do

    logger.info("[EXEC-ENGINE] executor missing, syncing from container: %s", project_path)

    # Extract user_id from the host path
    user_id = None
    if "/user_" in project_path:
        parts = project_path.split("/user_")
        if len(parts) > 1:
            uid_str = parts[1].split("/")[0]
            if uid_str.isdigit():
                user_id = int(uid_str)

    if not user_id:
        logger.warning("[EXEC-ENGINE] could not extract user_id from path: %s", project_path)
        return False

    container_name = f"dreamagent-user-{user_id}"

    # Map host path → container path:
    # /workspaces/user_24/scheduler/1811_xxx → /workspace/scheduler/1811_xxx
    container_path = project_path.replace(f"/workspaces/user_{user_id}", "/workspace", 1)

    try:
        import subprocess as _sp
        # Check if container has the files
        check = _sp.run(
            ["docker", "exec", container_name, "test", "-f",
             os.path.join(container_path, "scheduler", "executor.py")],
            capture_output=True, timeout=10,
        )
        if check.returncode != 0:
            logger.warning("[EXEC-ENGINE] executor not in container either: %s", container_path)
            return False

        # Sync from container to host
        os.makedirs(project_path, exist_ok=True)
        _sp.run(
            ["docker", "cp", f"{container_name}:{container_path}/.", project_path],
            capture_output=True, timeout=60,
        )
        logger.info("[EXEC-ENGINE] ✓ synced project %s from container %s",
                     project_id, container_name)
        return os.path.isfile(executor_path)

    except _sp.TimeoutExpired:
        logger.warning("[EXEC-ENGINE] container sync timed out for project %s", project_id)
    except FileNotFoundError:
        logger.debug("[EXEC-ENGINE] docker not available on this VPS")
    except Exception as e:
        logger.warning("[EXEC-ENGINE] container sync failed for project %s: %s", project_id, e)

    return False


def _execute_in_sandbox(project_id: int, project_path: str, job: dict) -> dict:
    """Run execute_task inside scripts/scheduler-sandbox.sh via subprocess.

    Protocol with scheduler_runner.py:
        stdin  ← json.dumps(job)
        stdout → one JSON line: {"status":..., "message":...}
        exit 0 always (status field carries success/failure)

    Includes auto-sync from Docker container if the host path is missing,
    plus a retry for race conditions after scheduler restart.
    """
    # Check if path exists, if not try to sync from container, then retry
    for attempt in range(3):
        if os.path.isdir(project_path):
            break
        # Try container sync on first miss
        if attempt == 0:
            if _sync_from_container(project_id, project_path):
                continue  # Sync succeeded, recheck path
        if attempt < 2:
            logger.warning(
                f"project_path not found (attempt {attempt + 1}/3), "
                f"retrying in 3s: {project_path}"
            )
            import time as _time
            _time.sleep(3)
    else:
        return {"status": "failed", "message": f"project_path not found after 3 retries: {project_path}"}

    # Ensure the sandbox script is executable. Windows Git checks these out
    # without the +x bit (same issue hit by backend-sandbox.sh — see
    # infrastructure_manager.py:578-589). chmod is idempotent + cheap.
    try:
        if not os.access(_SANDBOX_SCRIPT, os.X_OK):
            os.chmod(_SANDBOX_SCRIPT, 0o755)
    except OSError as e:
        logger.warning(f"Could not chmod {_SANDBOX_SCRIPT}: {e}")

    # Minimal env — whitelisted keys only. No DATABASE_URL leak.
    clean_env = {k: v for k, v in os.environ.items() if k in _SCHEDULER_ENV_KEYS}
    # Guarantee PATH has the venv binaries + system paths even if the host
    # env didn't set PATH in a way bwrap would inherit cleanly.
    clean_env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    clean_env.setdefault("HOME", "/tmp")
    clean_env.setdefault("PYTHONUNBUFFERED", "1")

    # Nango OAuth connections of the project owner: mint fresh short-lived
    # access tokens so scheduler jobs can call connected providers (YouTube
    # etc.) with ZERO user configuration. Failure-tolerant — a broken Nango
    # must never stop jobs that don't need OAuth.
    try:
        _inject_oauth_tokens(project_id, clean_env)
    except Exception as e:
        logger.debug("[EXEC-ENGINE] oauth token injection skipped: %s", e)

    # Invoke via bash explicitly so we don't depend on the +x bit being set
    # at the OS level (defense-in-depth alongside the chmod above).
    cmd = ["bash", _SANDBOX_SCRIPT, _SHARED_VENV, project_path]
    job_json = json.dumps(job, default=str)

    try:
        proc = subprocess.run(
            cmd,
            input=job_json,
            capture_output=True,
            text=True,
            timeout=JOB_TIMEOUT_SECONDS,
            env=clean_env,
        )
    except subprocess.TimeoutExpired:
        logger.error(
            f"Job {job.get('id')} (project {project_id}) timed out after "
            f"{JOB_TIMEOUT_SECONDS}s in sandbox"
        )
        return {
            "status": "failed",
            "message": f"job timed out after {JOB_TIMEOUT_SECONDS}s",
        }
    except Exception as e:
        logger.error(f"Sandbox launch failed for job {job.get('id')}: {e}")
        return {"status": "failed", "message": f"sandbox launch failed: {e}"}

    # Forward runner stderr to scheduler logs for diagnosability.
    if proc.stderr:
        for line in proc.stderr.strip().splitlines():
            logger.warning(f"[sandbox stderr, job {job.get('id')}]: {line}")

    stdout = proc.stdout.strip()
    if not stdout:
        # Runner panicked before emitting a result line (e.g. python import
        # error, bwrap itself failed). Treat as a hard failure.
        logger.error(
            f"Job {job.get('id')} (project {project_id}): sandbox produced no "
            f"output (rc={proc.returncode})"
        )
        return {
            "status": "failed",
            "message": f"sandbox produced no output (rc={proc.returncode})",
        }

    # Parse the single result line. If the runner printed extra lines (e.g.
    # executor print() statements), take the LAST line — that's the result.
    lines = [ln for ln in stdout.splitlines() if ln.strip()]
    result_line = lines[-1] if lines else ""

    try:
        result = json.loads(result_line)
        if not isinstance(result, dict) or "status" not in result:
            return {
                "status": "failed",
                "message": f"invalid result shape from sandbox: {result_line[:200]}",
            }
        return result
    except json.JSONDecodeError as e:
        logger.error(
            f"Job {job.get('id')} (project {project_id}): failed to parse "
            f"sandbox output as JSON: {e}; output tail: {result_line[:200]}"
        )
        return {
            "status": "failed",
            "message": f"sandbox output not JSON: {result_line[:200]}",
        }


# ---------------------------------------------------------------------------
# In-process fallback (local dev / no bwrap)
# ---------------------------------------------------------------------------

def _execute_in_process(project_id: int, project_path: str, job: dict) -> dict:
    """Legacy importlib path — used when EXECUTION_MODE != container.

    Kept for local dev environments without bwrap installed. Logged loudly
    on first use so prod never silently falls back.
    """
    if not _execute_in_process._warned:
        logger.warning(
            "Scheduler running in IN-PROCESS mode (EXECUTION_MODE != container "
            "or sandbox script missing). Executor code has full platform access. "
            "Set EXECUTION_MODE=container + install bwrap for isolation."
        )
        _execute_in_process._warned = True

    executor = _load_executor_inprocess(project_id, project_path)
    if executor is None:
        return {"status": "failed", "message": f"Executor not found at {project_path}"}

    try:
        result = executor.execute_task(job)
        if not isinstance(result, dict) or "status" not in result:
            return {"status": "failed", "message": f"Invalid executor result shape: {type(result).__name__}"}
        return result
    except Exception as e:
        logger.error(f"Executor error (project={project_id}, job={job.get('id')}): {e}")
        return {"status": "failed", "message": str(e)}

_execute_in_process._warned = False


# In-memory cache for the in-process fallback only. Unused in sandbox mode
# (each job loads fresh — bwrap startup cost is the tradeoff).
_executor_cache: Dict[int, Any] = {}


def _load_executor_inprocess(project_id: int, project_path: str) -> Optional[Any]:
    """importlib loader — only used in local-dev fallback mode.

    Preserved from the pre-isolation implementation so dev workflows that
    don't have bwrap still function. See git history for the full original.
    """
    import importlib.util
    import sys

    if project_id in _executor_cache:
        return _executor_cache[project_id]

    executor_path = None
    candidate = os.path.join(project_path, "scheduler", "executor.py")
    if os.path.exists(candidate):
        executor_path = candidate
    if not executor_path:
        candidate = os.path.join(project_path, "executor.py")
        if os.path.exists(candidate):
            executor_path = candidate
    if not executor_path:
        logger.error(f"No executor.py found for project {project_id} (searched: {project_path})")
        return None

    module_name = f"scheduler_executors.project_{project_id}"

    # Evict conflicting backend modules so project-local copies win.
    saved_modules = {}
    evicted_keys = []
    for key in list(sys.modules.keys()):
        if key == "services.scheduler.execution_engine":
            continue
        if key == "config" or key == "services" or key == "scheduler" \
                or key.startswith("services.") or key.startswith("scheduler."):
            saved_modules[key] = sys.modules.pop(key)
            evicted_keys.append(key)

    # Force-load project .env (same override=True semantics as before).
    try:
        from dotenv import load_dotenv as _ld
        _project_env = os.path.join(project_path, ".env")
        if not os.path.exists(_project_env):
            _project_env = os.path.join(os.path.dirname(project_path), ".env")
        if os.path.exists(_project_env):
            _ld(_project_env, override=True)
    except Exception:
        pass

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

        if not hasattr(module, 'execute_task'):
            logger.error(f"executor.py missing execute_task() for project {project_id}")
            return None

        _executor_cache[project_id] = module
        logger.info(f"Loaded executor for project {project_id} from {executor_path}")
        return module

    except Exception as e:
        logger.error(f"Failed to load executor for project {project_id}: {e}")
        return None

    finally:
        if not path_was_present and project_path in sys.path:
            sys.path.remove(project_path)
        for key in evicted_keys:
            if key in saved_modules:
                sys.modules[key] = saved_modules[key]


def clear_cache(project_id: int = None):
    """No-op in sandbox mode (no in-process cache to clear).

    Kept as a shim so callers (services/scheduler/jobs.py:305-309) don't
    break. In sandbox mode, each job already loads fresh executor code —
    no restart, no cache invalidation needed after AI edits.

    In local-dev fallback mode, this DOES clear the importlib cache.
    """
    if not _USE_SANDBOX:
        if project_id:
            module_name = f"scheduler_executors.project_{project_id}"
            _executor_cache.pop(project_id, None)
            import sys
            sys.modules.pop(module_name, None)
            logger.info(f"Cleared executor cache for project {project_id} (in-process mode)")
        else:
            _executor_cache.clear()
            import sys
            for key in list(sys.modules.keys()):
                if key.startswith("scheduler_executors."):
                    del sys.modules[key]
            logger.info("Cleared all executor cache (in-process mode)")
    # Sandbox mode: silently no-op. Each job already runs fresh.
