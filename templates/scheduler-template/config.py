#!/usr/bin/env python3
"""
Configuration - Environment variables for the scheduler project.
No database credentials — jobs are managed centrally in main DB.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Project Identity
PROJECT_ID = os.getenv("PROJECT_ID", "1")
PROJECT_PATH = os.getenv("PROJECT_PATH", os.path.dirname(os.path.abspath(__file__)))

# Channel: Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Channel: Discord
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# Channel: Email
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")

# Channel: API
API_ENDPOINT = os.getenv("API_ENDPOINT", "")

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
