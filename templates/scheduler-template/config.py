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

# Task: Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Task: Discord
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")

# Task: Email
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
