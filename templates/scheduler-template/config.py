#!/usr/bin/env python3
"""
Configuration - Environment variables for the scheduler project.
No database credentials — jobs are managed centrally in main DB.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the directory where config.py lives (project root),
# not from cwd (which may be the backend directory for daemon processes).
# override=True is CRITICAL: the centralized scheduler loads multiple
# projects in the same process. Without override=True, the first project's
# env vars win and subsequent projects inherit stale values (wrong email, etc.)
_project_dir = Path(__file__).resolve().parent
load_dotenv(_project_dir / ".env", override=True)

# Project Identity
PROJECT_ID = os.getenv("PROJECT_ID", "1")
PROJECT_PATH = os.getenv("PROJECT_PATH", os.path.dirname(os.path.abspath(__file__)))

# Channel: Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Channel: Discord
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# Channel: Email — send via the platform's internal delivery API
# (POST {BACKEND_URL}/internal/email/send). Only EMAIL_TO is
# project-specific; the relay credentials live platform-side and are
# never exposed to this project.
EMAIL_TO = os.getenv("EMAIL_TO", "")

# Channel: API
API_ENDPOINT = os.getenv("API_ENDPOINT", "")

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
