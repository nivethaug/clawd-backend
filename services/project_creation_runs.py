"""
Durable project creation run storage and worker execution.

The API enqueues project creation into the database and returns the project
record immediately. A separate PM2 worker claims queued rows and performs the
same creation pipeline that used to run inside the FastAPI process.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import uuid
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from database_adapter import get_db
from database_postgres import get_connection_pool
from github_service import get_github_service
from project_initial_env import write_initial_environment_variables
from project_manager import ProjectFileManager
from services.token_tracker import record_usage
from services.sentry_config import capture_exception
from template_selector import TemplateSelector

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent.parent
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "interrupted"}
ACTIVE_STATUSES = {"queued", "running"}
DEFAULT_CHUNK_RETENTION_DAYS = 7
DEFAULT_MAX_TERMINAL_CHUNKS_PER_RUN = 800


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _row_value(row: Any, key: str, index: int = 0) -> Any:
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    return row[index]


def _json_loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False)


def enqueue_project_creation_run(
    *,
    user_id: int,
    name: str,
    domain: str,
    description: Optional[str],
    type_id: int,
    template_id: Optional[str],
    bot_token: Optional[str],
    telegram_bot_token: Optional[str],
    telegram_chat_id: Optional[str],
    discord_webhook_url: Optional[str],
    email_to: Optional[str],
    api_endpoint: Optional[str],
    description_for_worker: str,
    initial_environment_variables: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Create the project row and queue a durable creation run."""
    run_uuid = str(uuid.uuid4())
    payload = {
        "name": name,
        "domain": domain,
        "description": description or "",
        "description_for_worker": description_for_worker or description or "",
        "type_id": type_id,
        "template_id": template_id,
        "bot_token": bot_token,
        "telegram_bot_token": telegram_bot_token,
        "telegram_chat_id": telegram_chat_id,
        "discord_webhook_url": discord_webhook_url,
        "email_to": email_to,
        "api_endpoint": api_endpoint,
        "initial_environment_variables": initial_environment_variables or [],
    }

    with get_db() as conn:
        row = conn.execute(
            """
            INSERT INTO projects (user_id, name, domain, description, project_path, type_id, status, claude_code_session_name)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (user_id, name, domain, description, "", type_id, "creating", None),
        ).fetchone()
        if not row:
            conn.rollback()
            raise RuntimeError("Failed to create project record")

        project = dict(row)
        conn.execute(
            """
            INSERT INTO project_creation_runs (
                run_uuid, project_id, user_id, type_id, status, payload, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, 'queued', %s::jsonb, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (run_uuid, project["id"], user_id, type_id, _json_dumps(payload)),
        )
        conn.commit()

    logger.info("[PROJECT-RUN] queued run=%s project=%s type=%s", run_uuid, project["id"], type_id)
    return project


def append_chunk(run_id: int, chunk_type: str, content: str) -> int:
    content = content or ""
    if not content:
        return -1
    pool = get_connection_pool()
    conn = pool.getconn()
    previous_autocommit = getattr(conn, "autocommit", False)
    try:
        # Some infrastructure helpers temporarily enable autocommit on pooled
        # connections. Chunk sequence assignment must always run in one explicit
        # transaction so concurrent stdout/stderr reader threads cannot pick the
        # same next seq value.
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (int(run_id),))
            cur.execute(
                "SELECT COALESCE(MAX(seq), -1) + 1 AS next_seq FROM project_creation_chunks WHERE run_id = %s",
                (run_id,),
            )
            row = cur.fetchone()
            seq = int(_row_value(row, "next_seq") or 0)
            cur.execute(
                """
                INSERT INTO project_creation_chunks (run_id, seq, chunk_type, content, created_at)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                """,
                (run_id, seq, chunk_type or "log", content[:8000]),
            )
            cur.execute(
                """
                UPDATE project_creation_runs
                SET heartbeat_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (run_id,),
            )
        conn.commit()
        return seq
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = previous_autocommit
        pool.putconn(conn)


def claim_next_run(worker_id: str) -> Optional[Dict[str, Any]]:
    pool = get_connection_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM project_creation_runs
                WHERE status = 'queued'
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """
            )
            row = cur.fetchone()
            if not row:
                conn.commit()
                return None
            run_id = row["id"] if isinstance(row, dict) else row[0]
            cur.execute(
                """
                UPDATE project_creation_runs
                SET status = 'running',
                    worker_id = %s,
                    started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                    heartbeat_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING *
                """,
                (worker_id, run_id),
            )
            run = cur.fetchone()
            conn.commit()
            return dict(run) if run else None
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def update_heartbeat(run_id: int) -> None:
    with get_db() as conn:
        conn.execute(
            """
            UPDATE project_creation_runs
            SET heartbeat_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (run_id,),
        )
        conn.commit()


def mark_completed(run_id: int, has_writes: bool = False) -> None:
    with get_db() as conn:
        conn.execute(
            """
            UPDATE project_creation_runs
            SET status = 'completed',
                has_writes = %s,
                completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (bool(has_writes), run_id),
        )
        conn.commit()
    prune_terminal_chunks(run_id=run_id)


def mark_failed(run_id: int, status: str, error: str, project_id: Optional[int] = None) -> None:
    final_status = status if status in {"failed", "cancelled", "interrupted"} else "failed"
    with get_db() as conn:
        conn.execute(
            """
            UPDATE project_creation_runs
            SET status = %s,
                error = %s,
                completed_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (final_status, error[:2000], run_id),
        )
        if project_id:
            # Cover intermediate statuses too (ai_provisioning/building/deploying/
            # verifying), not just "creating" — a failure mid-phase must not leave
            # the project stuck. Never override an already-terminal status.
            conn.execute(
                "UPDATE projects SET status = %s, error_code = %s WHERE id = %s AND status NOT IN ('ready', 'failed')",
                ("failed", "creation_worker_failed", project_id),
            )
        conn.commit()
    prune_terminal_chunks(run_id=run_id)


def prune_terminal_chunks(run_id: Optional[int] = None) -> None:
    """Bound durable project creation chunk growth for terminal runs.

    Active runs keep all chunks so reconnect/polling remains complete. Once a
    run completes or fails, keep a recent tail for troubleshooting and remove
    terminal chunks after the retention window.
    """
    retention_days = max(
        1,
        _env_int("PROJECT_CREATION_CHUNK_RETENTION_DAYS", DEFAULT_CHUNK_RETENTION_DAYS),
    )
    max_chunks = max(
        100,
        _env_int("PROJECT_CREATION_CHUNK_MAX_TERMINAL_PER_RUN", DEFAULT_MAX_TERMINAL_CHUNKS_PER_RUN),
    )

    pool = get_connection_pool()
    conn = pool.getconn()
    previous_autocommit = getattr(conn, "autocommit", False)
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            params: List[Any] = [list(TERMINAL_STATUSES)]
            run_filter = ""
            if run_id is not None:
                run_filter = "AND c.run_id = %s"
                params.append(int(run_id))

            cur.execute(
                f"""
                DELETE FROM project_creation_chunks c
                USING project_creation_runs r
                WHERE c.run_id = r.id
                  AND r.status = ANY(%s)
                  {run_filter}
                  AND COALESCE(r.completed_at, r.updated_at, r.created_at)
                        < CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')
                """,
                (*params, retention_days),
            )
            deleted_expired = cur.rowcount

            cap_params: List[Any] = [list(TERMINAL_STATUSES)]
            cap_run_filter = ""
            if run_id is not None:
                cap_run_filter = "AND c.run_id = %s"
                cap_params.append(int(run_id))
            cap_params.append(max_chunks)

            cur.execute(
                f"""
                DELETE FROM project_creation_chunks
                WHERE id IN (
                    SELECT id FROM (
                        SELECT c.id,
                               ROW_NUMBER() OVER (PARTITION BY c.run_id ORDER BY c.seq DESC) AS rn
                        FROM project_creation_chunks c
                        JOIN project_creation_runs r ON r.id = c.run_id
                        WHERE r.status = ANY(%s)
                          {cap_run_filter}
                          AND c.chunk_type <> 'error'
                    ) ranked
                    WHERE ranked.rn > %s
                )
                """,
                tuple(cap_params),
            )
            deleted_over_cap = cur.rowcount
        conn.commit()
        if deleted_expired or deleted_over_cap:
            logger.info(
                "[PROJECT-RUN] pruned creation chunks run=%s expired=%s over_cap=%s max_per_run=%s retention_days=%s",
                run_id or "all",
                deleted_expired,
                deleted_over_cap,
                max_chunks,
                retention_days,
            )
    except Exception as exc:
        conn.rollback()
        logger.warning("[PROJECT-RUN] chunk pruning failed run=%s: %s", run_id or "all", exc)
    finally:
        conn.autocommit = previous_autocommit
        pool.putconn(conn)


def _record_charge(run_id: int, operation_code: str, charge: List[Dict[str, Any]], charge_result: Dict[str, Any]) -> None:
    with get_db() as conn:
        conn.execute(
            """
            UPDATE project_creation_runs
            SET operation_code = %s,
                charge = %s::jsonb,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (operation_code, _json_dumps({"charged": charge, "cost": charge_result.get("cost")}), run_id),
        )
        conn.commit()


def _set_project_status(project_id: int, status: str, error_code: Optional[str] = None) -> None:
    with get_db() as conn:
        if error_code:
            conn.execute(
                "UPDATE projects SET status = %s, error_code = %s WHERE id = %s",
                (status, error_code, project_id),
            )
        else:
            conn.execute("UPDATE projects SET status = %s WHERE id = %s", (status, project_id))
        conn.commit()


def _get_project(project_id: int) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = %s", (project_id,)).fetchone()
    return dict(row) if row else None


def _mark_container_active(user_id: Optional[int]) -> None:
    """Mark the user's container as having an active Claude session.

    Touches the sentinel file inside the container so the reaper doesn't
    stop it during a long-running build (project creation takes 20-30 min).
    """
    if not user_id:
        return
    try:
        import os as _os
        if _os.getenv("EXECUTION_MODE", "local").lower() == "container":
            from services.container_manager import ContainerManager
            ContainerManager(user_id).mark_claude_active()
            logger.info("[PROJECT-RUN] marked container active for user %s (reaper protection)", user_id)
    except Exception as e:
        logger.warning("[PROJECT-RUN] failed to mark container active: %s", e)


def _mark_container_inactive(user_id: Optional[int]) -> None:
    """Clear the sentinel after build completes — reaper can stop the container."""
    if not user_id:
        return
    try:
        import os as _os
        if _os.getenv("EXECUTION_MODE", "local").lower() == "container":
            from services.container_manager import ContainerManager
            ContainerManager(user_id).mark_claude_inactive()
            logger.info("[PROJECT-RUN] marked container inactive for user %s", user_id)
    except Exception as e:
        logger.warning("[PROJECT-RUN] failed to mark container inactive: %s", e)


def _database_url() -> Optional[str]:
    """DEPRECATED — returns the PLATFORM database URL.

    Previously, every bot's .env got the platform DB credentials (admin user
    on the dreampilot database). This leaked platform credentials to Claude
    Code running inside Docker containers, which could read sibling projects'
    .env files and connect directly to the platform DB.

    Use _provision_project_database() instead, which creates an isolated
    per-project database + user with no access to the platform DB.

    Kept only as a fallback if provisioning fails (bot runs DB-less).
    """
    if os.getenv("USE_POSTGRES", "true").lower() != "true":
        return None
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "dreampilot")
    db_user = os.getenv("DB_USER", "admin")
    db_password = os.getenv("DB_PASSWORD", "")
    return f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"


def _provision_project_database(project_name: str, project_id: int) -> Optional[str]:
    """Create an isolated PostgreSQL database + user for a bot project.

    Returns a DATABASE_URL scoped to the new database. The new user has NO
    access to the platform dreampilot database — only its own {project}_db.

    This replaces _database_url() for bot projects (Telegram, Discord).
    The platform admin credentials are used ONLY to run CREATE DATABASE /
    CREATE USER, then discarded. The bot's .env gets the restricted user.

    Mirrors DatabaseProvisioner.create_database_and_user() in
    infrastructure_manager.py but uses direct psycopg2 (TCP) instead of
    docker exec, so it works from the worker VPS.

    Returns None if Postgres is not configured or provisioning fails —
    bots with DATABASE_URL=None still work (their template guards on it).
    """
    if os.getenv("USE_POSTGRES", "true").lower() != "true":
        return None

    import string as _string
    import random as _random

    db_host = os.getenv("DB_HOST", "localhost")
    db_port = int(os.getenv("DB_PORT", "5432"))
    admin_user = os.getenv("DB_USER", "admin")
    admin_password = os.getenv("DB_PASSWORD", "")
    admin_db = os.getenv("DB_NAME", "dreampilot")

    # Sanitize: lowercase, hyphens → underscores, strip non-alphanumeric.
    # Prefix with project_id to guarantee uniqueness across projects with
    # similar names. Truncate to keep under Postgres's 63-char identifier limit.
    raw = re.sub(r'[^a-z0-9]', '_', project_name.lower())[:20]
    db_name = f"proj{project_id}_{raw}_db"[:60]
    username = f"proj{project_id}_{raw}_u"[:60]
    password = ''.join(_random.choice(_string.ascii_letters + _string.digits) for _ in range(32))

    try:
        import psycopg2
        from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

        # Connect as admin to the platform DB to create the new database + user.
        # autocommit is required — CREATE DATABASE cannot run inside a transaction.
        admin_conn = psycopg2.connect(
            host=db_host, port=db_port,
            dbname=admin_db, user=admin_user, password=admin_password,
            connect_timeout=10,
        )
        admin_conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        admin_cur = admin_conn.cursor()

        # Drop stale database/user if they exist (e.g. project re-created after deletion)
        try:
            admin_cur.execute(f'DROP DATABASE IF EXISTS "{db_name}";')
            admin_cur.execute(f'DROP USER IF EXISTS "{username}";')
        except Exception:
            admin_conn.rollback()

        # Create fresh isolated database + user
        admin_cur.execute(f'CREATE DATABASE "{db_name}";')
        admin_cur.execute(f'CREATE USER "{username}" WITH PASSWORD \'{password}\';')
        admin_cur.execute(f'GRANT ALL PRIVILEGES ON DATABASE "{db_name}" TO "{username}";')
        admin_cur.close()
        admin_conn.close()

        # Connect to the NEW database to grant schema permissions (PG 15+ requires this)
        proj_conn = psycopg2.connect(
            host=db_host, port=db_port,
            dbname=db_name, user=admin_user, password=admin_password,
            connect_timeout=10,
        )
        proj_conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        proj_cur = proj_conn.cursor()
        proj_cur.execute(f'GRANT ALL ON SCHEMA public TO "{username}";')
        proj_cur.execute(
            f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO "{username}";'
        )
        proj_cur.close()
        proj_conn.close()

        database_url = f"postgresql://{username}:{password}@{db_host}:{db_port}/{db_name}"
        logger.info(
            "[PROJECT-RUN] provisioned isolated DB '%s' + user '%s' for project %s",
            db_name, username, project_id,
        )
        return database_url

    except Exception as e:
        logger.error(
            "[PROJECT-RUN] failed to provision per-project DB for project %s: %s. "
            "Bot will run DB-less (template degrades gracefully).",
            project_id, e,
        )
        return None


def _run_logged_subprocess(
    run_id: int,
    args: List[str],
    *,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    timeout: int = 1800,
    prefix: str = "",
) -> int:
    logger.info("[PROJECT-RUN] executing: %s", " ".join(args))
    append_chunk(run_id, "log", f"Executing: {' '.join(args)}")
    stdout_tail = deque(maxlen=30)
    stderr_tail = deque(maxlen=30)

    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        cwd=cwd,
        env=env,
    )

    def stream(pipe, stream_prefix: str) -> None:
        # Stateful passthrough: when we see a multi-line diagnostic block
        # (e.g. "[VERIFY] PM2 jlist:\n{...}" or "Traceback ..."), keep forwarding
        # the continuation lines to PM2 logs until the block ends. Otherwise the
        # noise filter strips the JSON/error body and we only see the label.
        # _diag_lines_remaining is decremented for each continuation line.
        diag_state = {"remaining": 0}

        # Markers that START a multi-line diagnostic block. When we see one of
        # these we set a high passthrough counter so the next N lines flow
        # through to PM2 logs (the content is small — capped by line length filter).
        _DIAG_START_MARKERS = (
            "[VERIFY] PM2 logs",
            "[VERIFY] PM2 status",
            "[VERIFY] PM2 jlist",
            "[VERIFY] PM2 list stderr",
            "[VERIFY] Ecosystem config",
            "[VERIFY] Sandbox debug",
            "[SERVICE] PM2 logs",
            "[SERVICE] PM2 stderr",
            "[SERVICE] PM2 error logs",
            "[SERVICE] Sandbox debug",
            "[SERVICE] ❌",
            "Traceback (most recent call last)",
        )

        try:
            for line in iter(pipe.readline, ""):
                if not line:
                    continue
                text = f"{stream_prefix}{line.rstrip()}"

                # Filter out noise — don't store in DB or PM2
                _is_noise = (
                    "Phase progress" in text
                    or "⏱️" in text
                    or "Converted query placeholders" in text
                    or "HTTP Request:" in text
                    or "httpcore" in text
                    or "pipeline_status" in text
                    or "database_postgres" in text
                    or "asyncio" in text.lower()
                    or "docker exec:" in text
                    or "container_manager" in text
                    or "runtime_manager" in text
                    or text.strip() == ""
                    or len(text) > 2000  # skip huge tool result dumps
                )
                if _is_noise:
                    continue

                if stream_prefix:
                    stderr_tail.append(text)
                else:
                    stdout_tail.append(text)

                # Save to DB chunk (UI shows progress).
                try:
                    append_chunk(run_id, "log", text)
                except Exception:
                    pass

                # Detect start of a multi-line diagnostic block.
                _starts_diag = any(m in text for m in _DIAG_START_MARKERS)
                if _starts_diag:
                    # 60 lines is plenty for PM2 jlist, ecosystem config, tracebacks.
                    diag_state["remaining"] = 60
                elif diag_state["remaining"] > 0:
                    diag_state["remaining"] -= 1
                    # Stop early if we hit the next log line (starts with timestamp
                    # + loggername pattern like "... - infrastructure_manager -").
                    if re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+ - \w+ - ", text):
                        diag_state["remaining"] = 0

                # Log important milestones to PM2 only
                _is_important = (
                    "PHASE_" in text
                    or "PAGE-INFERENCE" in text  # page-inference decision chain (planner + LLM)
                    or "✅" in text
                    or "❌" in text
                    or "⚠️" in text
                    or "ACPX:" in text
                    or "completed" in text.lower()
                    or "failed" in text.lower()
                    or "READY" in text
                    or "ERROR" in text
                    or "Traceback" in text
                    or "RuntimeError" in text
                    or "ACP Frontend Editor" in text  # captures partial/fail status
                    or diag_state["remaining"] > 0    # diagnostic continuation
                )
                if _is_important:
                    logger.info("%s", text)
        except Exception as exc:
            logger.warning("[PROJECT-RUN] stream error: %s", exc)
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    stdout_thread = threading.Thread(target=stream, args=(process.stdout, prefix), daemon=True)
    stderr_thread = threading.Thread(target=stream, args=(process.stderr, f"{prefix}STDERR: "), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    try:
        return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise
    finally:
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)

    logger.info("[PROJECT-RUN] process exited with code %s: %s", return_code, " ".join(args))
    if return_code != 0:
        if stdout_tail:
            logger.error("[PROJECT-RUN] stdout tail before failure:\n%s", "\n".join(stdout_tail))
            append_chunk(run_id, "error", "stdout tail before failure:\n" + "\n".join(stdout_tail))
        if stderr_tail:
            logger.error("[PROJECT-RUN] stderr tail before failure:\n%s", "\n".join(stderr_tail))
            append_chunk(run_id, "error", "stderr tail before failure:\n" + "\n".join(stderr_tail))
    append_chunk(run_id, "log", f"Process exited with code {return_code}")
    return return_code


def _run_best_effort_command(args: List[str], path: str) -> None:
    if not args or not shutil.which(args[0]):
        return
    try:
        subprocess.run([*args, path], check=False, capture_output=True, timeout=30)
    except Exception as exc:
        logger.debug("[PROJECT-RUN] best-effort command failed %s: %s", args, exc)


def _fix_project_ownership(project_path: str) -> None:
    """Ensure the dreampilot user owns the scaffolded project tree.

    fast_wrapper rsyncs the template into project_path as root; the files arrive
    owned by root:root. Claude Code runs as the dreampilot user and cannot write
    to root-owned files, so ownership MUST be transferred to dreampilot AFTER
    the scaffold copy completes and BEFORE openclaw invokes claude.
    """
    # Remove any immutable flags first (would block chown/chmod).
    _run_best_effort_command(["chattr", "-R", "-i"], project_path)
    # Transfer ownership to the user claude runs as.
    _run_best_effort_command(["chown", "-R", "dreampilot:dreampilot"], project_path)
    # Ensure the tree is writable + traversable by the owner.
    _run_best_effort_command(["chmod", "-R", "u+rwX"], project_path)
    logger.info("[PROJECT-RUN] ownership transferred to dreampilot for %s", project_path)


def _create_project_folder(run_id: int, project_id: int, name: str, type_id: int, user_id: Optional[int] = None) -> str:
    append_chunk(run_id, "log", "Creating project folder and Git repository")
    project_manager = ProjectFileManager()
    # Phase 4: pass user_id so container mode resolves the per-user workspace path.
    # In local mode (default) user_id is ignored — behavior unchanged.
    project_folder_path, folder_success = project_manager.create_project_with_git(
        project_id, name, type_id, user_id=user_id,
    )
    if not folder_success or not project_folder_path:
        raise RuntimeError("Failed to create project folder, Git repository, and required files")

    _run_best_effort_command(["chattr", "-R", "-i"], project_folder_path)
    _run_best_effort_command(["chown", "-R", "dreampilot:dreampilot"], project_folder_path)
    _run_best_effort_command(["chmod", "-R", "755"], project_folder_path)

    with get_db() as conn:
        conn.execute("UPDATE projects SET project_path = %s WHERE id = %s", (project_folder_path, project_id))
        conn.commit()
    return project_folder_path


def _create_github_repo(run_id: int, project_id: int, project_path: str, domain: str, name: str) -> None:
    try:
        github = get_github_service()
        append_chunk(run_id, "log", f"Creating GitHub repository: {domain}")
        repo_url = github.create_repository(name=domain, public=False, description=f"Project: {name}")
        if not repo_url:
            append_chunk(run_id, "log", "GitHub repository was not created; continuing without remote")
            return

        logger.info("[PROJECT-RUN] GitHub repo created: %s", repo_url)

        # Save repo_url to DB FIRST — even if add_remote fails (git ownership),
        # _push_to_github can recover by reading repo_url from DB.
        with get_db() as conn:
            conn.execute("UPDATE projects SET repo_url = %s WHERE id = %s", (repo_url, project_id))
            conn.commit()
        logger.info("[PROJECT-RUN] Saved repo_url to DB for project %s", project_id)

        # Fix dubious ownership before git commands
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", project_path],
            capture_output=True, text=True, timeout=10,
        )

        # Try to add remote — may fail if git ownership is wrong, but DB has the URL
        try:
            if github.add_remote(project_path, repo_url):
                append_chunk(run_id, "log", f"GitHub remote attached: {repo_url}")
            else:
                logger.warning("[PROJECT-RUN] add_remote returned False for %s", repo_url)
        except Exception as remote_err:
            logger.warning("[PROJECT-RUN] add_remote failed (non-fatal, DB has URL): %s", remote_err)

    except Exception as exc:
        logger.warning("[PROJECT-RUN] GitHub integration failed for project %s: %s", project_id, exc)
        append_chunk(run_id, "log", f"GitHub setup skipped: {exc}")


def _push_to_github(run_id: int, project_id: int, project_path: str) -> None:
    """Push the project code to GitHub after all edits + builds complete.

    Called after the pipeline finishes (ACPX, build, deploy) so the GitHub
    repo reflects the final state of the project — not just the empty git
    init from _create_project_folder.
    """
    try:
        logger.info("[PROJECT-RUN] _push_to_github: project_id=%s path=%s", project_id, project_path)

        # Fix dubious ownership: register project as safe directory for root
        subprocess.run(
            ["git", "config", "--global", "--add", "safe.directory", project_path],
            capture_output=True, text=True, timeout=10,
        )

        # Stage all files (ACPX/build may have created new files since init)
        add_result = subprocess.run(
            ["git", "add", "-A"],
            cwd=project_path, capture_output=True, text=True, timeout=30,
        )
        if add_result.returncode != 0:
            logger.warning("[PROJECT-RUN] git add failed: %s", add_result.stderr[:300])

        # Commit any uncommitted changes
        commit_result = subprocess.run(
            ["git", "commit", "-m", "Initial project creation",
             "--allow-empty"],
            cwd=project_path, capture_output=True, text=True, timeout=30,
        )
        logger.info("[PROJECT-RUN] git commit: rc=%s out=%s", commit_result.returncode, commit_result.stdout[:200])

        # Check if 'origin' remote exists
        remote_result = subprocess.run(
            ["git", "remote", "-v"],
            cwd=project_path, capture_output=True, text=True, timeout=10,
        )
        has_origin = "origin" in remote_result.stdout
        logger.info("[PROJECT-RUN] git remote -v: %s", remote_result.stdout[:200])

        if not has_origin:
            # Try to get repo_url from DB and add it
            with get_db() as conn:
                row = conn.execute(
                    "SELECT repo_url FROM projects WHERE id = %s",
                    (project_id,),
                ).fetchone()
            repo_url = row["repo_url"] if row else None
            logger.info("[PROJECT-RUN] repo_url from DB: %s", repo_url)
            if repo_url:
                subprocess.run(
                    ["git", "remote", "add", "origin", repo_url],
                    cwd=project_path, capture_output=True, text=True, timeout=10,
                )
                has_origin = True

        if not has_origin:
            append_chunk(run_id, "log", "GitHub push skipped — no remote configured")
            logger.warning("[PROJECT-RUN] GitHub push skipped — no remote configured")
            return

        # Push to origin main
        push_result = subprocess.run(
            ["git", "push", "--set-upstream", "origin", "main"],
            cwd=project_path, capture_output=True, text=True, timeout=60,
        )
        logger.info(
            "[PROJECT-RUN] git push: rc=%s out=%s err=%s",
            push_result.returncode, push_result.stdout[:200], push_result.stderr[:200],
        )
        if push_result.returncode == 0:
            logger.info("[PROJECT-RUN] Pushed project %s to GitHub", project_id)
            append_chunk(run_id, "log", "Project code pushed to GitHub")
        else:
            logger.warning(
                "[PROJECT-RUN] Git push failed for project %s: %s",
                project_id, push_result.stderr[:300],
            )
            append_chunk(run_id, "log", f"GitHub push failed: {push_result.stderr[:200]}")
    except Exception as exc:
        logger.warning("[PROJECT-RUN] GitHub push failed for project %s: %s", project_id, exc)
        append_chunk(run_id, "log", f"GitHub push error: {exc}")


def _select_template(run_id: int, project_id: int, name: str, description: str, type_id: int, template_id: Optional[str]) -> Optional[str]:
    selected_template_id = template_id
    if os.getenv("EMPTY_TEMPLATE_MODE", "false").lower() == "true":
        selected_template_id = "blank"
    elif type_id == 1 and not selected_template_id:
        try:
            selector = TemplateSelector()
            if selector.is_available():
                append_chunk(run_id, "log", "Selecting the best website template")
                result = asyncio.run(selector.select_template(
                    project_name=name,
                    project_description=description or "",
                    project_type="website",
                ))
                if result.get("template"):
                    selected_template_id = result["template"]["id"]
        except Exception as exc:
            logger.warning("[PROJECT-RUN] template selection failed: %s", exc)
            append_chunk(run_id, "log", f"Template selection skipped: {exc}")

    if selected_template_id:
        with get_db() as conn:
            conn.execute("UPDATE projects SET template_id = %s WHERE id = %s", (selected_template_id, project_id))
            conn.commit()
    return selected_template_id


def _run_website_pipeline(
    run_id: int,
    project_id: int,
    project_path: str,
    name: str,
    description: str,
    template_id: Optional[str],
    initial_env_vars: List[Dict[str, Any]],
    user_id: Optional[int] = None,
) -> None:
    session_name = f"project-{project_id}-{name.replace(' ', '-')}"
    with get_db() as conn:
        conn.execute(
            "UPDATE projects SET claude_code_session_name = %s WHERE id = %s",
            (session_name, project_id),
        )
        conn.commit()

    env = os.environ.copy()
    env["EMPTY_TEMPLATE_MODE"] = os.getenv("EMPTY_TEMPLATE_MODE", "false")
    env["PYTHONUNBUFFERED"] = "1"
    python_exe = sys.executable

    fast_code = _run_logged_subprocess(
        run_id,
        [
            python_exe,
            "-u",
            str(BACKEND_DIR / "fast_wrapper.py"),
            str(project_id),
            str(project_path),
            str(name),
            str(description or ""),
            str(template_id or ""),
        ],
        env=env,
        timeout=int(os.getenv("PROJECT_CREATION_FAST_TIMEOUT", "3600")),
        prefix="[FAST-WRAPPER] ",
    )
    if fast_code != 0:
        raise RuntimeError(f"fast_wrapper.py failed with exit code {fast_code}")

    # fast_wrapper has just rsync'd the template into project_path (as root).
    # Claude Code runs as the dreampilot user, so transfer ownership now —
    # before openclaw invokes claude, which needs write access to every file.
    _fix_project_ownership(project_path)

    if initial_env_vars:
        env_path = str(Path(project_path) / "backend" / ".env")
        write_initial_environment_variables(env_path, initial_env_vars)
        append_chunk(run_id, "log", f"Initial environment variables applied: {[item.get('key') for item in initial_env_vars]}")

    # Mark the container as having active Claude so the reaper doesn't kill it
    # mid-build. openclaw_wrapper.py invokes Claude inside the container for
    # up to 30 minutes. Without the sentinel, the reaper sees the container
    # as idle (last_used_at is stale) and stops it → build fails (exit 137).
    _mark_container_active(user_id)

    # 45-minute budget for the AI build/enhancement phase. On timeout the
    # process is killed but the AI-edited files are KEPT (no revert to the
    # blank template) — the pipeline continues so a fix edit can complete
    # the project from its current state.
    try:
        openclaw_code = _run_logged_subprocess(
            run_id,
            [
                python_exe,
                "-u",
                str(BACKEND_DIR / "openclaw_wrapper.py"),
                str(project_id),
                str(project_path),
                str(name),
                str(description or ""),
                str(template_id or ""),
            ],
            env=env,
            timeout=int(os.getenv("PROJECT_CREATION_OPENCLAW_TIMEOUT", "2700")),
            prefix="[DREAMAGENT] ",
        )
    except subprocess.TimeoutExpired:
        logger.warning(
            "[PROJECT-RUN] DreamAgent AI phase timed out after %ss for project %s — "
            "keeping AI-edited files (no template revert); continuing so a fix "
            "edit can complete the project",
            os.getenv("PROJECT_CREATION_OPENCLAW_TIMEOUT", "2700"), project_id,
        )
        append_chunk(
            run_id, "warning",
            "AI build phase timed out after 45 min — AI-edited files kept as-is "
            "(not reverted); run a fix edit to check and complete the project.",
        )
        openclaw_code = 0  # don't fail the run — files are preserved

    # Re-touch the sentinel to keep it fresh for the NEXT project in the queue.
    # Don't remove it — removing creates a race window where the parallel
    # worker's next cleanup runs and kills this worker's processes. The
    # 70-minute TTL handles eventual cleanup.
    _mark_container_active(user_id)

    if openclaw_code != 0:
        raise RuntimeError(f"openclaw_wrapper.py failed with exit code {openclaw_code}")


def _run_bot_or_scheduler_pipeline(
    run_id: int,
    project_id: int,
    project_path: str,
    payload: Dict[str, Any],
    type_id: int,
) -> Tuple[bool, Dict[str, Any]]:
    name = payload.get("name") or "Untitled"
    description = payload.get("description_for_worker") or payload.get("description") or ""
    domain = payload.get("domain") or ""
    initial_env_vars = payload.get("initial_environment_variables") or []

    if type_id == 2:
        from services.telegram.worker import run_telegram_bot_pipeline

        append_chunk(run_id, "log", "Starting Telegram bot creation pipeline")
        db_url = _provision_project_database(name, project_id)
        return run_telegram_bot_pipeline(
            project_id=project_id,
            project_name=name,
            description=description,
            bot_token=payload.get("bot_token"),
            project_path=project_path,
            domain=domain,
            port=8000 + (project_id % 1000),
            database_url=db_url,
            initial_environment_variables=initial_env_vars,
        )

    if type_id == 3:
        from services.discord.worker import run_discord_bot_pipeline

        append_chunk(run_id, "log", "Starting Discord bot creation pipeline")
        db_url = _provision_project_database(name, project_id)
        return run_discord_bot_pipeline(
            project_id=project_id,
            project_name=name,
            description=description,
            bot_token=payload.get("bot_token"),
            project_path=project_path,
            domain=domain,
            port=8000 + (project_id % 1000),
            database_url=db_url,
            initial_environment_variables=initial_env_vars,
        )

    if type_id == 5:
        from services.scheduler.worker import run_scheduler_pipeline

        append_chunk(run_id, "log", "Starting scheduler project creation pipeline")
        # backend_url=None lets env_injector.py resolve it from SCHEDULER_BACKEND_URL
        # env (or its hardcoded https://api.dreamagent.cloud default). Passing
        # localhost:8002 here would override the env_injector default and leak
        # into the project's .env — Claude inside the container can't reach it.
        return run_scheduler_pipeline(
            project_id=project_id,
            project_name=name,
            description=description,
            project_path=project_path,
            backend_url=None,
            telegram_bot_token=payload.get("telegram_bot_token"),
            telegram_chat_id=payload.get("telegram_chat_id"),
            discord_webhook_url=payload.get("discord_webhook_url"),
            email_to=payload.get("email_to"),
            api_endpoint=payload.get("api_endpoint"),
            initial_environment_variables=initial_env_vars,
        )

    # Agent — slug-keyed (type ids are SERIAL, never hardcoded)
    try:
        from database_adapter import get_db as _get_db
        with _get_db() as _conn:
            _trow = _conn.execute(
                "SELECT type FROM project_types WHERE id = %s", (type_id,)
            ).fetchone()
        _slug = ""
        if _trow:
            _d = dict(_trow) if not isinstance(_trow, dict) else _trow
            _slug = _d.get("type") or ""
    except Exception:
        _slug = ""
    if _slug == "agent":
        from services.agent import run_agent_pipeline

        append_chunk(run_id, "log", "Starting agent creation pipeline")
        return run_agent_pipeline(
            project_id=project_id,
            project_name=name,
            description=description,
            project_path=project_path,
            backend_url=None,
            telegram_bot_token=payload.get("telegram_bot_token"),
            telegram_chat_id=payload.get("telegram_chat_id"),
            discord_webhook_url=payload.get("discord_webhook_url"),
            email_to=payload.get("email_to"),
            api_endpoint=payload.get("api_endpoint"),
            initial_environment_variables=initial_env_vars,
        )

    return False, {"errors": [f"Unsupported project type: {type_id}"]}


def _refund_if_needed(user_id: int, operation_code: Optional[str], charge_payload: Any) -> None:
    charge = _json_loads(charge_payload, {})
    charged = charge.get("charged") if isinstance(charge, dict) else None
    if not user_id or not operation_code or not charged:
        return
    try:
        from services.billing_service import refund_credits

        with get_db() as conn:
            refund_credits(conn, user_id, operation_code, charged)
            conn.commit()
        logger.info("[PROJECT-RUN] refunded creation credits user=%s operation=%s", user_id, operation_code)
    except Exception as exc:
        logger.warning("[PROJECT-RUN] failed to refund creation credits: %s", exc)


def execute_run(run_id: int) -> Dict[str, Any]:
    run = None
    project_id = None
    user_id = None
    project_path = ""
    charged = False
    try:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM project_creation_runs WHERE id = %s", (run_id,)).fetchone()
        if not row:
            return {"status": "error", "message": "Project creation run not found"}

        run = dict(row)
        project_id = int(run["project_id"])
        user_id = int(run["user_id"])
        type_id = int(run.get("type_id") or 1)
        payload = _json_loads(run.get("payload"), {})
        name = payload.get("name") or "Untitled Project"
        description = payload.get("description_for_worker") or payload.get("description") or ""

        append_chunk(run_id, "log", f"Starting durable project creation for {name}")

        # Clean up orphaned processes in the user's container before starting
        # a new project creation. Previous ACPX/build/MCP processes accumulate
        # (orphaned npm, esbuild, node, chrome-devtools). This prevents PID
        # exhaustion that causes build failures and rollbacks.
        #
        # CRITICAL: if a chat is currently running in the same container, skip
        # the cleanup entirely. The container hosts BOTH the chat's Claude and
        # this project's ACPX Claude. cleanup_processes() would SIGKILL the
        # chat's Claude (exit code 137) and lose the user's in-flight chat.
        # Even with spare_patterns=['claude'], running cleanup adds docker
        # exec overhead and risks edge cases — better to skip when we know
        # there's parallel work.
        try:
            if os.getenv("EXECUTION_MODE", "local").lower() == "container":
                from services.container_manager import ContainerManager
                cm = ContainerManager(user_id)
                if cm._container_exists():
                    # Mark container active BEFORE cleanup so a parallel
                    # worker sees the sentinel and skips its cleanup.
                    # Without this, Worker B's cleanup runs before Worker A
                    # has written the sentinel → Worker B kills Worker A's
                    # processes → exit 137.
                    cm.mark_claude_active()

                    if cm.has_active_claude():
                        # has_active_claude checks the sentinel we just wrote.
                        # But if another worker wrote it FIRST (before us),
                        # that's a true parallel session — skip cleanup.
                        # We can't distinguish "our sentinel" from "their sentinel"
                        # so we check the file age: if it was touched in the last
                        # 2 seconds, it might be ours (just written above).
                        # Simplest safe approach: always skip cleanup if sentinel
                        # exists, since we just wrote it ourselves.
                        logger.warning(
                            "[PROJECT-RUN] active Claude session in %s — "
                            "SKIPPING pre-run cleanup (parallel build protection)",
                            cm.container_name,
                        )
                    else:
                        killed = cm.cleanup_processes()
                        if killed:
                            logger.info("[PROJECT-RUN] pre-run cleanup: killed %d orphaned processes", killed)
        except Exception as exc:
            logger.debug("[PROJECT-RUN] container pre-cleanup skipped: %s", exc)

        from services.billing_service import charge_project_creation

        with get_db() as conn:
            charge_result = charge_project_creation(
                conn,
                user_id,
                project_type_id=type_id,
                project_id=project_id,
            )
            if not charge_result.get("success"):
                conn.rollback()
                error = charge_result.get("error", "insufficient_credits")
                mark_failed(run_id, "failed", f"Project creation billing failed: {error}", project_id)
                append_chunk(run_id, "error", f"Billing failed: {error}")
                return {"status": "error", "message": error}

            operation_code = (charge_result.get("operation") or {}).get("code") or "WEBSITE"
            charge = charge_result.get("charged", [])
            conn.commit()
        charged = True
        _record_charge(run_id, operation_code, charge, charge_result)

        project_path = _create_project_folder(run_id, project_id, name, type_id, user_id=user_id)
        _create_github_repo(run_id, project_id, project_path, payload.get("domain") or "", name)
        selected_template_id = _select_template(
            run_id,
            project_id,
            name,
            payload.get("description") or "",
            type_id,
            payload.get("template_id"),
        )

        if type_id == 1:
            _run_website_pipeline(
                run_id,
                project_id,
                project_path,
                name,
                description,
                selected_template_id,
                payload.get("initial_environment_variables") or [],
                user_id=user_id,
            )
            project = _get_project(project_id)
            # Promote ANY non-terminal status to ready. The strict "== creating"
            # check left projects stuck in intermediate statuses (ai_provisioning,
            # building, deploying, verifying) whenever openclaw was killed — most
            # commonly by the 45-min AI-phase timeout, whose handler intentionally
            # continues the run with the AI-edited files kept.
            if project and project.get("status") not in ("ready", "failed"):
                _set_project_status(project_id, "ready")
        else:
            success, result = _run_bot_or_scheduler_pipeline(run_id, project_id, project_path, payload, type_id)
            if success:
                _set_project_status(project_id, "ready")
            else:
                errors = result.get("errors") if isinstance(result, dict) else None
                raise RuntimeError("; ".join(errors or ["Project pipeline failed"]))

        # Push the final project code to GitHub (after all edits/builds/deploy).
        # The repo was created earlier in _create_github_repo but only the
        # remote was attached — no push happened. This pushes the complete
        # project state including ACPX-generated code, builds, and configs.
        _push_to_github(run_id, project_id, project_path)

        record_usage(
            user_id=user_id,
            usage_type="project_create",
            total_tokens=1,
            project_id=project_id,
            description=f"Created project: {name} (domain: {payload.get('domain')})",
        )
        mark_completed(run_id, has_writes=True)
        append_chunk(run_id, "log", "Project creation completed")
        return {"status": "success", "project_id": project_id}

    except Exception as exc:
        logger.error("[PROJECT-RUN] run %s failed: %s", run_id, exc, exc_info=True)
        capture_exception(
            exc,
            tags={
                "service": "project-creation-worker",
                "run_id": run_id,
                "project_id": project_id,
                "user_id": user_id,
                "type_id": run.get("type_id") if run else None,
            },
            context={
                "project_path": project_path,
                "charged": charged,
            },
        )
        append_chunk(run_id, "error", f"Project creation failed: {exc}")
        if project_id:
            _set_project_status(project_id, "failed", "creation_worker_failed")
        if charged and run:
            with get_db() as conn:
                latest = conn.execute(
                    "SELECT operation_code, charge FROM project_creation_runs WHERE id = %s",
                    (run_id,),
                ).fetchone()
            _refund_if_needed(user_id, _row_value(latest, "operation_code"), _row_value(latest, "charge", 1))
        mark_failed(run_id, "failed", str(exc), project_id)
        return {"status": "error", "message": str(exc)}


def recover_stale_runs(stale_after_minutes: int = 20) -> int:
    cutoff = datetime.utcnow() - timedelta(minutes=stale_after_minutes)
    recovered = 0
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, project_id, user_id, operation_code, charge
            FROM project_creation_runs
            WHERE status = 'running'
              AND (heartbeat_at IS NULL OR heartbeat_at < %s)
            """,
            (cutoff,),
        ).fetchall()
        for row in rows:
            run_id = _row_value(row, "id")
            project_id = _row_value(row, "project_id", 1)
            user_id = _row_value(row, "user_id", 2)
            operation_code = _row_value(row, "operation_code", 3)
            charge = _row_value(row, "charge", 4)
            message = "Project creation was interrupted because the worker stopped before this run finished."
            conn.execute(
                """
                UPDATE project_creation_runs
                SET status = 'interrupted',
                    error = %s,
                    completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (message, run_id),
            )
            conn.execute(
                "UPDATE projects SET status = 'failed', error_code = 'creation_worker_interrupted' WHERE id = %s AND status NOT IN ('ready', 'failed')",
                (project_id,),
            )
            recovered += 1
            _refund_if_needed(user_id, operation_code, charge)
        conn.commit()
    if recovered:
        logger.warning("[PROJECT-RUN] recovered %s stale project creation runs", recovered)
    return recovered


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"
