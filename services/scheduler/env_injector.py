#!/usr/bin/env python3
"""
Scheduler Env Injector - Creates .env file for scheduler project.

Injects PROJECT_ID, PROJECT_PATH, BACKEND_URL, and sender channel config.
At least one sender channel must be provided so jobs can deliver notifications.

Sender channels:
  - Telegram: bot_token + chat_id
  - Discord:  webhook_url
  - Email:    email_to (SMTP is shared from backend .env)
  - API:      api_endpoint URL

No DATABASE_URL — jobs are in main DB, managed centrally.
"""

import os
from pathlib import Path
from typing import Tuple
from dotenv import load_dotenv

import logging
from utils.logger import logger  # noqa: F811 — reassign below
logger = logging.getLogger("services.scheduler.env_injector")

from domain_config import DEFAULT_SUPPORT_EMAIL, DEFAULT_FROM_EMAIL

# Load backend .env for default values
load_dotenv()


def inject_scheduler_env(
    project_path: str,
    project_id: int,
    backend_url: str = None,
    # Telegram channel
    telegram_bot_token: str = None,
    telegram_chat_id: str = None,
    # Discord channel
    discord_webhook_url: str = None,
    # Email channel (SMTP comes from backend .env, only recipient needed)
    email_to: str = None,
    # API channel
    api_endpoint: str = None,
) -> Tuple[bool, str]:
    """
    Create .env file for the scheduler project.

    Args:
        project_path: Path to scheduler/ directory
        project_id: Project ID
        backend_url: Backend API URL for job_manager
        telegram_bot_token: Telegram bot token
        telegram_chat_id: Default Telegram chat ID for notifications
        discord_webhook_url: Discord webhook URL for notifications
        email_to: Default email recipient (SMTP credentials from backend .env)
        api_endpoint: Default API endpoint URL

    Returns:
        (True, path) on success, (False, error) on failure
    """
    scheduler_path = Path(project_path)

    if not scheduler_path.exists():
        return False, f"Scheduler directory not found: {scheduler_path}"

    # Default backend URL — where job_manager.py sends /api/scheduler/* calls.
    # Resolution order:
    #   1. Explicit backend_url arg (caller knows best)
    #   2. SCHEDULER_BACKEND_URL env (operator config)
    #   3. Hardcoded public API URL (safe default — works from Docker/bwrap)
    #
    # We NEVER default to localhost:8002. The executor runs inside a Docker
    # container or bwrap sandbox on the worker VPS where localhost is empty.
    # The only always-reachable URL is the public API. localhost only works
    # in local dev (EXECUTION_MODE != container), which is handled by the
    # SCHEDULER_BACKEND_URL env override.
    if not backend_url:
        backend_url = os.getenv("SCHEDULER_BACKEND_URL", "https://api.dreamagent.cloud")

    # SMTP from backend .env (shared - Hostinger)
    smtp_host = os.getenv("SMTP_HOST", "smtp.hostinger.com")
    smtp_port = os.getenv("SMTP_PORT", "465")
    smtp_user = os.getenv("SMTP_USER", DEFAULT_SUPPORT_EMAIL)
    smtp_pass = os.getenv("SMTP_PASS", "Nivetha@3117")
    smtp_from = os.getenv("SMTP_FROM", DEFAULT_FROM_EMAIL)  # From alias

    # Build env content
    lines = [
        f"PROJECT_ID={project_id}",
        f"PROJECT_PATH={scheduler_path}",
        f"BACKEND_URL={backend_url}",
    ]

    # --- Telegram channel ---
    if telegram_bot_token:
        lines.append(f"\n# Channel: Telegram")
        lines.append(f"TELEGRAM_BOT_TOKEN={telegram_bot_token}")
        if telegram_chat_id:
            lines.append(f"TELEGRAM_CHAT_ID={telegram_chat_id}")

    # --- Discord channel ---
    if discord_webhook_url:
        lines.append(f"\n# Channel: Discord")
        lines.append(f"DISCORD_WEBHOOK_URL={discord_webhook_url}")

    # --- Email channel (SMTP auto-injected from backend, only recipient per-project) ---
    if email_to:
        lines.append(f"\n# Channel: Email")
        lines.append(f"SMTP_HOST={smtp_host}")
        lines.append(f"SMTP_PORT={smtp_port}")
        lines.append(f"SMTP_USER={smtp_user}")
        if smtp_pass:
            lines.append(f"SMTP_PASS={smtp_pass}")
        lines.append(f"SMTP_FROM={smtp_from}")
        lines.append(f"EMAIL_TO={email_to}")

    # --- API channel ---
    if api_endpoint:
        lines.append(f"\n# Channel: API")
        lines.append(f"API_ENDPOINT={api_endpoint}")

    # Write .env file
    env_path = scheduler_path / ".env"
    try:
        with open(env_path, 'w') as f:
            f.write("\n".join(lines) + "\n")

        logger.info(f"✅ Environment configured at {env_path}")
        return True, str(env_path)

    except Exception as e:
        error_msg = f"Failed to write .env: {e}"
        logger.error(f"❌ {error_msg}")
        return False, error_msg
