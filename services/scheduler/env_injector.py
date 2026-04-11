#!/usr/bin/env python3
"""
Scheduler Env Injector - Creates .env file for scheduler project.

Pattern: Same as services/telegram/env_injector.py.
Injects PROJECT_ID, PROJECT_PATH, BACKEND_URL, and task tokens.
No DATABASE_URL — jobs are in main DB, managed centrally.
"""

import os
from pathlib import Path
from typing import Tuple, Optional
from dotenv import load_dotenv

from utils.logger import logger

# Load backend .env for default values
load_dotenv()


def inject_scheduler_env(
    project_path: str,
    project_id: int,
    backend_url: str = None,
    telegram_bot_token: str = None,
    discord_bot_token: str = None,
    smtp_host: str = None,
    smtp_port: int = None,
    smtp_user: str = None,
    smtp_pass: str = None,
) -> Tuple[bool, str]:
    """
    Create .env file for the scheduler project.

    Args:
        project_path: Path to scheduler/ directory
        project_id: Project ID
        backend_url: Backend API URL for job_manager
        telegram_bot_token: Optional telegram token
        discord_bot_token: Optional discord token
        smtp_*: Optional SMTP credentials

    Returns:
        (True, path) on success, (False, error) on failure
    """
    scheduler_path = Path(project_path)

    if not scheduler_path.exists():
        return False, f"Scheduler directory not found: {scheduler_path}"

    # Default backend URL
    if not backend_url:
        backend_port = os.getenv("PORT", "8000")
        backend_url = f"http://localhost:{backend_port}"

    # Read .env.example as base if it exists
    env_example_path = scheduler_path / ".env.example"
    if env_example_path.exists():
        with open(env_example_path, 'r') as f:
            env_content = f.read()
    else:
        env_content = ""

    # Build env content
    lines = [
        f"PROJECT_ID={project_id}",
        f"PROJECT_PATH={scheduler_path}",
        f"BACKEND_URL={backend_url}",
    ]

    # Task tokens (only if provided)
    if telegram_bot_token:
        lines.append(f"\n# Task: Telegram\nTELEGRAM_BOT_TOKEN={telegram_bot_token}")

    if discord_bot_token:
        lines.append(f"\n# Task: Discord\nDISCORD_BOT_TOKEN={discord_bot_token}")

    if smtp_host:
        lines.append(f"\n# Task: Email")
        lines.append(f"SMTP_HOST={smtp_host}")
        lines.append(f"SMTP_PORT={smtp_port or 587}")
        if smtp_user:
            lines.append(f"SMTP_USER={smtp_user}")
        if smtp_pass:
            lines.append(f"SMTP_PASS={smtp_pass}")

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
