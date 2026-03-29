"""
Configuration module.
Centralized config for easy AI modifications.
"""

import os

# Bot Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_NAME = os.getenv("BOT_NAME", "AI Assistant Bot")

# API Configuration
API_TIMEOUT = int(os.getenv("API_TIMEOUT", "10"))
DEFAULT_CURRENCY = os.getenv("DEFAULT_CURRENCY", "usd")

# Database Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/telegram_bot")

# JWT Configuration (for API auth)
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", "24"))

# Webhook Configuration
WEBHOOK_PORT = int(os.getenv("PORT", "8010"))  # Port for FastAPI server
WEBHOOK_DOMAIN = os.getenv("WEBHOOK_DOMAIN", "example.com")  # Domain (e.g., mybot.dreambigwithai.com)
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")
WEBHOOK_URL = f"https://{WEBHOOK_DOMAIN}{WEBHOOK_PATH}" if WEBHOOK_DOMAIN else None
