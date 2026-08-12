"""
Discord Bot AI Editor
Enhances bot logic using Claude AI based on user description.
ACPX-inspired pattern: read -> prompt -> modify -> validate -> rollback if failed.
"""
import os
import shutil
from pathlib import Path
from typing import Tuple
import logging
from utils.logger import logger  # noqa: F811 — reassign below
logger = logging.getLogger("services.discord.editor")
from workflow_prompt_meta import build_workflow_meta_block
from services.container_storage import to_container_path
from integration_prompt_block import build_external_integrations_block

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

    def __init__(self, project_path: str, project_id: int = None):
        """
        Initialize editor.

        Args:
            project_path: Path to discord/ directory
        """
        self.project_path = Path(project_path)
        self.project_id = project_id

        # Core logic files
        self.ai_logic_path = self.project_path / "services" / "ai_logic.py"
        self.api_client_path = self.project_path / "services" / "api_client.py"

        # Command files (AI can edit to update welcome/help messages)
        self.start_cmd_path = self.project_path / "commands" / "start.py"
        self.ask_cmd_path = self.project_path / "commands" / "ask.py"
        self.help_cmd_path = self.project_path / "commands" / "help.py"
        self.main_path = self.project_path / "main.py"

        # Backup paths
        self.backup_ai_logic = self.project_path / "services" / "ai_logic.py.backup"
        self.backup_api_client = self.project_path / "services" / "api_client.py.backup"
        self.backup_start_cmd = self.project_path / "commands" / "start.py.backup"
        self.backup_ask_cmd = self.project_path / "commands" / "ask.py.backup"
        self.backup_help_cmd = self.project_path / "commands" / "help.py.backup"
        self.backup_main = self.project_path / "main.py.backup"

        # Token usage from last query
        self._last_token_usage = None

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

            if self.help_cmd_path.exists():
                logger.info(f"Creating backup: {self.backup_help_cmd}")
                shutil.copy2(self.help_cmd_path, self.backup_help_cmd)

            if self.main_path.exists():
                logger.info(f"Creating backup: {self.backup_main}")
                shutil.copy2(self.main_path, self.backup_main)

            # Fix file ownership so Claude Code (dreampilot user) can write
            import subprocess
            subprocess.run(
                ["chown", "-R", "dreampilot:dreampilot", str(self.project_path)],
                capture_output=True
            )

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
                                   self.backup_start_cmd, self.backup_ask_cmd,
                                   self.backup_help_cmd, self.backup_main]:
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
        """Build AI prompt for Discord bot enhancement with dynamic command generation."""
        # Derive domain from project path (e.g. .../1922_bot-name_ts/discord -> parent dir name)
        _parent = self.project_path.parent.name
        domain = _parent.split("_", 1)[1].rsplit("_", 1)[0] if "_" in _parent else bot_name.lower().replace(" ", "-")
        meta_block = build_workflow_meta_block(
            project_type_id=3,
            project_type="discord",
            operation="create",
            workflow="discord_create",
            project_name=bot_name,
            project_id=self.project_id,
            project_path=to_container_path(str(self.project_path)),
            service_path=to_container_path(str(self.project_path)),
            prompt_kind="discord_ai_enhancement",
        )
        integrations_block = build_external_integrations_block(self.project_id)
        return f"""{meta_block}
Bot: {bot_name}
{integrations_block}
Allowed files to modify:
- services/ai_logic.py (PRIMARY — all bot behavior)
- services/api_client.py (helper functions only)
- commands/start.py (ONLY update welcome message text)
- commands/ask.py (ONLY if absolutely required)
- commands/help.py (update help text when new commands added)
- main.py (ONLY to register new command handlers — see COMMAND REGISTRATION below)

DO NOT modify: config.py, core/, models/, utils/, services/web_scraper.py, services/mock_data.py

IMPORTANT: api_client.py already has these functions — import and use them, do NOT recreate:
- fetch_json(url, params) — generic JSON fetcher
- fetch_page(url, extract_js) — fast web page scraper (~200ms)
- get_crypto_price(coin_id, currency) — crypto price
- get_weather(latitude, longitude) — weather
- get_news(query, page) — news headlines
Only add a NEW function to api_client.py if you need an API NOT listed above.
NEVER import a function name that doesn't exist (e.g. fetch_data) — if unsure,
Read api_client.py first to confirm the exact function name.

==================================================
COMMAND ROUTING ARCHITECTURE (CRITICAL — READ FIRST)
==================================================

The bot uses Discord.py commands (not on_message). This means:

1. main.py registers command handlers via bot.load_extension() or direct @bot.command()
2. Only registered commands (!start, !help, !ask, !status) reach handlers
3. ALL user input arrives through commands/ask.py → process_user_input()

THE FLOW:
  User types "!ask price btc" in Discord
  → Discord.py routes to commands/ask.py (registered command)
  → ask.py strips "!ask" prefix
  → process_user_input() receives: "price btc" (NO ! prefix)

  User types "!price btc" in Discord
  → Discord.py says "Command not found" (NOT registered in main.py)
  → NEVER reaches process_user_input()

THEREFORE: process_user_input() receives text WITHOUT any ! prefix.
All command matching must work on plain text like "price btc", NOT "!price btc".

==================================================
COMMAND REGISTRATION IN main.py
==================================================

If you add new command handlers in ai_logic.py that should be callable directly
(e.g., !price, !top), you MUST also register them in main.py.

Two approaches (pick ONE):

APPROACH A — Route everything through !ask (RECOMMENDED for simple bots):
  - All input goes through process_user_input() via ask.py
  - User types: "!ask price btc"
  - ai_logic parses: "price btc" → calls _handle_crypto_query("btc")
  - NO changes to main.py needed
  - Parsing in ai_logic uses: text.startswith("price") (no ! prefix)

APPROACH B — Register new Discord commands:
  - Add new command files like commands/price.py, commands/top.py
  - Register in main.py: bot.load_extension("commands.price")
  - Each command file calls process_user_input() internally
  - User types: "!price btc" directly

For MOST bots, use Approach A. Only use Approach B if the user explicitly
requests direct commands like !price, !top as separate Discord commands.

CRITICAL — !help command:
- main.py disables discord.py's built-in !help (help_command=None), so
  commands/help.py can safely register !help via bot.command(name="help").
- If you rewrite help.py, do NOT call bot.remove_command("help") — it's
  unnecessary now and can cause errors if the command doesn't exist.
- Just register !help normally: @bot.command(name="help")
==================================================

ANALYZE user description: "{description}"

During initial bot creation, LLM has FULL AUTONOMY to:
1. Match description to BEST category from /llm/categories/index.json
2. Select appropriate APIs from that category
3. Generate commands to use those APIs
4. NO USER INTERACTION NEEDED - decide everything autonomously

KEYWORD MATCHING PROCESS:
- Use category keywords array to find best match
- Use sample_questions to understand category purpose
- AI decides based on description complexity and intent

EXAMPLES:
- "weather tracker bot" -> weather category, use Open-Meteo API
- "crypto prices" -> crypto_finance category, use CoinGecko API
- "news aggregator" -> news category, use Hacker News API
- "joke bot" -> entertainment category, use JokeAPI
- "crypto price tracker" -> crypto_finance category, add !price, !market, !top commands

NOTE: User provides title + description - AI MUST decide APIs autonomously
- NO back-and-forth with user
- AI selects and implements best APIs for the use case

--------------------------------------------------
CRITICAL RULES (MANDATORY)
==================================================

🔴 DO NOT RUN THE BOT DIRECTLY IN THE SANDBOX.
The sandbox blocks psycopg2's C library (mmap restriction). If you run
`python3 main.py` or `python3 -c "import ..."` it will crash on psycopg2.
This is NOT a code bug — it's a sandbox limitation. The bot runs fine
via PM2 (outside the sandbox) after publishing.
ALWAYS publish via buildpublish.py and verify by reading logs. Never
try to test-import or run the bot directly.

🔴 RULE ZERO: ALWAYS READ LOGS FIRST.
Before fixing ANY issue (crash, no response, 502, DB error), ALWAYS read
the logs FIRST. The logs tell you EXACTLY what broke.

```bash
cat logs/error.log | tail -30
cat logs/out.log | tail -10
```

Reading logs is KNOWING. Reading code is guessing.
Never spend 10+ tool calls reading code when 1 log read reveals the answer.

Database issues? The log will show the exact DB error (connection refused,
auth failed, table missing). Do NOT guess — read the log and fix the
specific error shown. Common DB errors are normal on first startup
(table doesn't exist yet) and are handled by init_db().

After fixing, ALWAYS run unit tests then publish:
```bash
# 1. Run unit tests (tests command parsing, AI logic, API calls)
cd {self.project_path} && python -m pytest unit/ -v 2>&1 | tail -30

# 2. Publish (handles PM2 restart via worker-api)
cd {self.project_path} && python3 buildpublish.py . {self.project_id}

# 3. Verify by reading logs (NOT pm2, NOT curl, NOT running bot directly)
cat {self.project_path}/logs/out.log | tail -20
cat {self.project_path}/logs/error.log | tail -10
```
cat logs/error.log | tail -5
```
Do NOT curl the health URL — DNS may not be propagated yet.

SLASH COMMAND SYNC — IMPORTANT:
"Synced 0 commands to [guild]" in the logs is NORMAL. It means Discord
already has the commands cached from a previous sync. Discord.py returns
0 when there are no NEW commands to register. Do NOT try to fix this by
modifying the sync logic in main.py — it is working correctly.
Global slash commands can take up to 1 hour to propagate to all servers.

The ONLY time you should modify sync logic is if you added a genuinely
NEW slash command (e.g. /chart) that doesn't appear in Discord at all.
In that case, ensure the command is registered via bot.tree.command or
tree.add_command before calling tree.sync().

1. KEEP function signature EXACT:
   def process_user_input(text: str) -> str

2. DO NOT remove existing commands

3. DO NOT break existing command handlers

4. DO NOT add new imports (EXCEPT importing services.web_scraper in api_client.py if needed)

5. DO NOT create new files

6. ALWAYS return a string (NEVER return None)

7. NEVER crash - always fallback safely

==================================================
COMMAND PARSING RULES (STRICT)
==================================================

IMPORTANT: process_user_input() receives text WITHOUT ! prefix.
The !ask command handler strips the prefix before calling this function.
So user types "!ask price btc" → ai_logic receives "price btc".

NEVER use:
- .replace()
- partial string manipulation
- ! prefix in startswith checks (text arrives without it)

ALWAYS use:

parts = text_lower.split()

RULES:

1. ALL commands MUST use split()

2. ALWAYS validate argument length

3. NEVER access parts[i] without checking length

4. DO NOT mix parsing styles

5. DO NOT invent new parsing logic

--------------------------------------------------

STANDARD COMMAND FORMAT (no ! prefix — text arrives plain):

# User types "!ask price btc" → process_user_input receives "price btc"
# User types "!ask top 5" → process_user_input receives "top 5"
# User types "!ask market" → process_user_input receives "market"

--------------------------------------------------

EXAMPLES (FOLLOW EXACTLY — NOTE: NO ! PREFIX):

# price
if text_lower.startswith("price"):
    parts = text_lower.split()

    if len(parts) < 2:
        return "Usage: !ask price <coin>"

    coin = parts[1]
    return _handle_crypto_query(coin)


# top
if text_lower.startswith("top"):
    parts = text_lower.split()

    limit = 10
    if len(parts) >= 2 and parts[1].isdigit():
        limit = min(int(parts[1]), 50)

    return _handle_top_coins(limit)


# market
if text_lower.startswith("market"):
    parts = text_lower.split()

    limit = 10
    if len(parts) >= 2 and parts[1].isdigit():
        limit = min(int(parts[1]), 50)

    return _handle_market_data(limit)


# convert
if text_lower.startswith("convert"):
    parts = text_lower.split()

    if len(parts) < 4:
        return "Usage: !ask convert <amount> <from> <to>"

    return _handle_conversion(parts[1], parts[2], parts[3])

==================================================
!ask COMMAND HANDLING (STRICT)
==================================================

The !ask command is registered in main.py and handled by commands/ask.py.
ask.py strips "!ask" and sends only the query text to process_user_input().

So if user types "!ask price btc", process_user_input() receives "price btc".
The "ask" prefix is NEVER present in the text passed to process_user_input().

THEREFORE: Do NOT add a handler for "!ask" or "ask" in process_user_input().
All text arriving there is already the user's query without any command prefix.

Just parse the intent directly:

if text_lower.startswith("price"):
    parts = text_lower.split()
    if len(parts) < 2:
        return "Usage: !ask price <coin>"
    coin = parts[1]
    return _handle_crypto_query(coin)

# Default fallback for unrecognized queries
return f"I received your query: \"{{text}}\". Type !help for available commands."

==================================================
API USAGE
==================================================

STEP 1: Check if user explicitly wants public APIs

Read the description carefully:
- If "api" or "API" is mentioned -> Use existing internal functions
- If NOT mentioned -> Use public APIs from /llm/categories/index.json

--------------------------------------------------
PUBLIC API USAGE (When NO explicit API mention)
--------------------------------------------------

1. Load category index: templates/discord-bot-template/llm/categories/index.json

2. Match keywords from description to category keywords:
   - Example: "weather" -> weather category
   - Example: "crypto" -> crypto_finance category
   - Example: "news" -> news category

3. Load the matched category JSON file:
   - Use json_file field to find the file
   - Example: weather.json, crypto_finance.json, news.json

4. Use the category's APIs:
   - Call direct_url from the matched endpoint
   - Handle errors with friendly messages


--------------------------------------------------
INTERNAL API USAGE (When explicit API mention)
--------------------------------------------------

Use existing functions only:
- get_crypto_price
- get_market_data
- get_top_coins

If API fails:
-> return mock or friendly fallback

--------------------------------------------------
RULE SUMMARY
--------------------------------------------------

1. ALWAYS check description for "api" or "API" keyword
2. NO "api" keyword -> Use /llm/categories/index.json
3. YES "api" keyword -> Use existing internal functions
4. Public APIs: Call direct_url directly
5. Fallback: Always return friendly message on failure

==================================================
WEBSITE DATA (MANDATORY)
==================================================

If the user request requires fetching website data (scraping):
1. USE the existing CDP scraper in services/web_scraper.py (do NOT create a new scraper system).
2. Add a small helper wrapper in services/api_client.py that builds a ScrapeConfig and calls scrape_url().
3. If site-specific steps are needed, subclass WebScraper in services/web_scraper.py and register it.
4. Always include the target URL in ScrapeConfig.url and keep selectors specific.

Add a utility helper for each website-based request:
- Name it for the intent, e.g., scrape_site_headlines(), scrape_product_prices().
- Keep it pure: accept url + optional params, return {{success, data, errors}}.

Example pattern:

from services.web_scraper import ScrapeConfig, scrape_url

def scrape_site_headlines(url: str) -> dict:
    config = ScrapeConfig(
        url=url,
        items_selector="article",
        fields={{"title": "h2, h3", "link": "a"}},
        max_pages=1,
        scroll=True
    )
    result = scrape_url(url, config)
    return {{"success": len(result.errors) == 0, "data": result.data, "errors": result.errors}}

==================================================
FEATURE RULES
==================================================

- Add new commands ONLY if clearly required
- DO NOT remove existing commands
- DO NOT rename commands

SLASH COMMAND REGISTRATION — CRITICAL:
If you create slash commands (/price, /market, /chart), follow these rules
to prevent crashes and duplicate registration errors:

1. Register ALL slash commands in main.py's setup_commands() function ONLY.
   Use @bot.tree.command(...) decorator inside setup_commands().
   Do NOT also register them in command file setup() functions.

2. Command files (price.py, market.py, etc.) should ONLY contain the handler
   function (e.g., `async def price(interaction, symbol):`) and a NO-OP setup:
   ```python
   def setup(bot):
       # No-op: command registered directly in main.py
       pass
   ```

3. setup() functions MUST be SYNCHRONOUS: `def setup(bot):`
   NEVER use `async def setup(bot):` — main.py calls setup() without await.
   Using async setup() causes "coroutine was never awaited" warnings and
   commands will NOT be registered.

4. Pick ONE registration approach and stick with it:
   - RECOMMENDED: Register all @bot.tree.command in main.py setup_commands()
   - Command files just export the handler function
   - Do NOT mix bot.tree.command in both main.py AND command files

==================================================
START + HELP UPDATE RULE (MANDATORY)
==================================================

If new commands are added, you MUST update ALL of these:

1. UPDATE _handle_start() in services/ai_logic.py — mention new command in welcome
2. UPDATE _handle_help() in services/ai_logic.py — add new command description
3. UPDATE commands/help.py — add new command to help text

NEVER add a command and forget to update help + start text.
DO NOT break formatting

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

When using public APIs from /llm/categories/index.json:

1. Generate commands in ai_logic.py that call the public API
2. If new API function is needed in api_client.py:
   - Add the function following the same pattern as existing helpers
   - Example: get_weather, get_news, get_crypto_price, etc.
   - Always handle errors with friendly messages
   - Return dict with success/data or error

Return FULL updated code for:
- services/ai_logic.py

REQUIRED (when adding new APIs):
- services/api_client.py (add new helper functions for any APIs you use)

OPTIONAL:
- commands/start.py (only text changes for welcome message)

MANDATORY: After ALL code changes, read and update `agent/ai_index/index.json`
to reflect new commands, functions, and file changes. The index.json contains
"symbols", "summaries", and "files" sections — update all relevant entries.

==================================================
PUBLISH CHANGES — MANDATORY FINAL STEP
==================================================

After ALL file edits + index.json update, you MUST publish to restart the bot.
Run this Bash command (NOT direct pm2 commands — they fail in the sandbox):

    cd {self.project_path} && python3 buildpublish.py . {self.project_id}

- buildpublish.py handles PM2 restart via the worker-api.
- ⛔ NEVER run `pm2 restart`, `pm2 stop`, `pm2 logs`, or `sudo pm2` directly — pm2 is NOT in the sandbox PATH.
- ⛔ Do NOT pass the project root to buildpublish.py — it needs `.` (bot dir).
- After publish, verify by reading log files (NOT pm2 commands):
    cat {self.project_path}/logs/out.log | tail -20
    cat {self.project_path}/logs/error.log | tail -10
- ⛔ Do NOT curl the health URL — DNS takes time to propagate for new projects.

==================================================

## USER REQUEST

Enhance Discord bot for: {description}
"""

    def _run_claude_modification(self, prompt: str) -> dict:
        """Run Claude Code Agent to modify file."""
        try:
            import asyncio

            async def run_claude():
                # Phase 4: resolve user_id for container targeting (no-op in local mode).
                from claude_code_agent import resolve_user_id_for_project
                _user_id = resolve_user_id_for_project(self.project_id)
                async with ClaudeCodeAgent(
                    repo_path=str(self.project_path),
                    user_id=_user_id,
                ) as agent:
                    result = await agent.query(
                        prompt=prompt,
                        timeout=1800
                    )
                    # Capture token usage
                    self._last_token_usage = agent.last_token_usage
                    if self._last_token_usage:
                        logger.info(f"[DISCORD-EDITOR] Token usage: {self._last_token_usage}")
                    return result

            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    result = asyncio.run(run_claude())
                else:
                    result = loop.run_until_complete(
                        asyncio.wait_for(run_claude(), timeout=1800)
                    )
            except RuntimeError:
                result = asyncio.run(
                    asyncio.wait_for(run_claude(), timeout=1800)
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
            logger.error("Claude modification timeout after 1800s (30 min)")
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
            help_changed = False
            main_changed = False

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

            if self.backup_help_cmd.exists() and self.help_cmd_path.exists():
                with open(self.backup_help_cmd, 'r') as f:
                    backup_content = f.read()
                with open(self.help_cmd_path, 'r') as f:
                    modified_content = f.read()
                help_changed = (backup_content != modified_content)

            if self.backup_main.exists() and self.main_path.exists():
                with open(self.backup_main, 'r') as f:
                    backup_content = f.read()
                with open(self.main_path, 'r') as f:
                    modified_content = f.read()
                main_changed = (backup_content != modified_content)

            if not any([ai_logic_changed, api_client_changed, start_changed, ask_changed,
                        help_changed, main_changed]):
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

            # Check help.py if modified
            if help_changed and self.help_cmd_path.exists():
                with open(self.help_cmd_path, 'r') as f:
                    help_content = f.read()
                try:
                    compile(help_content, str(self.help_cmd_path), 'exec')
                except SyntaxError as e:
                    return False, f"Syntax error in help.py: {e}"

            # Check main.py if modified
            if main_changed and self.main_path.exists():
                with open(self.main_path, 'r') as f:
                    main_content = f.read()
                try:
                    compile(main_content, str(self.main_path), 'exec')
                except SyntaxError as e:
                    return False, f"Syntax error in main.py: {e}"

            # Validate function signature in ai_logic.py
            if "def process_user_input(text: str" not in ai_logic_content:
                return False, "Function signature changed or missing in ai_logic.py"

            # Check protected files were not modified
            protected_files = [
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

            if self.backup_help_cmd.exists():
                logger.info("Rolling back help.py...")
                shutil.copy2(self.backup_help_cmd, self.help_cmd_path)
                self.backup_help_cmd.unlink()

            if self.backup_main.exists():
                logger.info("Rolling back main.py...")
                shutil.copy2(self.backup_main, self.main_path)
                self.backup_main.unlink()

            logger.info("Rollback complete")
        except Exception as e:
            logger.error(f"Rollback failed: {e}")
