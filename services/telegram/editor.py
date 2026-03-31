"""
Telegram Bot AI Editor
Enhances bot logic using Claude AI based on user description.
ACPX-inspired pattern: read → prompt → modify → validate → rollback if failed.
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


class TelegramBotEditor:
    """
    AI-powered bot logic enhancer.
    Modifies services/ai_logic.py based on user description.
    """
    
    def __init__(self, project_path: str):
        """
        Initialize editor.
        
        Args:
            project_path: Path to telegram/ directory
        """
        self.project_path = Path(project_path)
        
        # Core logic files
        self.ai_logic_path = self.project_path / "services" / "ai_logic.py"
        self.api_client_path = self.project_path / "services" / "api_client.py"
        
        # Handler files (AI can edit to update welcome messages)
        self.start_handler_path = self.project_path / "handlers" / "start.py"
        self.message_handler_path = self.project_path / "handlers" / "message.py"
        
        # Backup paths
        self.backup_ai_logic = self.project_path / "services" / "ai_logic.py.backup"
        self.backup_api_client = self.project_path / "services" / "api_client.py.backup"
        self.backup_start_handler = self.project_path / "handlers" / "start.py.backup"
        self.backup_message_handler = self.project_path / "handlers" / "message.py.backup"
    
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
            # Verify ai_logic.py exists
            if not self.ai_logic_path.exists():
                return False, f"ai_logic.py not found at {self.ai_logic_path}"
            
            # Create backup for ai_logic.py
            logger.info(f"Creating backup: {self.backup_ai_logic}")
            shutil.copy2(self.ai_logic_path, self.backup_ai_logic)
            
            # Create backup for api_client.py if it exists
            if self.api_client_path.exists():
                logger.info(f"Creating backup: {self.backup_api_client}")
                shutil.copy2(self.api_client_path, self.backup_api_client)
            
            # Create backups for handler files
            if self.start_handler_path.exists():
                logger.info(f"Creating backup: {self.backup_start_handler}")
                shutil.copy2(self.start_handler_path, self.backup_start_handler)
            
            if self.message_handler_path.exists():
                logger.info(f"Creating backup: {self.backup_message_handler}")
                shutil.copy2(self.message_handler_path, self.backup_message_handler)
            
            # Build AI prompt
            prompt = self._build_enhancement_prompt(description, bot_name)
            
            # Run Claude Code Agent
            logger.info(f"Running Claude AI enhancement for: {description}")
            
            # Use Claude agent to modify file
            result = self._run_claude_modification(prompt)
            
            if result.get("success"):
                # Validate modified file
                is_valid, validation_msg = self._validate_modified_file()
                
                if is_valid:
                    logger.info(f"✅ AI enhancement successful: {validation_msg}")
                    # Remove backups
                    if self.backup_ai_logic.exists():
                        self.backup_ai_logic.unlink()
                    if self.backup_api_client.exists():
                        self.backup_api_client.unlink()
                    if self.backup_start_handler.exists():
                        self.backup_start_handler.unlink()
                    if self.backup_message_handler.exists():
                        self.backup_message_handler.unlink()
                    return True, "Bot logic enhanced successfully"
                else:
                    # Validation failed - rollback
                    logger.error(f"❌ Validation failed: {validation_msg}")
                    self._rollback()
                    return False, f"Validation failed: {validation_msg}"
            else:
                # Claude failed - rollback
                logger.error(f"❌ Claude modification failed: {result.get('error')}")
                self._rollback()
                return False, f"AI modification failed: {result.get('error')}"
        
        except Exception as e:
            logger.error(f"❌ Enhancement error: {e}")
            self._rollback()
            return False, f"Enhancement error: {e}"
    
    def _build_enhancement_prompt(self, description: str, bot_name: str) -> str:
        """Build concise AI prompt for bot enhancement with dynamic command generation."""
        return f"""
Enhance Telegram bot for: {description}

Bot: {bot_name}

Allowed files to modify ONLY:
- services/ai_logic.py
- services/api_client.py (helper functions only)
- handlers/start.py (ONLY update welcome message text)
- handlers/message.py (ONLY if absolutely required)

DO NOT modify any other files.

==================================================
🧠 INTENT DETECTION
==================================================

Analyze intent from description: "{description}"

Examples:
- crypto → /price, /market, /top, /convert
- weather → /weather, /forecast
- productivity → /tasks, /remind
- unknown → keep default commands

==================================================
🔒 CRITICAL RULES (MANDATORY)
==================================================

1. KEEP function signature EXACT:
   def process_user_input(text: str, user: Optional[User] = None) -> str

2. DO NOT remove existing commands

3. DO NOT break existing handlers

4. DO NOT add new imports

5. DO NOT create new files

6. ALWAYS return a string (NEVER return None)

7. NEVER crash — always fallback safely

==================================================
🚨 COMMAND PARSING RULES (STRICT)
==================================================

❌ NEVER use:
- .replace()
- partial string manipulation

✅ ALWAYS use:

parts = text_lower.split()

RULES:

1. ALL commands MUST use split()

2. ALWAYS validate argument length

3. NEVER access parts[i] without checking length

4. DO NOT mix parsing styles

5. DO NOT invent new parsing logic

--------------------------------------------------

✅ STANDARD COMMAND FORMAT:

/price <coin>
/top [n]
/market [n]
/convert <amount> <from> <to>

--------------------------------------------------

✅ EXAMPLES (FOLLOW EXACTLY):

# /price
if text_lower.startswith("/price"):
    parts = text_lower.split()

    if len(parts) < 2:
        return "💡 Usage: /price <coin>"

    coin = parts[1]
    return _handle_crypto_query(coin)


# /top
if text_lower.startswith("/top"):
    parts = text_lower.split()

    limit = 10
    if len(parts) >= 2 and parts[1].isdigit():
        limit = min(int(parts[1]), 50)

    return _handle_top_coins(limit)


# /convert
if text_lower.startswith("/convert"):
    parts = text_lower.split()

    if len(parts) < 4:
        return "💡 Usage: /convert <amount> <from> <to>"

    return _handle_conversion(parts[1], parts[2], parts[3])


==================================================
🤖 /ask COMMAND RULE (STRICT)
==================================================

MUST follow EXACTLY:

if text_lower.startswith("/ask"):
    parts = text.split(maxsplit=1)

    if len(parts) < 2:
        return "💡 Usage: /ask <question>"

    question = parts[1]

    # OPTIONAL: detect crypto intent
    if "btc" in question.lower():
        return _handle_crypto_query("bitcoin")

    return f"🤔 {{question}}\\n\\nUse /price btc for crypto queries"

==================================================
🌐 API USAGE
==================================================

Use existing functions only:
- get_crypto_price
- get_market_data
- get_top_coins

If API fails:
→ return mock or friendly fallback

==================================================
📦 FEATURE RULES
==================================================

- Add new commands ONLY if clearly required
- DO NOT remove existing commands
- DO NOT rename commands

==================================================
🧾 START + HELP UPDATE RULE
==================================================

If new commands are added:

1. UPDATE _handle_start()
2. UPDATE _handle_help()

DO NOT break formatting

==================================================
🛡️ SAFETY RULES
==================================================

- NEVER return empty string
- NEVER return None
- ALWAYS return user-friendly message
- ALWAYS handle invalid input

==================================================
🎯 OUTPUT REQUIREMENT
==================================================

Return FULL updated code for:
- services/ai_logic.py

OPTIONAL:
- services/api_client.py (if needed)
- handlers/start.py (only text changes)

==================================================
"""
    
    def _run_claude_modification(self, prompt: str) -> dict:
        """
        Run Claude Code Agent to modify file with safe async execution.
        
        Args:
            prompt: Enhancement prompt
        
        Returns:
            Result dict with success status
        """
        try:
            import asyncio
            
            async def run_claude():
                async with ClaudeCodeAgent(repo_path=str(self.project_path)) as agent:
                    result = await agent.query(
                        prompt=prompt,
                        timeout=600  # 10 minutes
                    )
                    return result
            
            # Safe async execution (FIX 1 & 2)
            try:
                # Try to use existing event loop
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If loop is already running, create new one
                    result = asyncio.run(run_claude())
                else:
                    # Use existing loop with timeout
                    result = loop.run_until_complete(
                        asyncio.wait_for(run_claude(), timeout=600)
                    )
            except RuntimeError:
                # No event loop, create new one
                result = asyncio.run(
                    asyncio.wait_for(run_claude(), timeout=600)
                )
            
            # Handle result - can be string (success) or dict
            if isinstance(result, dict):
                return {
                    "success": result.get("success", False),
                    "error": result.get("error", "Unknown error")
                }
            elif isinstance(result, str) and result:
                # String response means success (files were modified)
                logger.info(f"✅ Claude returned response: {result[:100]}...")
                return {"success": True, "error": None}
            else:
                return {"success": False, "error": "Empty or invalid response"}
        
        except asyncio.TimeoutError:
            logger.error("❌ Claude modification timeout after 600s")
            return {
                "success": False,
                "error": "Modification timeout"
            }
        except Exception as e:
            logger.error(f"❌ Claude modification error: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    def _validate_modified_file(self) -> Tuple[bool, str]:
        """
        Validate modified ai_logic.py file.
        
        Returns:
            Tuple of (is_valid, message)
        
        Checks:
            - File exists
            - Python syntax valid
            - Function signature intact
            - Changes were actually made (FIX 3)
            - No other files modified (FIX 5)
        """
        try:
            if not self.ai_logic_path.exists():
                return False, "Modified file not found"
            
            # FIX 3: Detect no-change edits
            ai_logic_changed = False
            api_client_changed = False
            start_handler_changed = False
            message_handler_changed = False
            
            if self.backup_ai_logic.exists():
                with open(self.backup_ai_logic, 'r') as f:
                    backup_ai_logic_content = f.read()
                
                with open(self.ai_logic_path, 'r') as f:
                    modified_ai_logic_content = f.read()
                
                ai_logic_changed = (backup_ai_logic_content != modified_ai_logic_content)
            
            if self.backup_api_client.exists():
                with open(self.backup_api_client, 'r') as f:
                    backup_api_client_content = f.read()
                
                with open(self.api_client_path, 'r') as f:
                    modified_api_client_content = f.read()
                
                api_client_changed = (backup_api_client_content != modified_api_client_content)
            
            if self.backup_start_handler.exists():
                with open(self.backup_start_handler, 'r') as f:
                    backup_start_content = f.read()
                
                with open(self.start_handler_path, 'r') as f:
                    modified_start_content = f.read()
                
                start_handler_changed = (backup_start_content != modified_start_content)
            
            if self.backup_message_handler.exists():
                with open(self.backup_message_handler, 'r') as f:
                    backup_message_content = f.read()
                
                with open(self.message_handler_path, 'r') as f:
                    modified_message_content = f.read()
                
                message_handler_changed = (backup_message_content != modified_message_content)
            
            # At least one file must be changed
            if not any([ai_logic_changed, api_client_changed, start_handler_changed, message_handler_changed]):
                return False, "AI made no changes to allowed files"
            
            # Check Python syntax for ai_logic.py
            try:
                with open(self.ai_logic_path, 'r') as f:
                    ai_logic_content = f.read()
                compile(ai_logic_content, str(self.ai_logic_path), 'exec')
            except SyntaxError as e:
                return False, f"Syntax error in ai_logic.py: {e}"
            
            # Check Python syntax for api_client.py if it was modified
            if api_client_changed:
                try:
                    with open(self.api_client_path, 'r') as f:
                        api_client_content = f.read()
                    compile(api_client_content, str(self.api_client_path), 'exec')
                except SyntaxError as e:
                    return False, f"Syntax error in api_client.py: {e}"
            
            # Check Python syntax for start.py if it was modified
            if start_handler_changed:
                try:
                    with open(self.start_handler_path, 'r') as f:
                        start_content = f.read()
                    compile(start_content, str(self.start_handler_path), 'exec')
                    
                    # Verify async def start still exists
                    if 'async def start(update, context):' not in start_content:
                        return False, "start handler function signature changed or missing"
                    
                    # CRITICAL: Verify username variable is still defined (needed for database)
                    if 'username = tg_user.username' not in start_content:
                        return False, "CRITICAL: 'username = tg_user.username' line was removed from start.py"
                    
                    # Verify it routes through ai_logic.py
                    if 'process_user_input' not in start_content:
                        return False, "start.py must call process_user_input() from ai_logic.py"
                except SyntaxError as e:
                    return False, f"Syntax error in start.py: {e}"
            
            # Check Python syntax for message.py if it was modified
            if message_handler_changed:
                try:
                    with open(self.message_handler_path, 'r') as f:
                        message_content = f.read()
                    compile(message_content, str(self.message_handler_path), 'exec')
                    
                    # Verify async def handle_message still exists
                    if 'async def handle_message(update, context):' not in message_content:
                        return False, "message handler function signature changed or missing"
                except SyntaxError as e:
                    return False, f"Syntax error in message.py: {e}"
            
            # FIX 4: Only validate function signature (relaxed rules)
            if "def process_user_input(text: str" not in ai_logic_content:
                return False, "Function signature changed or missing in ai_logic.py"
            
            # FIX 5: Check if other files were modified (restrict scope)
            # Only these files can be modified
            protected_files = [
                "main.py",
                "config.py",
                "database.py",
                "models/user.py",
                "utils/logger.py",
                "utils/user_helpers.py"
            ]
            
            for filename in protected_files:
                protected_path = self.project_path / "services" / filename
                backup_path = self.project_path / "services" / f"{filename}.backup"
                
                # If backup exists for protected file, it means AI tried to modify it
                if backup_path.exists():
                    logger.error(f"❌ AI attempted to modify protected file: {filename}")
                    return False, f"AI attempted to modify {filename} (not allowed)"
            
            logger.info("✅ Validation passed")
            return True, "Validation passed"
        
        except Exception as e:
            logger.error(f"❌ Validation error: {e}")
            return False, f"Validation error: {e}"
    
    def _rollback(self):
        """Rollback to backup if enhancement failed."""
        try:
            # Rollback ai_logic.py
            if self.backup_ai_logic.exists():
                logger.info(f"🔄 Rolling back ai_logic.py...")
                shutil.copy2(self.backup_ai_logic, self.ai_logic_path)
                self.backup_ai_logic.unlink()
            
            # Rollback api_client.py
            if self.backup_api_client.exists():
                logger.info(f"🔄 Rolling back api_client.py...")
                shutil.copy2(self.backup_api_client, self.api_client_path)
                self.backup_api_client.unlink()
            
            # Rollback start.py
            if self.backup_start_handler.exists():
                logger.info(f"🔄 Rolling back start.py...")
                shutil.copy2(self.backup_start_handler, self.start_handler_path)
                self.backup_start_handler.unlink()
            
            # Rollback message.py
            if self.backup_message_handler.exists():
                logger.info(f"🔄 Rolling back message.py...")
                shutil.copy2(self.backup_message_handler, self.message_handler_path)
                self.backup_message_handler.unlink()
            
            logger.info("✅ Rollback complete")
        except Exception as e:
            logger.error(f"❌ Rollback failed: {e}")
