#!/usr/bin/env python3
"""
Configuration - Load environment variables.
"""

import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Discord
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")

# Database
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "dreampilot")
DB_USER = os.getenv("DB_USER", "admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")

# Database URL (constructed from parts)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# Bot settings
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "!")

# Server settings
PORT = int(os.getenv("PORT", "8010"))
PROJECT_ID = os.getenv("PROJECT_ID", "1")
