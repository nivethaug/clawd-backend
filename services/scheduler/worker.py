#!/usr/bin/env python3
"""
Scheduler Worker - Main orchestration pipeline for scheduler project creation.

Pattern: Same as services/telegram/worker.py but simpler:
- No PM2 (centralized scheduler)
- No nginx/DNS/webhook
- AI enhances executor.py
- Job creation happens later via LLM chat

Steps:
1. Copy template
2. Inject .env
3. AI enhance executor.py
4. Save project.json
5. Mark ready
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Tuple, Dict

from utils.logger import logger

from services.scheduler.template import copy_scheduler_template
from services.scheduler.env_injector import inject_scheduler_env
from services.scheduler.editor import SchedulerEditor
from services.scheduler.validator import validate_scheduler_project


def run_scheduler_pipeline(
    project_id: int,
    project_name: str,
    description: str,
    project_path: str,
    backend_url: str = None,
    **kwargs
) -> Tuple[bool, Dict]:
    """
    Run complete scheduler project creation pipeline.

    Args:
        project_id: Project ID
        project_name: Project name
        description: User description (for AI enhancement)
        project_path: Base project path
        backend_url: Backend API URL for job_manager
        **kwargs: Optional task tokens (telegram_bot_token, discord_bot_token, smtp_*)

    Returns:
        (success, result_info)
    """
    logger.info(f"🚀 Starting scheduler pipeline for project {project_id}")
    logger.info(f"Project: {project_name}")

    result_info = {
        "project_id": project_id,
        "project_name": project_name,
        "steps_completed": [],
        "errors": []
    }

    try:
        # Step 1: Copy template
        logger.info("📋 Step 1/4: Copying scheduler template...")
        success, template_result = copy_scheduler_template(project_path)

        if not success:
            error_msg = f"Template copy failed: {template_result}"
            logger.error(f"❌ {error_msg}")
            result_info["errors"].append(error_msg)
            return False, result_info

        scheduler_path = template_result
        logger.info(f"✅ Template copied to {scheduler_path}")
        result_info["scheduler_path"] = scheduler_path
        result_info["steps_completed"].append("template_copy")

        # Step 2: Inject environment
        logger.info("📋 Step 2/4: Injecting environment variables...")
        success, env_result = inject_scheduler_env(
            project_path=scheduler_path,
            project_id=project_id,
            backend_url=backend_url,
            telegram_bot_token=kwargs.get("telegram_bot_token"),
            telegram_chat_id=kwargs.get("telegram_chat_id"),
            discord_webhook_url=kwargs.get("discord_webhook_url"),
            smtp_host=kwargs.get("smtp_host"),
            smtp_port=kwargs.get("smtp_port"),
            smtp_user=kwargs.get("smtp_user"),
            smtp_pass=kwargs.get("smtp_pass"),
            email_to=kwargs.get("email_to"),
            api_endpoint=kwargs.get("api_endpoint"),
        )

        if not success:
            error_msg = f"Environment injection failed: {env_result}"
            logger.error(f"❌ {error_msg}")
            result_info["errors"].append(error_msg)
            return False, result_info

        logger.info(f"✅ Environment configured")
        result_info["steps_completed"].append("env_injection")

        # Step 3: AI enhance executor.py
        logger.info("📋 Step 3/4: AI enhancement of executor.py...")
        try:
            editor = SchedulerEditor(project_path)
            success, edit_result = editor.enhance_executor(description, project_name)

            if success:
                logger.info(f"✅ AI enhancement: {edit_result}")
                result_info["ai_enhancement"] = edit_result
                result_info["steps_completed"].append("ai_enhancement")
            else:
                logger.warning(f"⚠️ AI enhancement failed: {edit_result}")
                result_info["ai_enhancement"] = f"failed: {edit_result}"
                # Continue anyway - base executor still works

        except Exception as e:
            logger.warning(f"⚠️ AI enhancement error: {e} - continuing with base executor")
            result_info["ai_enhancement"] = f"error: {e}"

        # Step 4: Validate + Save metadata
        logger.info("📋 Step 4/4: Validating and saving metadata...")

        # Validate
        is_valid, validation_info = validate_scheduler_project(project_path)
        result_info["validation"] = validation_info

        if not is_valid:
            logger.warning(f"⚠️ Validation warning: {validation_info}")

        # Save project.json
        _save_project_metadata(
            project_path=project_path,
            project_id=project_id,
            project_name=project_name,
            scheduler_path=scheduler_path,
            description=description,
        )
        result_info["steps_completed"].append("metadata_saved")

        logger.info(f"🎉 Scheduler pipeline completed for project {project_id}")

        return True, result_info

    except Exception as e:
        error_msg = f"Pipeline error: {e}"
        logger.error(f"❌ {error_msg}")
        result_info["errors"].append(error_msg)
        return False, result_info


def _save_project_metadata(
    project_path: str,
    project_id: int,
    project_name: str,
    scheduler_path: str,
    description: str,
) -> bool:
    """Save project.json for cleanup support."""
    try:
        metadata = {
            "project_id": project_id,
            "project_name": project_name,
            "type_id": 5,
            "description": description,
            "scheduler_path": scheduler_path,
            "status": "ready",
            "created_at": datetime.utcnow().isoformat(),
        }

        metadata_path = Path(project_path) / "project.json"
        metadata_path.write_text(json.dumps(metadata, indent=2))

        logger.info(f"✅ Project metadata saved: {metadata_path}")
        return True

    except Exception as e:
        logger.error(f"Failed to save metadata: {e}")
        return False
