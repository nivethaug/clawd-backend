#!/usr/bin/env python3
"""
Agent Worker - Automation agent project creation pipeline.

Same shape as services/scheduler/worker.py but:
  - copies templates/agent-template/ (capability layer baked in)
  - generates + stores a per-project SECRET_KEY (projects.secret_key) and
    writes it into the project .env so executor proxy_call() works
  - enhances via AgentEditor (agent-voiced capability-menu prompt)
  - saves project.json with type "agent"

Reuses unchanged: inject_scheduler_env (channels), validator (path-based),
central jobs/worker/execution infrastructure.
"""

import json
import logging
import secrets
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("services.agent.worker")

from services.scheduler.template import copy_scheduler_template
from services.scheduler.env_injector import inject_scheduler_env
from services.agent.editor import AgentEditor, _agent_type_id
from services.scheduler.validator import validate_scheduler_project
from project_initial_env import write_initial_environment_variables


def _ensure_project_secret(project_id: int, project_path: str) -> Optional[str]:
    """Generate a fresh per-project secret, store in projects.secret_key
    (cross-VPS proxy auth) and append SECRET_KEY= to the project .env.

    Mirrors the website-creation pattern (infrastructure_manager) and the
    scheduler-clone pattern (app.py). Never overwrites an existing key —
    regenerating would break the .env↔DB pairing."""
    from database_adapter import get_db

    env_path = Path(project_path) / ".env"

    # Existing DB key wins (idempotent re-runs after partial failures)
    with get_db() as conn:
        row = conn.execute(
            "SELECT secret_key FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
    existing = ((dict(row) if row and not isinstance(row, dict) else row) or {}).get("secret_key") if row else None

    key = existing or secrets.token_urlsafe(32)
    if not existing:
        with get_db() as conn:
            conn.execute(
                "UPDATE projects SET secret_key = %s WHERE id = %s",
                (key, project_id),
            )
            conn.commit()
        logger.info("[AGENT] project %s secret_key stored in DB", project_id)

    # Write into the project .env if missing (env_injector rewrites the whole
    # file, so this runs AFTER it; SECRET_KEY is a SYSTEM_KEY for env_manager
    # rewrites — the DB copy remains the durable source).
    if env_path.exists():
        content = env_path.read_text()
        if "SECRET_KEY=" not in content:
            with open(env_path, "a", encoding="utf-8") as fh:
                fh.write(f"\nSECRET_KEY={key}\n")
            logger.info("[AGENT] SECRET_KEY appended to project %s .env", project_id)
    return key


def run_agent_pipeline(
    project_id: int,
    project_name: str,
    description: str,
    project_path: str,
    backend_url: str = None,
    initial_environment_variables: Optional[List[Dict[str, Any]]] = None,
    **kwargs
) -> Tuple[bool, Dict]:
    """Run complete automation agent creation pipeline.

    Returns (success, result_info)."""
    logger.info("🚀 Starting agent pipeline for project %s (%s)", project_id, project_name)

    result_info = {
        "project_id": project_id,
        "project_name": project_name,
        "steps_completed": [],
        "errors": []
    }

    try:
        # Step 1: Copy agent template
        success, template_result = copy_scheduler_template(project_path, template_name="agent-template")
        if not success:
            result_info["errors"].append(f"Template copy failed: {template_result}")
            return False, result_info
        logger.info("✅ Agent template copied")
        result_info["steps_completed"].append("template_copy")

        # Step 2: Inject environment (channels — all optional for agents;
        # users describe delivery in the prompt and configure later)
        success, env_result = inject_scheduler_env(
            project_path=project_path,
            project_id=project_id,
            backend_url=backend_url,
            telegram_bot_token=kwargs.get("telegram_bot_token"),
            telegram_chat_id=kwargs.get("telegram_chat_id"),
            discord_webhook_url=kwargs.get("discord_webhook_url"),
            email_to=kwargs.get("email_to"),
            api_endpoint=kwargs.get("api_endpoint"),
        )
        if not success:
            result_info["errors"].append(f"Environment injection failed: {env_result}")
            return False, result_info
        result_info["steps_completed"].append("env_injection")

        # Step 3: Per-project SECRET_KEY (proxy auth for OAuth actions) +
        # webhook trigger token (public /api/triggers/{token} ingress)
        _ensure_project_secret(project_id, project_path)
        try:
            from api.triggers_router import _ensure_trigger_token
            _ensure_trigger_token(project_id)
        except Exception as e:
            logger.warning("[AGENT] trigger token generation deferred: %s", e)
        result_info["steps_completed"].append("secret_key")

        # Step 4: Initial env vars (vault imports / custom keys)
        initial_env_vars = initial_environment_variables or []
        if initial_env_vars:
            write_initial_environment_variables(str(Path(project_path) / ".env"), initial_env_vars)
            result_info["steps_completed"].append("initial_env_injection")

        # Step 5: AI enhancement (agent-voiced capability prompt)
        try:
            editor = AgentEditor(project_path, project_id=project_id, backend_url=backend_url)
            success, edit_result = editor.enhance_executor(description, project_name)
            if success:
                result_info["ai_enhancement"] = edit_result
                result_info["steps_completed"].append("ai_enhancement")

                try:
                    from services.token_tracker import record_from_token_usage_json
                    from database_adapter import get_db
                    usage = getattr(editor, '_last_token_usage', None)
                    if usage:
                        with get_db() as conn:
                            row = conn.execute(
                                "SELECT user_id FROM projects WHERE id = %s", (project_id,)
                            ).fetchone()
                        _uid = row["user_id"] if row else None
                        if _uid:
                            record_from_token_usage_json(
                                user_id=_uid,
                                token_usage_json=usage,
                                usage_type="project_create",
                                project_id=project_id,
                                description=f"Agent create: {project_name}",
                            )
                except Exception as track_err:
                    logger.warning("Token tracking failed: %s", track_err)
            else:
                logger.warning("⚠️ AI enhancement failed: %s", edit_result)
                result_info["ai_enhancement"] = f"failed: {edit_result}"
                # Continue anyway — base executor still works
        except Exception as e:
            logger.warning("⚠️ AI enhancement error: %s — continuing with base executor", e)
            result_info["ai_enhancement"] = f"error: {e}"

        # Step 6: Validate + save metadata
        is_valid, validation_info = validate_scheduler_project(project_path)
        result_info["validation"] = validation_info
        if not is_valid:
            logger.warning("⚠️ Validation warning: %s", validation_info)

        metadata = {
            "project_id": project_id,
            "project_name": project_name,
            "type_id": _agent_type_id(),
            "type": "agent",
            "description": description,
            "scheduler_path": project_path,
            "status": "ready",
            "created_at": datetime.utcnow().isoformat(),
        }
        (Path(project_path) / "project.json").write_text(json.dumps(metadata, indent=2))
        result_info["steps_completed"].append("metadata_saved")

        logger.info("🎉 Agent pipeline completed for project %s", project_id)
        return True, result_info

    except Exception as e:
        logger.error("❌ Agent pipeline error: %s", e, exc_info=True)
        result_info["errors"].append(f"Pipeline error: {e}")
        return False, result_info
