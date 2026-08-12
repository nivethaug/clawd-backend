# Discord Bot - AI Agent Guide

This guide helps AI assistants understand and modify this Discord bot.

## Architecture (SLASH COMMANDS ONLY)

```
main.py (entry point + slash command registration)
    ├── commands/            # Slash command handlers
    │   ├── start.py         # /start - user registration
    │   ├── help.py          # /help - show commands
    │   ├── ask.py           # /ask <query> - free-text AI query
    │   └── status.py        # /status - bot status
    ├── services/            # Business logic
    │   ├── ai_logic.py      # process_user_input() — the /ask brain (MODIFY THIS)
    │   ├── api_client.py    # External API calls (MODIFY THIS)
    │   └── mock_data.py     # Fallback responses
    ├── models/              # Database models
    │   └── user.py          # User CRUD operations
    ├── core/                # Infrastructure
    │   └── database.py      # PostgreSQL connection
    └── utils/
        └── logger.py        # Logging setup
```

No text/prefix commands (!cmd). All interactions are slash commands.
No `message_content` privileged intent needed.

## How to Add a New Command

### Option A — /ask keyword (RECOMMENDED, no main.py changes):

Edit `services/ai_logic.py` → `process_user_input(text)`:
```python
if text_lower.startswith("weather"):
    parts = text_lower.split()
    if len(parts) < 2:
        return "Usage: /ask weather <city>"
    return _handle_weather(parts[1])
```
User accesses via `/ask weather london`.

### Option B — Dedicated slash command (typed parameters):

1. Create `commands/weather.py`:
```python
import discord

async def weather_handler(interaction: discord.Interaction, city: str):
    result = _handle_weather(city)
    await interaction.response.send_message(result)

def setup(bot):
    pass  # Registered in main.py
```

2. Register in `main.py` `setup_commands()`:
```python
from commands.weather import weather_handler

@bot.tree.command(name="weather", description="Get weather for a city")
@app_commands.describe(city="City name")
async def weather_cmd(interaction: discord.Interaction, city: str):
    await weather_handler(interaction, city)
```

3. `bot.tree.sync()` in `on_ready()` pushes it to Discord automatically.

## How to Modify AI Behavior

Edit `services/ai_logic.py` → `process_user_input(text)`:
- Add new intent detection (if/elif with startswith)
- Call API via `api_client.py` helpers
- Return response string
- Fallback to `mock_data.py`

## How to Add External API

1. Add helper function to `services/api_client.py` (follow get_crypto_price pattern)
2. Call from `services/ai_logic.py`
3. Handle errors with friendly fallback

## How LLM Extends Web Scraping

Use `services/web_scraper.py` when data needs JavaScript rendering (dynamic sites, infinite scroll, client-side UI).

### Preferred Integration Flow

1. Add a wrapper function in `services/api_client.py` that builds `ScrapeConfig`.
2. Call `scrape_url(url, config)` for simple cases.
3. For complex sites, subclass `WebScraper`, then `register_scraper("name", MyScraper)`.
4. Consume results in `services/ai_logic.py` and return a plain response string.

### LLM Extension Rules

- Put scraping logic in `services/api_client.py` or `services/web_scraper.py`.
- Use specific CSS selectors and set `max_pages` to bound crawl size.
- If auth is needed, use `ScrapeConfig.auth` fields.
- After structural changes, update `agent/ai_index/index.json`.

## How to Modify Database

1. Add table creation in `core/database.py` → `init_db()`
2. Create model functions in `models/`
3. Import in `models/__init__.py`

## Publishing Changes

```bash
# Run unit tests
python -m pytest unit/ -v

# Publish (handles PM2 restart via worker-api)
python3 buildpublish.py . {project_id}

# Verify by reading logs
cat logs/out.log | tail -20
cat logs/error.log | tail -10
```

NEVER run pm2 commands directly — use buildpublish.py.

## Error Handling

- Slash command errors caught in `main.py` → `on_app_command_error`
- API errors fall back to mock data in `ai_logic.py`
- Database errors logged and user notified gracefully

## Safety Rules

- Slash commands registered ONLY in `main.py` `setup_commands()` via `@bot.tree.command`
- Each handler receives `discord.Interaction` (NOT ctx)
- Respond via `interaction.response.send_message()` within 3 seconds
- NO API calls directly in command handlers — route through `process_user_input()` or ai_logic helpers
- AI can modify: `services/ai_logic.py`, `services/api_client.py`, `main.py` (slash registration), `commands/help.py`
- DO NOT modify: `commands/start.py`, `commands/ask.py`, `commands/status.py`, `config.py`, `core/`, `models/`, `utils/`
