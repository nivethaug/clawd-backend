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
# IMPORTANT: Set WEBHOOK_URL or WEBHOOK_DOMAIN in environment for production
# If not set, webhook registration will be skipped (useful for development/polling mode)
WEBHOOK_PORT = int(os.getenv("PORT", "8010"))  # Port for FastAPI server
WEBHOOK_DOMAIN = os.getenv("WEBHOOK_DOMAIN")  # Domain (e.g., mybot.dreambigwithai.com)
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")

# Construct webhook URL - only set if properly configured
WEBHOOK_URL = None
if os.getenv("WEBHOOK_URL"):
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
elif WEBHOOK_DOMAIN and WEBHOOK_DOMAIN != "example.com":
    WEBHOOK_URL = f"https://{WEBHOOK_DOMAIN}{WEBHOOK_PATH}"
