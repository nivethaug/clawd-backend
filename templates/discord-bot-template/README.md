# Discord Bot Template

A clean, minimal, AI-friendly Discord bot template with PostgreSQL support for DreamAgent integration.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add:
# - DISCORD_TOKEN (from Discord Developer Portal)
# - DATABASE_URL (PostgreSQL connection string)

# Run the bot
python main.py
```

## Structure

```
discord_bot_template/
├── main.py              # Entry point (no logic)
├── config.py            # Configuration
├── requirements.txt     # Dependencies
├── .env.example         # Environment template
├── buildpublish.py      # Build & publish script
├── commands/            # Discord command handlers
│   ├── start.py         # !start command
│   ├── help.py          # !help command
│   ├── ask.py           # !ask <query>
│   └── status.py        # !status command
├── services/            # Business logic
│   ├── ai_logic.py      # Core AI decision engine
│   ├── api_client.py    # External API calls
│   └── mock_data.py     # Fallback responses
├── core/                # Core infrastructure
│   └── database.py      # PostgreSQL connection
├── models/              # Database models
│   └── user.py          # User model
├── utils/               # Utilities
│   └── logger.py        # Logging setup
├── unit/                # Unit tests
│   ├── test_commands.py  # Command handler tests
│   ├── test_handlers.py  # API client tests
│   └── README.md         # Test documentation
├── agent/               # AI assistant guide
│   └── README.md        # Code navigation instructions
└── ai_index/            # AI codebase index
    ├── symbols.json      # Functions, commands with locations
    ├── modules.json      # Logical module groupings
    ├── dependencies.json # Import relationships
    ├── summaries.json    # File semantic descriptions
    └── files.json        # File metadata
```

## Design Principles

1. **NO business logic in `main.py`** - Only handler registration
2. **ALL behavior in `ai_logic.py`** - Easy to modify
3. **ALL APIs in `api_client.py`** - Centralized API calls
4. **Commands only route** - Minimal, predictable code
5. **Database-ready** - PostgreSQL support with user persistence

## Database Features

### User Model
- **Unified user system**: Supports both Discord users and email-based users
- **Discord users**: Auto-created on first message
- **Email users**: Optional, for API authentication
- **Single table**: Simple, extensible schema

### Auto-Creation
Discord users are automatically created in the database:
```python
# In commands/start.py
user = get_or_create_discord_user(
    db=db,
    discord_user_id=str(ctx.author.id),
    discord_username=str(ctx.author)
)
```

## Commands

| Command | Description |
|---------|-------------|
| `!start` | Register your account |
| `!help` | Show available commands |
| `!ask <query>` | Ask a question or send a message |
| `!status` | Check bot status and latency |

## AI-Friendly Features

- Clean separation of concerns
- Predictable file structure
- Clear function signatures
- Safe environment handling
- Minimal dependencies
- Easy to extend
- Database integration
- User context in all handlers

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
3. Add table creation in `core/database.py` → `init_db()`

## Dependencies

### Core
- `discord.py==2.3.2` - Discord Bot API
- `requests==2.31.0` - HTTP client
- `python-dotenv==1.0.0` - Environment management

### Database
- `psycopg2-binary==2.9.9` - PostgreSQL adapter

## Security

- Token stored in `.env` (never committed)
- `.gitignore` excludes sensitive files
- No hardcoded credentials
- Environment-based configuration
- Database connection pooling

## DreamAgent Integration

This template is designed for automated deployment:

```
Template -> Copy -> Inject .env -> Modify ai_logic -> Run PM2
```

**Template is:**
- Generic
- Clean
- Predictable
- Easy to modify programmatically
- Database-ready
- AI-friendly (with agent guide)

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

**Example AI Workflow:**
```
User: "Add Ethereum price tracking"

AI Agent:
1. Check agent/README.md -> Find "How to Add External API"
2. Check ai_index/symbols.json -> Find fetch_bitcoin_price()
3. Check ai_index/dependencies.json -> See ai_logic.py calls api_client
4. Modify services/api_client.py -> Add fetch_ethereum_price()
5. Modify services/ai_logic.py -> Add ETH detection logic
6. Update ai_index/symbols.json -> Add new function with line numbers
```

## Example Usage

### User sends first message:
1. Bot receives message
2. User auto-created in database
3. User context passed to AI logic
4. Response sent back

### User asks "whoami":
```
You can use `!start` to see your Discord user info!
```

### User asks "BTC price":
```
Bitcoin Price: $45,123.45
```

## PM2 Deployment

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

## Unit Tests

```bash
# Run all tests
python -m pytest unit/ -v

# Or with unittest
python -m unittest discover unit/ -v
```

## License

MIT
