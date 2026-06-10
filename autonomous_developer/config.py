"""
Autonomous Developer — Configuration
All settings loaded from environment variables with sensible defaults.
"""

import os
from pathlib import Path

# ── Paths ──────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

STATE_FILE = DATA_DIR / "codex_usage_state.json"
LOCK_FILE = DATA_DIR / "codex_maintainer.lock"
LOG_FILE = DATA_DIR / "codex_maintainer.log"
CRON_LOG_FILE = DATA_DIR / "codex_cron.log"
QA_DB_PATH = Path(os.getenv("QA_DB_PATH", r"D:\clawduiback\ai-qa-tester\qa_tester.db"))

# ── Wrapper / Codex ────────────────────────────────────
WRAPPER_PATH = Path(os.getenv("WRAPPER_PATH", r"D:\claudewrapper\context_api.py"))
CODEX_REPO_PATH = Path(os.getenv("CODEX_REPO_PATH", r"D:\claudewrapper"))
CODEX_TIMEOUT = int(os.getenv("CODEX_TIMEOUT", "600"))           # 10 minutes

# ── PM2 ────────────────────────────────────────────────
PM2_PROCESS = os.getenv("PM2_PROCESS", "clawd-backend")

# ── Backend API ────────────────────────────────────────
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
WRAPPER_HEALTH_URL = os.getenv("WRAPPER_HEALTH_URL", "http://localhost:7861/health")

# ── Polling ────────────────────────────────────────────
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "12"))             # seconds
PROJECT_TIMEOUT = int(os.getenv("PROJECT_TIMEOUT", "600"))        # 10 minutes

# ── Safety ─────────────────────────────────────────────
MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "10"))
MAX_SUBPROCESS_TIMEOUT = int(os.getenv("MAX_SUBPROCESS_TIMEOUT", "1200"))  # 20 min

# ── Usage Tracker ──────────────────────────────────────
USAGE_LIMIT_HOURS = int(os.getenv("USAGE_LIMIT_HOURS", "5"))
USAGE_LIMIT_SECONDS = USAGE_LIMIT_HOURS * 3600
RESET_INTERVAL_HOURS = int(os.getenv("RESET_INTERVAL_HOURS", "24"))

# ── Notifications ──────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# ── Test Project Defaults ──────────────────────────────
DEFAULT_USER_ID = int(os.getenv("DEFAULT_USER_ID", "1"))
DEFAULT_TEMPLATE_ID = os.getenv("DEFAULT_TEMPLATE_ID", "blank-template")

# ── Log Format ─────────────────────────────────────────
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
