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
# The webhook URL is registered with Telegram so it can send updates to our bot.
# nginx routes {domain}-api.dreamagent.cloud → bot port. The webhook MUST use
# the -api domain, not the bare domain (which is for the frontend, not the bot).
WEBHOOK_PORT = int(os.getenv("PORT", "8010"))  # Port for FastAPI server
WEBHOOK_DOMAIN = os.getenv("WEBHOOK_DOMAIN")  # Bare domain (e.g., mybot-abc123)
WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")

# Construct webhook URL - only set if properly configured.
# Uses {domain}-api.dreamagent.cloud (the backend API domain where nginx
# routes the /webhook endpoint to this bot's port).
WEBHOOK_URL = None
if os.getenv("WEBHOOK_URL"):
    # Explicit full URL takes priority
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
elif WEBHOOK_DOMAIN and WEBHOOK_DOMAIN != "example.com":
    # Construct from domain + -api suffix + path
    WEBHOOK_URL = f"https://{WEBHOOK_DOMAIN}-api.dreamagent.cloud{WEBHOOK_PATH}"
