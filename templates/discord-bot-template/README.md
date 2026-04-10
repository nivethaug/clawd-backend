# Discord Bot Template

A clean, minimal, AI-friendly Discord bot template with PostgreSQL support for DreamPilot integration.

## Quick Start

### Prerequisites

1. **Create a Discord Application** at https://discord.com/developers/applications/
2. **Bot Settings** -> Reset Token -> Copy the bot token
3. **Privileged Gateway Intents** -> Enable **Message Content Intent**
4. **Invite the bot** using this URL format:
   ```
   https://discord.com/oauth2/authorize?client_id=YOUR_APP_ID&scope=bot&permissions=277025770560
   ```

### Install & Run

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add:
# - DISCORD_TOKEN (from Discord Developer Portal)
# - DATABASE_URL (PostgreSQL connection string)
# - PORT (for health endpoint, default 8010)

# Run the bot
python main.py
```

## Structure

```
discord_bot_template/
├── main.py              # Entry point (no logic) + health server
├── config.py            # Configuration (DISCORD_TOKEN, DB, PORT)
├── requirements.txt     # Dependencies
├── .env.example         # Environment template
├── buildpublish.py      # Build & publish script (PM2)
├── commands/            # Discord command handlers
│   ├── start.py         # !start command (user registration)
│   ├── help.py          # !help command
│   ├── ask.py           # !ask <query>
│   └── status.py        # !status command (bot info)
├── services/            # Business logic
│   ├── ai_logic.py      # Core AI decision engine (primary modification target)
│   ├── api_client.py    # External API calls
│   └── mock_data.py     # Fallback responses
├── core/                # Core infrastructure
│   └── database.py      # PostgreSQL connection + auto-migration
├── models/              # Database models
│   └── user.py          # User model (shared with main backend)
├── utils/               # Utilities
│   └── logger.py        # Logging setup
├── unit/                # Unit tests
│   ├── test_commands.py # Command handler tests
│   └── test_handlers.py # API client tests
├── agent/               # AI assistant guide
│   ├── README.md        # Code navigation instructions
│   └── ai_index/        # Codebase index (JSON)
└── logs/                # PM2 log output directory
```

## Architecture

### Message Flow

```
Discord User                    Your Bot (PM2 process)
─────────────                   ──────────────────────
User types:                     discord.py connects via
  "!ask bitcoin"       ──→      WebSocket gateway
                                       │
                                       ▼
                                 on_message (logs all messages)
                                       │
                                       ▼
                                 commands/ask.py: ask()
                                       │
                                       ▼
                                 services/ai_logic.py:
                                   process_user_input("bitcoin")
                                       │
                                       ▼
                                 services/api_client.py:
                                   CoinGecko API call
                                       │
                                       ▼
                           ◀──    ctx.send("$94,231.00")
                           
User sees bot reply
in Discord channel
```

### Health Endpoint

The bot starts a lightweight HTTP server on `PORT` for infrastructure verification:

- `GET /health` → `{"status": "healthy", "service": "discord-bot"}`
- Used by deployment pipeline to verify the bot is running
- Runs in a background thread alongside the Discord gateway

### Logging

All bot components use structured logging visible via PM2:

```
pm2 logs dc-bot-{project_id} --lines 50
```

Log events include:
- `[MSG]` - Every message the bot sees (guild, channel, author, content)
- `[CMD]` - Command execution with arguments
- `[CMD-DONE]` - Command completion
- `[CMD-ERR]` - Command errors with full traceback
- `[services.ai_logic]` - Intent detection (greeting, bitcoin, etc.)
- `[services.api_client]` - External API requests and responses

### Database

The bot connects to the shared PostgreSQL database. On startup, `init_db()`:
1. Creates the `users` table if it doesn't exist
2. Auto-adds `discord_user_id` column if the table exists without it (shared DB scenario)

This allows the bot to coexist with the main DreamPilot backend which uses the same `users` table.

## Design Principles

1. **NO business logic in `main.py`** - Only command registration
2. **ALL behavior in `ai_logic.py`** - Easy to modify
3. **ALL APIs in `api_client.py`** - Centralized API calls
4. **Commands only route** - Minimal, predictable code
5. **Database-ready** - PostgreSQL support with shared schema
6. **Structured logging** - Full message and command visibility

## Commands

| Command | Description |
|---------|-------------|
| `!start` | Register your Discord account in the database |
| `!help` | Show available commands |
| `!ask <query>` | Ask a question (routes through AI logic) |
| `!status` | Check bot status and latency |

## AI-Friendly Features

- Clean separation of concerns
- Predictable file structure
- Clear function signatures
- Safe environment handling
- Minimal dependencies
- Easy to extend
- Full structured logging
- Shared database schema

## Extending the Bot

### Add New Command

1. Create `commands/new_command.py`
2. Register in `main.py`:
   ```python
   from commands.new_command import setup as setup_new
   setup_new(bot)
   ```

### Add New API

1. Add function to `services/api_client.py`
2. Call from `services/ai_logic.py`

### Add New Logic

1. Modify `services/ai_logic.py`
2. Add new conditions in `process_user_input()`

### Add Database Model

1. Create model functions in `models/`
2. Import in `models/__init__.py`
3. Add migration in `core/database.py` → `init_db()` (use ALTER TABLE for existing DBs)

## Dependencies

### Core
- `discord.py==2.3.2` - Discord Bot API
- `requests==2.31.0` - HTTP client
- `python-dotenv==1.0.0` - Environment management

### Database
- `sqlalchemy==2.0.25` - SQL toolkit
- `psycopg2-binary==2.9.9` - PostgreSQL adapter

## Security

- Token stored in `.env` with chmod 600 permissions
- `.gitignore` excludes sensitive files
- No hardcoded credentials
- Environment-based configuration
- Health endpoint runs on internal port only

## DreamPilot Integration

This template is designed for automated deployment:

```
API creates project → Copy template → Inject .env → Install deps → 
Start PM2 → Configure nginx/DNS → Verify health → AI enhance → 
Run buildpublish → Final verify
```

### PM2 Management

```bash
# Start bot
pm2 start main.py --name dc-bot-{project_id} --interpreter python3 --cwd /path/to/discord/

# View structured logs
pm2 logs dc-bot-{project_id} --lines 50

# Restart after code changes
pm2 restart dc-bot-{project_id}

# Check status
pm2 status dc-bot-{project_id}
```

### Testing with dreamtest CLI

```bash
# Create and test a Discord bot project
dreamtest discord --name "My Bot" --token "YOUR_DISCORD_TOKEN" --desc "A test bot"

# Skip infrastructure verification
dreamtest discord --name "My Bot" --token "YOUR_DISCORD_TOKEN" --skip-verify

# JSON output for automation
dreamtest discord --name "My Bot" --token "YOUR_DISCORD_TOKEN" --agent
```

## Troubleshooting

### `PrivilegedIntentsRequired` error
Enable **Message Content Intent** in the Discord Developer Portal:
- https://discord.com/developers/applications/ -> Bot -> Privileged Gateway Intents

### `CommandRegistrationError: The command help is already an existing command`
This is handled in `commands/help.py` — the built-in help command is removed before registering the custom one.

### `column "discord_user_id" does not exist`
`init_db()` auto-adds the column via ALTER TABLE. Restart the bot to trigger the migration.

### Bot shows `Guilds: 0`
The bot hasn't been invited to any server. Use the invite URL with `&scope=bot`:
```
https://discord.com/oauth2/authorize?client_id=YOUR_APP_ID&scope=bot&permissions=277025770560
```

## Unit Tests

```bash
# Run all tests
python -m pytest unit/ -v

# Or with unittest
python -m unittest discover unit/ -v
```

## AI Agent Support

The `agent/` folder contains comprehensive documentation for AI assistants:

**agent/README.md** - Complete guide for:
- PM2 process management
- Database modifications
- Command/handler structure
- AI logic modification
- API integration
- Error troubleshooting

**ai_index/** - Structured codebase index:
- `symbols.json` - All functions, commands with line numbers
- `modules.json` - Logical module groupings and responsibilities
- `dependencies.json` - Import relationships between files
- `summaries.json` - Semantic descriptions of each file
- `files.json` - File metadata (lines, types, endpoints)

**How AI Agents Use This:**
1. Read `agent/README.md` to understand architecture
2. Query `ai_index/symbols.json` to find exact code locations
3. Check `ai_index/dependencies.json` to understand relationships
4. Use `ai_index/summaries.json` for context about files
5. Make targeted modifications based on line numbers
6. Update `ai_index/` files after code changes

## License

MIT
