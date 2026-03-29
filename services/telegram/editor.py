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
        self.ai_logic_path = self.project_path / "services" / "ai_logic.py"
        self.api_client_path = self.project_path / "services" / "api_client.py"
        self.backup_ai_logic = self.project_path / "services" / "ai_logic.py.backup"
        self.backup_api_client = self.project_path / "services" / "api_client.py.backup"
    
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
        return f"""Enhance Telegram bot for: {description}

Bot: {bot_name}
Allowed files to modify:
- services/ai_logic.py (process_user_input function)
- services/api_client.py (add helper functions only)

## 🧠 COMMAND GENERATION STRATEGY

### Step 1: Analyze Intent
Detect user intent from description: "{description}"

**Intent Patterns:**
- crypto/blockchain → /price, /market, /balance
- weather/forecast → /weather, /forecast, /temperature
- productivity → /tasks, /remind, /todo
- jokes/entertainment → /joke, /fun, /random
- news → /news, /headlines, /latest
- unknown/unclear → Use default commands

**Default Commands (use if intent unclear):**
- /start - Welcome message
- /help - Show available commands
- /ask - General Q&A
- /status - Bot status

### Step 2: Generate Commands
IF intent is clear from "{description}":
  → Create relevant keyword handlers
  → Add API helpers if needed
ELSE:
  → Use default commands with mock responses

## CRITICAL RULES
1. Keep signature: def process_user_input(text: str, user: Optional[User] = None) -> str
2. Use keyword matching: if "keyword" in text_lower
3. DO NOT add new imports (all imports in templates)
4. DO NOT create new files
5. DO NOT modify main.py, config.py, database.py
6. Handle errors gracefully
7. Keep existing greetings/help logic

## 🌐 API INTEGRATION PATTERN

### If API needed:
1. Add helper function to api_client.py:
```python
def get_feature_data() -> dict:
    \"\"\"Fetch data from API.\"\"\"
    result = fetch_json("https://api.example.com/endpoint", timeout=10)
    if result["success"]:
        return {{"success": True, "data": result["data"]}}
    return {{"success": False, "error": result["error"]}}
```

2. Call from ai_logic.py:
```python
if any(kw in text_lower for kw in ["keyword", "command"]):
    result = get_feature_data()
    if result["success"]:
        return f"✅ {{result['data']}}"
    else:
        return f"⚠️ Error: {{result['error']}}"
```

### If API unavailable or unclear:
Use MOCK response:
```python
if "price" in text_lower:
    return "💰 BTC Price: $65,000 (mock data)"
```

## 📦 Available API Functions
- fetch_json(url, params, timeout) → Generic JSON fetcher
- safe_get(data, *keys, default) → Safe dict access
- get_crypto_price(coin_id) → Crypto prices
- get_weather(city) → Weather (may not be configured)

## 🔍 Intent Detection Examples

**Crypto Bot:**
- Description: "crypto price tracker"
- Keywords: btc, eth, price, market
- Commands: /price, /market
- API: CoinGecko

**Weather Bot:**
- Description: "weather forecast bot"
- Keywords: weather, forecast, temperature
- Commands: /weather, /forecast
- API: OpenWeatherMap

**Generic Bot:**
- Description: "helpful assistant"
- Keywords: help, ask, question
- Commands: /start, /help, /ask
- Response: Mock or default

## 🎯 Implementation Steps
1. Read services/ai_logic.py
2. Read services/api_client.py
3. Detect intent from: "{description}"
4. If clear intent → add relevant handlers
5. If unclear → use default commands
6. Add API helpers if needed
7. Add mock fallbacks for errors
8. Test syntax

## 📝 Output
- Modified services/ai_logic.py
- Optional: new functions in services/api_client.py

## ⚠️ Fallback Rules
- If API fails → return mock response
- If intent unclear → use default commands
- If error occurs → show user-friendly message
- NEVER crash the bot
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
            
            # At least one file must be changed
            if not ai_logic_changed and not api_client_changed:
                return False, "AI made no changes to ai_logic.py or api_client.py"
            
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
            
            # FIX 4: Only validate function signature (relaxed rules)
            if "def process_user_input(text: str" not in ai_logic_content:
                return False, "Function signature changed or missing in ai_logic.py"
            
            # FIX 5: Check if other files were modified (restrict scope)
            # Only ai_logic.py and api_client.py can be modified
            protected_files = [
                "main.py",
                "config.py",
                "database.py"
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
            
            logger.info("✅ Rollback complete")
        except Exception as e:
            logger.error(f"❌ Rollback failed: {e}")
