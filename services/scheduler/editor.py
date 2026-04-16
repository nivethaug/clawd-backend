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

    def __init__(self, project_path: str, project_id: int = None, backend_url: str = None):
        self.project_path = Path(project_path)
        self.project_id = project_id
        self.backend_url = backend_url or "http://localhost:8002"
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
        # Build the job creation API instruction
        jobs_api_url = f"{self.backend_url}/api/scheduler/projects/{self.project_id}/jobs"

        return f"""
Enhance the scheduler executor for: {description}

Project: {project_name} (ID: {self.project_id})

Allowed files to modify:
- scheduler/executor.py (add task handlers + routes) — PRIMARY file to modify
- services/api_client.py — ONLY if you need a NEW API function that doesn't exist yet
- services/web_scraper.py — ONLY to extend the existing scraper when website data is required

DO NOT modify any other files.

IMPORTANT: api_client.py already has these functions:
- get_crypto_price(coin_id, currency) — use it, don't recreate it
- get_weather(latitude, longitude)
- get_news(query, page)
- fetch_json(url, params) — generic JSON fetcher
Only add to api_client.py if you need an API NOT listed above.

==================================================
WEBSITE DATA (MANDATORY)
==================================================

If the user request requires fetching website data (scraping):
1. USE the existing CDP scraper in services/web_scraper.py (do NOT create a new scraper system).
2. Add a helper wrapper in services/api_client.py that builds a ScrapeConfig and calls scrape_url().
3. If site-specific steps are needed, subclass WebScraper in services/web_scraper.py and register it.
4. Always include the target URL in ScrapeConfig.url and keep selectors specific.

Add a utility helper for each website-based request:
- Name it for the intent, e.g., scrape_site_headlines(), scrape_product_prices().
- Keep it pure: accept url + optional params, return {success, data, errors}.

==================================================
INTENT DETECTION & API SELECTION
==================================================

ANALYZE user description: "{description}"

STEP 1: Read .env to find which channels are configured:
- TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID → Telegram available
- DISCORD_WEBHOOK_URL → Discord available
- SMTP_HOST + EMAIL_TO → Email available
- API_ENDPOINT → API available

STEP 2: Determine target channels from description:
- "send to telegram" → Telegram only
- "send to discord" → Discord only
- "send to email" → Email only
- "send to telegram and email" → BOTH Telegram + Email
- "send to all channels" → ALL configured channels
- If description doesn't specify a channel → send to ALL configured channels

STEP 3: CHANNEL FALLBACK RULES:
- If description requests a channel that is NOT configured in .env:
  → Use available channels instead, do NOT silently skip
  → Include a note in the message: "(Discord not configured, sent via Telegram)"
  → If NO requested channels are configured, fall back to ALL configured channels
- Example: "send to discord" but only Telegram is configured
  → Send via Telegram with note: "(Discord not configured)"

STEP 3: Build your handler to send to ALL target channels.
The executor already has these sender functions you can call:
- _send_telegram({{"text": msg, "chat_id": "..."}})
- _send_discord({{"content": msg}})
- _send_email({{"to": "...", "subject": "...", "body": msg}})
- _call_api({{"url": "...", "body": {{}}}})

MULTI-CHANNEL HANDLER PATTERN:
    def _btc_alert(payload: dict) -> Tuple[str, str]:
        price = ...  # fetch data

        results = []
        # Send to each configured channel
        if TELEGRAM_BOT_TOKEN:
            s, m = _send_telegram({{"text": f"BTC: {{price}}"}})
            results.append(("telegram", s))
        if DISCORD_WEBHOOK_URL:
            s, m = _send_discord({{"content": f"BTC: {{price}}"}})
            results.append(("discord", s))
        if EMAIL_TO:
            s, m = _send_email({{"subject": "BTC", "body": f"BTC: {{price}}"}})
            results.append(("email", s))

        failed = [r for r in results if r[1] == "failed"]
        if failed:
            return ("failed", f"Failed: {{failed}}")
        return ("success", f"Sent to {{len(results)}} channels")

During initial creation, you have FULL AUTONOMY to:
1. Read .env to detect configured channels
2. Select appropriate public APIs from api_client
3. Add task handlers to scheduler/executor.py
4. Register new routes in execute_task()
5. Add FETCH_DATA_REGISTRY entries for dynamic content
6. Create the scheduled job via the REST API (see below)

EXAMPLES:
- "BTC price to telegram every 10min" → _btc_alert() sends to Telegram only
- "BTC price to discord every 10min" → _btc_alert() sends to Discord only
- "BTC price to telegram and email" → _btc_alert() sends to BOTH Telegram + Email
- "weather alert every hour" → sends to ALL configured channels

==================================================
EXECUTOR.PY STRUCTURE
==================================================

The executor has TWO extension points:

1. FETCH_DATA_REGISTRY - for dynamic {{{{variable}}}} resolution:
   FETCH_DATA_REGISTRY["btc_price"] = lambda: _fetch_crypto("bitcoin")

2. execute_task() routing - for task_type handlers:
   elif task_type == "btc_email":
       status, message = _btc_email(payload)

Add your handlers BELOW existing ones. Keep existing handlers intact.

==================================================
MESSAGE FORMATTING RULES
==================================================

When sending messages via Telegram or Discord:
- Use plain text ONLY (no parse_mode)
- Do NOT use $ before {{{{variable}}}} — the variable already includes formatting
  Example: "BTC: {{btc_price}}" → "BTC: $84,234.00" (correct)
  NOT: "BTC: ${{btc_price}}" → "BTC: $$84,234.00" (wrong — double $)
- Keep messages concise and scannable
- Use simple ASCII art or unicode symbols, NOT emoji codes
- Good template example:
    "BTC Price Update\n\nPrice: {{btc_price}}\nChange 24h: {{btc_change}}\n\nUpdated: auto"
- BAD template example:
    "💰 BTC Price: ${{price}}" (double $, wrong variable name)

==================================================
JOB CREATION - REQUIRED FINAL STEP
==================================================

After modifying files, you MUST create the job by EXECUTING this curl command.
Do NOT just print it — actually RUN it using Bash:

    curl -s -X POST {jobs_api_url} \\
      -H "Content-Type: application/json" \\
      -d '{{"
        "job_type": "interval",
        "schedule_value": "5m",
        "task_type": "YOUR_TASK_TYPE",
        "payload": {{{{
            "text": "BTC Price: {{{{btc_price}}}}",
            "fetch": ["btc_price"]
        }}}}
      }}'

The backend API is running and ready to accept this request.
Execute the curl command NOW — this is step 6 of your task, not optional.

Variable names in {{{{}}}} MUST match keys in FETCH_DATA_REGISTRY exactly.
Current registry keys: btc_price, eth_price, weather, news.

The "fetch" array is REQUIRED — without it, {{{{variable}}}} placeholders
will NOT be resolved and will be sent as literal text.

Rules:
- task_type MUST match the elif route you added in execute_task()
- job_type: "interval" (recurring), "daily" (once per day at time), or "once"
- schedule_value: "30s", "5m", "1h", "2d", or "daily:09:00"
- Derive schedule from the user description (e.g., "every 10min" → "10m")
- The "fetch" array is REQUIRED when using {{{{variable}}}} placeholders

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
9. YOU MUST create the job via curl after modifying files — this is not optional
10. AFTER editing ANY .py file, run: python -c "import py_compile; py_compile.compile('FILE_PATH', doraise=True)"
    This catches syntax errors BEFORE they break the scheduler.
    If compilation fails, FIX the error immediately — do not leave broken files.
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
        """Validate modified executor.py and api_client.py."""
        if not self.executor_path.exists():
            return False, "executor.py missing"

        # Syntax check both files
        for path in [self.executor_path, self.api_client_path]:
            if not path.exists():
                continue
            try:
                compile(path.read_text(), str(path), 'exec')
            except SyntaxError as e:
                return False, f"Syntax error in {path.name}: {e.msg} (line {e.lineno})"

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
