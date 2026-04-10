# Discord Bot - AI Agent Guide

This guide helps AI assistants understand and modify this Discord bot.

## Architecture

```
main.py (entry point, NO logic)
    ├── commands/        # Discord command handlers (route only)
    │   ├── start.py     # !start - user registration
    │   ├── help.py      # !help - show commands
    │   ├── ask.py       # !ask <query> - AI query
    │   └── status.py    # !status - bot status
    ├── services/        # Business logic
    │   ├── ai_logic.py  # Core decision engine (MODIFY THIS)
    │   ├── api_client.py # External API calls (MODIFY THIS)
    │   └── mock_data.py # Fallback responses
    ├── models/          # Database models
    │   └── user.py      # User CRUD operations
    ├── core/            # Infrastructure
    │   └── database.py  # PostgreSQL connection
    └── utils/
        └── logger.py    # Logging setup
```

## How to Add a New Command

1. Create `commands/new_command.py`:
```python
async def new_command(ctx):
    await ctx.send("Response here")

def setup(bot):
    bot.command(name="new_command")(new_command)
```

2. Register in `main.py` `setup_commands()`:
```python
from commands.new_command import setup as setup_new
setup_new(bot)
```

## How to Modify AI Behavior

Edit `services/ai_logic.py` → `process_user_input(text)`:
- Add new intent detection (if/elif)
- Call API via `api_client.py`
- Return response string
- Fallback to `mock_data.py`

## How to Add External API

1. Add URL to `services/api_client.py` → `API_URLS` dict
2. Create a fetch function
3. Call from `services/ai_logic.py`

## How to Modify Database

1. Add table creation in `core/database.py` → `init_db()`
2. Create model functions in `models/`
3. Import in `models/__init__.py`

## PM2 Management

```bash
# Start bot
pm2 start main.py --name dc-bot-{project_id} --interpreter python3

# View logs
pm2 logs dc-bot-{project_id}

# Restart
pm2 restart dc-bot-{project_id}

# Stop
pm2 stop dc-bot-{project_id}
```

## Error Handling

- All errors caught in `main.py` → `on_command_error`
- API errors fall back to mock data in `ai_logic.py`
- Database errors logged and user notified gracefully

## Safety Rules

- NO logic in `main.py`
- NO API calls in commands
- NO structure changes without updating ai_index
- AI can modify ONLY: `services/ai_logic.py`, `services/api_client.py`
