#!/usr/bin/env python3
"""
Configuration - Environment variables for the scheduler project.
No database credentials — jobs are managed centrally in main DB.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the directory where config.py lives (project root),
# not from cwd (which may be the backend directory for daemon processes)
_project_dir = Path(__file__).resolve().parent
load_dotenv(_project_dir / ".env")

# Project Identity
PROJECT_ID = os.getenv("PROJECT_ID", "1")
PROJECT_PATH = os.getenv("PROJECT_PATH", os.path.dirname(os.path.abspath(__file__)))

# Channel: Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Channel: Discord
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# Channel: Email (SMTP auto-injected from backend .env, only EMAIL_TO per-project)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.hostinger.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "support@dreambigwithai.com")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", "dreamagent@dreambigwithai.com")  # From alias
EMAIL_TO = os.getenv("EMAIL_TO", "")

# Channel: API
API_ENDPOINT = os.getenv("API_ENDPOINT", "")

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
