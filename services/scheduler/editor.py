#!/usr/bin/env python3
"""
Scheduler AI Editor - Enhances executor.py based on user description.

Pattern: Same as services/telegram/editor.py.
Uses Claude Code Agent to modify executor.py + api_client.py.
Adds task handlers, API helpers, and FETCH_DATA_REGISTRY entries.
"""

import shutil
from pathlib import Path
from typing import Tuple

from utils.logger import logger

try:
    from claude_code_agent import ClaudeCodeAgent
    CLAUDE_AVAILABLE = True
except ImportError:
    CLAUDE_AVAILABLE = False
    logger.warning("ClaudeCodeAgent not available - AI enhancement disabled")


class SchedulerEditor:
    """AI-powered scheduler executor enhancer."""

    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.executor_path = self.project_path / "scheduler" / "executor.py"
        self.api_client_path = self.project_path / "services" / "api_client.py"
        self.backup_executor = self.project_path / "scheduler" / "executor.py.backup"
        self.backup_api_client = self.project_path / "services" / "api_client.py.backup"

    def enhance_executor(self, description: str, project_name: str) -> Tuple[bool, str]:
        """
        Enhance executor.py using Claude AI.

        Args:
            description: User's description (e.g., "send BTC price via email every 10min")
            project_name: Project name

        Returns:
            (success, message)
        """
        if not CLAUDE_AVAILABLE:
            return True, "AI enhancement skipped (Claude not available)"

        try:
            # Verify executor.py exists
            if not self.executor_path.exists():
                return False, f"executor.py not found at {self.executor_path}"

            # Create backups
            shutil.copy2(self.executor_path, self.backup_executor)
            if self.api_client_path.exists():
                shutil.copy2(self.api_client_path, self.backup_api_client)

            # Build prompt
            prompt = self._build_prompt(description, project_name)

            # Run Claude
            logger.info(f"Running AI enhancement for: {description}")
            result = self._run_claude(prompt)

            if result.get("success"):
                # Validate
                is_valid, msg = self._validate()
                if is_valid:
                    # Remove backups
                    if self.backup_executor.exists():
                        self.backup_executor.unlink()
                    if self.backup_api_client.exists():
                        self.backup_api_client.unlink()
                    return True, "Executor enhanced successfully"
                else:
                    self._rollback()
                    return False, f"Validation failed: {msg}"
            else:
                self._rollback()
                return False, f"AI modification failed: {result.get('error')}"

        except Exception as e:
            self._rollback()
            return False, f"Enhancement error: {e}"

    def _build_prompt(self, description: str, project_name: str) -> str:
        """Build AI prompt for executor enhancement."""
        return f"""
Enhance the scheduler executor for: {description}

Project: {project_name}

Allowed files to modify ONLY:
- scheduler/executor.py (add task handlers + routes)
- services/api_client.py (add API helper functions)

DO NOT modify any other files.

==================================================
INTENT DETECTION & API SELECTION
==================================================

ANALYZE user description: "{description}"

During initial creation, you have FULL AUTONOMY to:
1. Match description to BEST category from /llm/categories/index.json
2. Select appropriate public APIs from that category
3. Add helper functions to services/api_client.py
4. Add task handlers to scheduler/executor.py
5. Register new routes in execute_task()
6. Add FETCH_DATA_REGISTRY entries for dynamic content

EXAMPLES:
- "weather update every hour" → add get_weather() to api_client, add _weather_alert() to executor, register as "weather_alert"
- "BTC price via email every 10min" → add get_crypto_price() to api_client, add _btc_email() to executor, register as "btc_email"
- "news digest daily" → add get_news() to api_client, add _news_digest() to executor, register as "news_digest"
- "monitor website every 5min" → add check_website() to api_client, add _monitor_site() to executor, register as "site_monitor"

==================================================
EXECUTOR.PY STRUCTURE
==================================================

The executor has TWO extension points:

1. FETCH_DATA_REGISTRY - for dynamic {{variable}} resolution:
   FETCH_DATA_REGISTRY["btc_price"] = lambda: _fetch_crypto("bitcoin")

2. execute_task() routing - for task_type handlers:
   elif task_type == "btc_email":
       status, message = _btc_email(payload)

Add your handlers BELOW existing ones. Keep existing handlers intact.

==================================================
JOB MANAGEMENT - CREATE JOBS
==================================================

After adding handlers, create the job using job_manager:

    from scheduler import job_manager

    job_manager.create(
        job_type="interval",          # interval, daily, once
        schedule_value="10m",         # 30s, 5m, 1h, 2d, daily:09:00
        task_type="btc_email",        # MUST match your executor route
        payload={{
            "to": "user@email.com",
            "subject": "BTC Price",
            "body": "Bitcoin: {{{{btc_price}}}}",   # dynamic content
            "fetch": ["btc_price"]                    # resolved before sending
        }}
    )

IMPORTANT: task_type in create() MUST match the elif route in execute_task().

==================================================
CRITICAL RULES
==================================================

1. KEEP execute_task function signature: def execute_task(job: dict) -> dict
2. KEEP all existing handlers (telegram, discord, email, api, trade)
3. KEEP FETCH_DATA_REGISTRY and resolve_content logic
4. Return {{"status": "success"|"failed", "message": str}} from all handlers
5. DO NOT create new files
6. DO NOT add imports that aren't available
7. Use services.api_client for ALL external API calls
8. Use {{variable}} with fetch list for dynamic content when possible

==================================================
OUTPUT
==================================================

Return the COMPLETE updated executor.py and api_client.py files.
Include the job_manager.create() call to register the job.
"""

    def _run_claude(self, prompt: str) -> dict:
        """Run Claude Code Agent using async query method."""
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(self._async_run_claude(prompt))
                return result
            finally:
                loop.close()
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _async_run_claude(self, prompt: str) -> dict:
        """Async wrapper for ClaudeCodeAgent."""
        async with ClaudeCodeAgent(str(self.project_path)) as agent:
            result = await agent.query(prompt, timeout=600)
            if result:
                return {"success": True, "result": result}
            return {"success": False, "error": "No response from Claude"}

    def _validate(self) -> Tuple[bool, str]:
        """Validate modified executor.py."""
        if not self.executor_path.exists():
            return False, "executor.py missing"

        content = self.executor_path.read_text()

        if "def execute_task" not in content:
            return False, "execute_task function missing"

        if "FETCH_DATA_REGISTRY" not in content:
            return False, "FETCH_DATA_REGISTRY missing"

        return True, "Valid"

    def _rollback(self):
        """Restore backups."""
        if self.backup_executor.exists():
            shutil.copy2(self.backup_executor, self.executor_path)
            self.backup_executor.unlink()
        if self.backup_api_client.exists():
            shutil.copy2(self.backup_api_client, self.api_client_path)
            self.backup_api_client.unlink()
        logger.info("Rolled back executor changes")
