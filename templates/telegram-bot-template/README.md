# Telegram Bot Template

A clean, minimal, AI-friendly Telegram bot template with PostgreSQL support for DreamAgent integration.

## 🚀 Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add:
# - BOT_TOKEN (from BotFather)
# - DATABASE_URL (PostgreSQL connection string)
# - SECRET_KEY (random string for JWT)

# Run the bot
python main.py
```

## 📁 Structure

```
telegram_bot_template/
├── main.py              # Entry point (no logic)
├── config.py            # Configuration
├── requirements.txt     # Dependencies
├── .env.example         # Environment template
├── buildpublish.py      # Build & publish script
├── handlers/            # Message/command handlers
│   ├── start.py         # /start command
│   ├── help.py          # /help command
│   └── message.py       # Text message handler
├── services/            # Business logic
│   ├── api_client.py    # External API calls
│   ├── ai_logic.py      # Core business logic
│   └── database.py      # Database operations
├── core/                # Core infrastructure
│   └── database.py      # PostgreSQL connection
├── models/              # Database models
│   └── user.py          # User model
├── routes/              # API routes
│   ├── auth.py          # Authentication endpoints
│   ├── health.py        # Health check endpoint
│   └── webhook.py       # Telegram webhook endpoint
├── utils/               # Utilities
│   └── logger.py        # Logging setup
├── unit/                # Unit tests
│   ├── test_commands.py  # Command handler tests
│   ├── test_handlers.py   # Message handler tests
│   └── README.md         # Test documentation
├── agent/               # AI assistant guide
│   └── README.md        # Code navigation instructions
└── ai_index/            # AI codebase index
    ├── symbols.json      # Functions, commands, APIs with locations
    ├── modules.json      # Logical module groupings
    ├── dependencies.json # Import relationships
    ├── summaries.json    # File semantic descriptions
    └── files.json       # File metadata
```

## 🎯 Design Principles

1. **NO business logic in `main.py`** - Only handler registration
2. **ALL behavior in `ai_logic.py`** - Easy to modify
3. **ALL APIs in `api_client.py`** - Centralized API calls
4. **Handlers only route** - Minimal, predictable code
5. **Database-ready** - PostgreSQL support with user persistence

## 🗄️ Database Features

### User Model
- **Unified user system**: Supports both Telegram users and email-based users
- **Telegram users**: Auto-created on first message
- **Email users**: Optional, for API authentication
- **Single table**: Simple, extensible schema

### Auto-Creation
Telegram users are automatically created in the database:
```python
# In handlers/message.py
user = get_or_create_telegram_user(
    db=db,
    telegram_user_id=user_id,
    telegram_chat_id=chat_id,
    telegram_username=username
)
```

## 🔐 Authentication

### Telegram Auth (Automatic)
- Users auto-created on first message
- No registration needed
- Persistent across sessions

### Email Auth (Optional)
```bash
# Register
POST /auth/register
{
  "email": "user@example.com",
  "password": "securepassword"
}

# Login
POST /auth/login
{
  "email": "user@example.com",
  "password": "securepassword"
}

# Get user info
GET /auth/me
Authorization: Bearer <token>
```

## 🤖 AI-Friendly Features

- ✅ Clean separation of concerns
- ✅ Predictable file structure
- ✅ Clear function signatures
- ✅ Safe environment handling
- ✅ Minimal dependencies
- ✅ Easy to extend
- ✅ Database integration
- ✅ User context in all handlers

## 🔧 Extending the Bot

### Add New Command

1. Create `handlers/new_command.py`
2. Register in `main.py`:
   ```python
   from handlers.new_command import new_command
   app.add_handler(CommandHandler("new_command", new_command))
   ```

### Add New API

1. Add function to `services/api_client.py`
2. Call from `services/ai_logic.py`

### Add New Logic

1. Modify `services/ai_logic.py`
2. Add new conditions in `process_user_input()`

### Add Database Model

1. Create model in `models/`
2. Import in `models/__init__.py`
3. Tables auto-created on startup

## 📦 Dependencies

### Core
- `python-telegram-bot==20.7` - Telegram Bot API
- `requests==2.31.0` - HTTP client
- `python-dotenv==1.0.0` - Environment management

### Database
- `sqlalchemy==2.0.25` - ORM
- `psycopg2-binary==2.9.9` - PostgreSQL adapter

### Auth (Optional)
- `passlib[bcrypt]==1.7.4` - Password hashing
- `python-jose==3.3.0` - JWT tokens
- `fastapi==0.109.0` - API framework
- `uvicorn==0.27.0` - ASGI server
- `pydantic==2.5.0` - Data validation

## 🔐 Security

- ✅ Token stored in `.env` (never committed)
- ✅ `.gitignore` excludes sensitive files
- ✅ No hardcoded credentials
- ✅ Environment-based configuration
- ✅ Password hashing with bcrypt
- ✅ JWT token authentication
- ✅ Database connection pooling

## 🎨 DreamAgent Integration

This template is designed for automated deployment:

```
Template → Copy → Inject .env → Modify ai_logic → Run PM2
```

**Template is:**
- ✅ Generic
- ✅ Clean
- ✅ Predictable
- ✅ Easy to modify programmatically
- ✅ Database-ready
- ✅ AI-friendly (with agent guide)

## 🤖 AI Agent Support

The `agent/` folder contains comprehensive documentation for AI assistants:

**agent/README.md** - Complete guide for:
- PM2 process management
- Database modifications
- Command/handler structure
- AI logic modification
- API integration
- Webhook configuration
- Error troubleshooting

**ai_index/** - Structured codebase index:
- `symbols.json` - All functions, commands, APIs with line numbers
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
1. Check agent/README.md → Find "How to Add External API"
2. Check ai_index/symbols.json → Find get_bitcoin_price()
3. Check ai_index/dependencies.json → See ai_logic.py calls api_client
4. Modify services/api_client.py → Add get_ethereum_price()
5. Modify services/ai_logic.py → Add ETH detection logic
6. Update ai_index/symbols.json → Add new function with line numbers
```

## 📝 Example Usage

### User sends first message:
1. Bot receives message
2. User auto-created in database
3. User context passed to AI logic
4. Response sent back

### User asks "whoami":
```
🆔 Your Telegram ID: 123456789
💬 Chat ID: 123456789
👤 Username: @johndoe
```

### User asks "BTC price":
```
💰 Bitcoin Price: $45,123.45
```

## 🚀 PM2 Deployment

```bash
# Start bot
pm2 start main.py --name tg-bot-{project_id} --interpreter python3

# View logs
pm2 logs tg-bot-{project_id}

# Restart
pm2 restart tg-bot-{project_id}

# Stop
pm2 stop tg-bot-{project_id}
```

## 📝 License

MIT
