"""
Discord Bot AI Editor
Enhances bot logic using Claude AI based on user description.
ACPX-inspired pattern: read -> prompt -> modify -> validate -> rollback if failed.
"""
import os
import shutil
from pathlib import Path
from typing import Tuple
from utils.logger import logger

# Try to import Claude Code Agent
try:
    from claude_code_agent import ClaudeCodeAgent
    CLAUDE_AVAILABLE = True
except ImportError:
    CLAUDE_AVAILABLE = False
    logger.warning("ClaudeCodeAgent not available - AI enhancement disabled")


class DiscordBotEditor:
    """
    AI-powered Discord bot logic enhancer.
    Modifies services/ai_logic.py based on user description.
    """

    def __init__(self, project_path: str):
        """
        Initialize editor.

        Args:
            project_path: Path to discord/ directory
        """
        self.project_path = Path(project_path)

        # Core logic files
        self.ai_logic_path = self.project_path / "services" / "ai_logic.py"
        self.api_client_path = self.project_path / "services" / "api_client.py"

        # Command files (AI can edit to update welcome messages)
        self.start_cmd_path = self.project_path / "commands" / "start.py"
        self.ask_cmd_path = self.project_path / "commands" / "ask.py"

        # Backup paths
        self.backup_ai_logic = self.project_path / "services" / "ai_logic.py.backup"
        self.backup_api_client = self.project_path / "services" / "api_client.py.backup"
        self.backup_start_cmd = self.project_path / "commands" / "start.py.backup"
        self.backup_ask_cmd = self.project_path / "commands" / "ask.py.backup"

    def enhance_bot_logic(
        self,
        description: str,
        bot_name: str
    ) -> Tuple[bool, str]:
        """
        Enhance bot logic using Claude AI.

        Args:
            description: User's bot description (e.g., "crypto price tracker")
            bot_name: Bot name for context

        Returns:
            Tuple of (success, message)

        Workflow:
            1. Create backup
            2. Read current ai_logic.py
            3. Build AI prompt
            4. Run Claude to modify file
            5. Validate modified file
            6. Rollback on failure
        """
        if not CLAUDE_AVAILABLE:
            logger.warning("Claude agent not available - skipping AI enhancement")
            return True, "AI enhancement skipped (Claude not available)"

        try:
            if not self.ai_logic_path.exists():
                return False, f"ai_logic.py not found at {self.ai_logic_path}"

            # Create backups
            logger.info(f"Creating backup: {self.backup_ai_logic}")
            shutil.copy2(self.ai_logic_path, self.backup_ai_logic)

            if self.api_client_path.exists():
                logger.info(f"Creating backup: {self.backup_api_client}")
                shutil.copy2(self.api_client_path, self.backup_api_client)

            if self.start_cmd_path.exists():
                logger.info(f"Creating backup: {self.backup_start_cmd}")
                shutil.copy2(self.start_cmd_path, self.backup_start_cmd)

            if self.ask_cmd_path.exists():
                logger.info(f"Creating backup: {self.backup_ask_cmd}")
                shutil.copy2(self.ask_cmd_path, self.backup_ask_cmd)

            # Build AI prompt
            prompt = self._build_enhancement_prompt(description, bot_name)

            # Run Claude Code Agent
            logger.info(f"Running Claude AI enhancement for: {description}")
            result = self._run_claude_modification(prompt)

            if result.get("success"):
                is_valid, validation_msg = self._validate_modified_file()

                if is_valid:
                    logger.info(f"AI enhancement successful: {validation_msg}")
                    for backup in [self.backup_ai_logic, self.backup_api_client,
                                   self.backup_start_cmd, self.backup_ask_cmd]:
                        if backup.exists():
                            backup.unlink()
                    return True, "Bot logic enhanced successfully"
                else:
                    logger.error(f"Validation failed: {validation_msg}")
                    self._rollback()
                    return False, f"Validation failed: {validation_msg}"
            else:
                logger.error(f"Claude modification failed: {result.get('error')}")
                self._rollback()
                return False, f"AI modification failed: {result.get('error')}"

        except Exception as e:
            logger.error(f"Enhancement error: {e}")
            self._rollback()
            return False, f"Enhancement error: {e}"

    def _build_enhancement_prompt(self, description: str, bot_name: str) -> str:
        """Build AI prompt for Discord bot enhancement."""
        return f"""
Enhance Discord bot for: {description}

Bot: {bot_name}

Allowed files to modify ONLY:
- services/ai_logic.py
- services/api_client.py (helper functions only)
- commands/start.py (ONLY update welcome message text)
- commands/ask.py (ONLY if absolutely required)

DO NOT modify any other files.

==================================================
INTENT DETECTION & API SELECTION
==================================================

ANALYZE user description: "{description}"

During initial bot creation, LLM has FULL AUTONOMY to:
1. Match description to BEST category from /llm/categories/index.json
2. Select appropriate APIs from that category
3. Generate commands to use those APIs
4. NO USER INTERACTION NEEDED - decide everything autonomously

EXAMPLES:
- "weather tracker bot" -> weather category, use Open-Meteo API
- "crypto prices" -> crypto_finance category, use CoinGecko API
- "news aggregator" -> news category, use Hacker News API
- "joke bot" -> entertainment category, use JokeAPI

NOTE: User provides title + description - AI MUST decide APIs autonomously

--------------------------------------------------
CRITICAL RULES (MANDATORY)
==================================================

1. KEEP function signature EXACT:
   def process_user_input(text: str) -> str

2. DO NOT remove existing commands

3. DO NOT break existing command handlers

4. DO NOT add new imports

5. DO NOT create new files

6. ALWAYS return a string (NEVER return None)

7. NEVER crash - always fallback safely

==================================================
COMMAND PARSING RULES (STRICT)
==================================================

ALWAYS use:

parts = text_lower.split()

RULES:
1. ALL commands MUST use split()
2. ALWAYS validate argument length
3. NEVER access parts[i] without checking length
4. DO NOT mix parsing styles

STANDARD COMMAND FORMAT (Discord uses ! prefix):

!price <coin>
!top [n]
!market [n]
!convert <amount> <from> <to>

EXAMPLES (FOLLOW EXACTLY):

# !price
if text_lower.startswith("!price"):
    parts = text_lower.split()

    if len(parts) < 2:
        return "Usage: !price <coin>"

    coin = parts[1]
    return _handle_crypto_query(coin)


# !top
if text_lower.startswith("!top"):
    parts = text_lower.split()

    limit = 10
    if len(parts) >= 2 and parts[1].isdigit():
        limit = min(int(parts[1]), 50)

    return _handle_top_coins(limit)


# !ask
if text_lower.startswith("!ask"):
    parts = text.split(maxsplit=1)

    if len(parts) < 2:
        return "Usage: !ask <question>"

    question = parts[1]
    return f"{{question}}"

==================================================
API USAGE
==================================================

Use public APIs when appropriate:
- Call direct_url from matched category endpoint
- Handle errors with friendly messages
- Always fallback safely

If API fails:
-> return mock or friendly fallback

==================================================
SAFETY RULES
==================================================

- NEVER return empty string
- NEVER return None
- ALWAYS return user-friendly message
- ALWAYS handle invalid input

==================================================
OUTPUT REQUIREMENT
==================================================

Return FULL updated code for:
- services/ai_logic.py

REQUIRED (when adding new APIs):
- services/api_client.py (add new helper functions for any APIs you use)

OPTIONAL:
- commands/start.py (only text changes for welcome message)

==================================================
"""

    def _run_claude_modification(self, prompt: str) -> dict:
        """Run Claude Code Agent to modify file."""
        try:
            import asyncio

            async def run_claude():
                async with ClaudeCodeAgent(repo_path=str(self.project_path)) as agent:
                    result = await agent.query(
                        prompt=prompt,
                        timeout=600
                    )
                    return result

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    result = asyncio.run(run_claude())
                else:
                    result = loop.run_until_complete(
                        asyncio.wait_for(run_claude(), timeout=600)
                    )
            except RuntimeError:
                result = asyncio.run(
                    asyncio.wait_for(run_claude(), timeout=600)
                )

            if isinstance(result, dict):
                return {
                    "success": result.get("success", False),
                    "error": result.get("error", "Unknown error")
                }
            elif isinstance(result, str) and result:
                logger.info(f"Claude returned response: {result[:100]}...")
                return {"success": True, "error": None}
            else:
                return {"success": False, "error": "Empty or invalid response"}

        except asyncio.TimeoutError:
            logger.error("Claude modification timeout after 600s")
            return {"success": False, "error": "Modification timeout"}
        except Exception as e:
            logger.error(f"Claude modification error: {e}")
            return {"success": False, "error": str(e)}

    def _validate_modified_file(self) -> Tuple[bool, str]:
        """Validate modified files."""
        try:
            if not self.ai_logic_path.exists():
                return False, "Modified file not found"

            # Detect changes
            ai_logic_changed = False
            api_client_changed = False
            start_changed = False
            ask_changed = False

            if self.backup_ai_logic.exists():
                with open(self.backup_ai_logic, 'r') as f:
                    backup_content = f.read()
                with open(self.ai_logic_path, 'r') as f:
                    modified_content = f.read()
                ai_logic_changed = (backup_content != modified_content)

            if self.backup_api_client.exists() and self.api_client_path.exists():
                with open(self.backup_api_client, 'r') as f:
                    backup_content = f.read()
                with open(self.api_client_path, 'r') as f:
                    modified_content = f.read()
                api_client_changed = (backup_content != modified_content)

            if self.backup_start_cmd.exists() and self.start_cmd_path.exists():
                with open(self.backup_start_cmd, 'r') as f:
                    backup_content = f.read()
                with open(self.start_cmd_path, 'r') as f:
                    modified_content = f.read()
                start_changed = (backup_content != modified_content)

            if self.backup_ask_cmd.exists() and self.ask_cmd_path.exists():
                with open(self.backup_ask_cmd, 'r') as f:
                    backup_content = f.read()
                with open(self.ask_cmd_path, 'r') as f:
                    modified_content = f.read()
                ask_changed = (backup_content != modified_content)

            if not any([ai_logic_changed, api_client_changed, start_changed, ask_changed]):
                return False, "AI made no changes to allowed files"

            # Check Python syntax for ai_logic.py
            with open(self.ai_logic_path, 'r') as f:
                ai_logic_content = f.read()
            try:
                compile(ai_logic_content, str(self.ai_logic_path), 'exec')
            except SyntaxError as e:
                return False, f"Syntax error in ai_logic.py: {e}"

            # Check api_client.py if modified
            if api_client_changed and self.api_client_path.exists():
                with open(self.api_client_path, 'r') as f:
                    api_content = f.read()
                try:
                    compile(api_content, str(self.api_client_path), 'exec')
                except SyntaxError as e:
                    return False, f"Syntax error in api_client.py: {e}"

            # Check start.py if modified
            if start_changed and self.start_cmd_path.exists():
                with open(self.start_cmd_path, 'r') as f:
                    start_content = f.read()
                try:
                    compile(start_content, str(self.start_cmd_path), 'exec')
                    if 'async def start(ctx):' not in start_content:
                        return False, "start command function signature changed or missing"
                except SyntaxError as e:
                    return False, f"Syntax error in start.py: {e}"

            # Validate function signature in ai_logic.py
            if "def process_user_input(text: str" not in ai_logic_content:
                return False, "Function signature changed or missing in ai_logic.py"

            # Check protected files were not modified
            protected_files = [
                "main.py",
                "config.py",
                "core/database.py",
                "models/user.py",
                "utils/logger.py"
            ]

            for filename in protected_files:
                filepath = self.project_path / filename
                if not filepath.exists():
                    # Try in subdirectories
                    for subdir in ["core", "models", "utils"]:
                        filepath = self.project_path / subdir / filename
                        if filepath.exists():
                            break
                backup_path = Path(str(filepath) + ".backup")
                if backup_path.exists():
                    logger.error(f"AI attempted to modify protected file: {filename}")
                    return False, f"AI attempted to modify {filename} (not allowed)"

            logger.info("Validation passed")
            return True, "Validation passed"

        except Exception as e:
            logger.error(f"Validation error: {e}")
            return False, f"Validation error: {e}"

    def _rollback(self):
        """Rollback to backup if enhancement failed."""
        try:
            if self.backup_ai_logic.exists():
                logger.info("Rolling back ai_logic.py...")
                shutil.copy2(self.backup_ai_logic, self.ai_logic_path)
                self.backup_ai_logic.unlink()

            if self.backup_api_client.exists():
                logger.info("Rolling back api_client.py...")
                shutil.copy2(self.backup_api_client, self.api_client_path)
                self.backup_api_client.unlink()

            if self.backup_start_cmd.exists():
                logger.info("Rolling back start.py...")
                shutil.copy2(self.backup_start_cmd, self.start_cmd_path)
                self.backup_start_cmd.unlink()

            if self.backup_ask_cmd.exists():
                logger.info("Rolling back ask.py...")
                shutil.copy2(self.backup_ask_cmd, self.ask_cmd_path)
                self.backup_ask_cmd.unlink()

            logger.info("Rollback complete")
        except Exception as e:
            logger.error(f"Rollback failed: {e}")
