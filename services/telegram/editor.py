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
        self.backup_path = self.project_path / "services" / "ai_logic.py.backup"
    
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
            
            # Create backup
            logger.info(f"Creating backup: {self.backup_path}")
            shutil.copy2(self.ai_logic_path, self.backup_path)
            
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
                    # Remove backup
                    if self.backup_path.exists():
                        self.backup_path.unlink()
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
        """
        Build AI prompt for bot enhancement.
        
        Args:
            description: Bot description
            bot_name: Bot name
        
        Returns:
            Prompt string
        """
        # Check if user mentioned specific APIs
        api_keywords = ["api", "API", "endpoint", "service"]
        has_api_mention = any(keyword in description for keyword in api_keywords)
        
        prompt = f"""# Telegram Bot Logic Enhancement

You are enhancing the AI logic for a Telegram bot.

## Bot Information
- Name: {bot_name}
- Description: {description}

## Your Task
Modify the `process_user_input()` function in `services/ai_logic.py` to match the bot's description.

## API Integration Strategy

### Step 1: Check Existing APIs
First, read `services/api_client.py` to see what API functions already exist.

### Step 2: Use Public APIs (Preferred)
**PREFER PUBLIC/FREE APIs for initial implementation:**
- CoinGecko API (crypto prices): `https://api.coingecko.com/api/v3`
- OpenWeatherMap API (weather): `https://api.openweathermap.org/data/2.5`
- JSONPlaceholder API (test data): `https://jsonplaceholder.typicode.com`
- RestCountries API: `https://restcountries.com/v3.1`
- NewsAPI: `https://newsapi.org/v2`
- ExchangeRate-API: `https://api.exchangerate-api.com/v4`
- Wikipedia API: `https://en.wikipedia.org/api/rest_v1`
- JokeAPI: `https://v2.jokeapi.dev/joke`

### Step 3: User-Specified APIs
{'⚠️ USER MENTIONED API - Check if they specified which API to use' if has_api_mention else ''}
{'If the description contains specific API names or endpoints, use those instead of defaults.' if has_api_mention else ''}

## Implementation Pattern

### Adding New API Integration:
1. Check if function exists in `services/api_client.py`
2. If not, add new function to `api_client.py`:
   ```python
   def get_{feature}_data(params) -> dict:
       try:
           response = requests.get("https://api.example.com/endpoint", timeout=10)
           response.raise_for_status()
           return {"success": True, "data": response.json()}
       except Exception as e:
           return {"success": False, "error": str(e)}
   ```
3. Import in `ai_logic.py`: `from services.api_client import get_{feature}_data`
4. Use in `process_user_input()` with error handling

## Constraints
- ONLY modify the `process_user_input()` function (and add imports if needed)
- CAN add new functions to `services/api_client.py` if needed
- DO NOT change function signature: `def process_user_input(text: str, user: Optional[User] = None) -> str`
- Use simple keyword-based logic (if "keyword" in text_lower)
- ALWAYS handle API errors gracefully (show user-friendly message)
- Add fallback response for unrecognized input
- Keep responses concise and user-friendly

## Examples

### Example 1: Crypto Price Tracker (using CoinGecko)
Input: "crypto price tracker bot"

In `services/api_client.py` (if not exists):
```python
def get_crypto_price(coin_id: str = "bitcoin") -> dict:
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price"
        params = {{"ids": coin_id, "vs_currencies": "usd"}}
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if coin_id in data:
            return {{"success": True, "price": data[coin_id]["usd"]}}
        return {{"success": False, "error": "Coin not found"}}
    except Exception as e:
        return {{"success": False, "error": str(e)}}
```

In `services/ai_logic.py`:
```python
from services.api_client import get_crypto_price

def process_user_input(text: str, user: Optional[User] = None) -> str:
    text_lower = text.lower().strip()
    
    # Crypto price queries
    if any(kw in text_lower for kw in ["btc", "bitcoin"]):
        result = get_crypto_price("bitcoin")
        if result["success"]:
            return f"💰 Bitcoin: ${{result['price']:,.2f}}"
        return f"⚠️ Error: {{result['error']}}"
    
    # ... existing logic ...
```

### Example 2: Weather Bot (using OpenWeatherMap)
Input: "weather bot for cities"

In `services/api_client.py`:
```python
def get_weather(city: str) -> dict:
    try:
        # Note: Requires API key from openweathermap.org
        api_key = os.getenv("OPENWEATHER_API_KEY", "demo")
        url = f"https://api.openweathermap.org/data/2.5/weather"
        params = {{"q": city, "appid": api_key, "units": "metric"}}
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        return {{
            "success": True,
            "temp": data["main"]["temp"],
            "description": data["weather"][0]["description"]
        }}
    except Exception as e:
        return {{"success": False, "error": str(e)}}
```

### Example 3: Joke Bot (using JokeAPI - no auth needed)
Input: "tell me jokes bot"

In `services/api_client.py`:
```python
def get_random_joke() -> dict:
    try:
        url = "https://v2.jokeapi.dev/joke/Programming,Misc?safe-mode"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data["type"] == "single":
            return {{"success": True, "joke": data["joke"]}}
        else:
            return {{"success": True, "joke": f"{{data['setup']}} ... {{data['delivery']}}"}}
    except Exception as e:
        return {{"success": False, "error": str(e)}}
```

### Example 4: User Specifies API
Input: "bot that uses the Spotify API to search songs"

Note: User specified "Spotify API" - use that instead of generic APIs.
Check Spotify API documentation and implement accordingly.

## Execution Steps
1. Read current `services/ai_logic.py`
2. Read `services/api_client.py` to check existing functions
3. Check if user mentioned specific APIs in: "{description}"
4. Identify what features need to be added based on: "{description}"
5. Add new API functions to `api_client.py` if needed (prefer public APIs)
6. Modify `process_user_input()` in `ai_logic.py` with new logic
7. Keep existing logic intact (greetings, help, etc.)
8. Add error handling for API calls
9. Add fallback response

## Required Output
- Modified `services/ai_logic.py` with enhanced logic
- Optional: New functions in `services/api_client.py` if needed
- Syntax must be valid Python
- All imports must be correct
- Function signature must not change
- API calls must have error handling

Begin by:
1. Reading `services/ai_logic.py`
2. Reading `services/api_client.py`
3. Checking if user mentioned specific APIs
4. Making your modifications
"""
        return prompt
    
    def _run_claude_modification(self, prompt: str) -> dict:
        """
        Run Claude Code Agent to modify file.
        
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
                        timeout=180  # 3 minutes
                    )
                    return result
            
            # Run async
            result = asyncio.run(run_claude())
            
            return {
                "success": result.get("success", False),
                "error": result.get("error", "Unknown error")
            }
        
        except Exception as e:
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
            - Imports intact
        """
        try:
            if not self.ai_logic_path.exists():
                return False, "Modified file not found"
            
            # Read content
            with open(self.ai_logic_path, 'r') as f:
                content = f.read()
            
            # Check Python syntax
            try:
                compile(content, str(self.ai_logic_path), 'exec')
            except SyntaxError as e:
                return False, f"Syntax error: {e}"
            
            # Check function signature exists
            if "def process_user_input(text: str" not in content:
                return False, "Function signature changed or missing"
            
            # Check imports intact
            required_imports = [
                "from services.api_client import",
                "from utils.logger import",
                "from models.user import"
            ]
            
            for imp in required_imports:
                if imp not in content:
                    return False, f"Missing import: {imp}"
            
            return True, "Validation passed"
        
        except Exception as e:
            return False, f"Validation error: {e}"
    
    def _rollback(self):
        """Rollback to backup if enhancement failed."""
        try:
            if self.backup_path.exists():
                logger.info(f"🔄 Rolling back to backup...")
                shutil.copy2(self.backup_path, self.ai_logic_path)
                self.backup_path.unlink()
                logger.info("✅ Rollback complete")
        except Exception as e:
            logger.error(f"❌ Rollback failed: {e}")
