# Agent Guide - Telegram Bot Code Navigation & Modification

This folder helps AI assistants understand and modify telegram bot codebase efficiently.

---

## 🚀 PM2 Process Management (CRITICAL)

### Process Information

| Property | Value |
|----------|-------|
| **PM2 Process Name** | `{domain}-bot` or `tg-bot-{project_id}` |
| **Domain** | `{domain}.dreambigwithai.com` |
| **Webhook URL** | `https://{domain}.dreambigwithai.com/webhook` |
| **PM2 Config File** | `ecosystem.config.json` (auto-generated) |
| **Entry Point** | `main:app` (python-telegram-bot) |
| **Default Port** | `{port}` (from .env, default: 8443) |

### How to Publish Bot

From bot directory:

```bash
# Full publish (installs deps + restarts PM2) - DEFAULT
python3 buildpublish.py

# Skip dependencies (only restart PM2)
python3 buildpublish.py --skip-deps

# Skip restart (local testing)
python3 buildpublish.py --no-restart
```

**What it does:**
1. Installs Python dependencies (using shared venv)
2. Verifies main.py exists
3. Clears Python cache (`__pycache__`, `*.pyc`)
4. Restarts PM2 (`{domain}-bot`)
5. Re-registers Telegram webhook

**Options:**

| Flag | Description |
|------|-------------|
| `--skip-deps` | Skip pip install |
| `--no-restart` | Skip PM2 restart (local testing only) |
| `--venv` | Use specific venv path |

**When to Use:**

| Scenario | Command |
|----------|---------|
| After code changes | `python3 buildpublish.py` |
| Just restart | `python3 buildpublish.py --skip-deps` |
| Local testing | `python3 buildpublish.py --no-restart` |

### Manual PM2 Commands

```bash
pm2 status                          # Check status
pm2 logs {domain}-bot               # View logs
pm2 restart {domain}-bot            # Restart service
pm2 stop {domain}-bot               # Stop service
pm2 delete {domain}-bot             # Delete process
pm2 save                            # Persist across reboot
pm2 resurrect                       # Restore after reboot
```

### PM2 Process Naming

PM2 process name follows this priority:
1. **Primary**: `{domain}-bot` (from WEBHOOK_DOMAIN)
2. **Fallback**: `tg-bot-{project_id}` (from PROJECT_ID)

Examples:
- `crypto-bot-x123` (if WEBHOOK_DOMAIN=crypto-bot-x123)
- `tg-bot-1082` (if WEBHOOK_DOMAIN not set)

---

## 🗄️ Database Connection Details (CRITICAL)

### How Bot Connects to Database

The bot uses **SQLAlchemy ORM** with a connection string from environment variables:

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  PM2 Ecosystem  │────▶│  Environment     │────▶│  SQLAlchemy     │
│  Config JSON    │     │  Variables       │     │  Engine         │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                                                        │
                                                        ▼
                                                 ┌─────────────────┐
                                                 │  PostgreSQL     │
                                                 │  Database       │
                                                 └─────────────────┘
```

### Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | Full PostgreSQL connection string | `postgresql://{user}:{pass}@{host}:5432/{db}` |
| `PORT` | Bot webhook server port | `8443` |
| `WEBHOOK_DOMAIN` | Webhook subdomain | `crypto-bot-x123` |
| `WEBHOOK_URL` | Full webhook URL | `https://crypto-bot-x123.dreambigwithai.com/webhook` |
| `BOT_TOKEN` | Telegram bot token | `123456:ABC...` |
| `SECRET_KEY` | JWT secret key | `random-string` |

### Database Configuration Files

| File | Purpose |
|------|---------|
| `core/database.py` | Reads `DATABASE_URL` from environment |
| `models/*.py` | SQLAlchemy model definitions (tables) |

### DATABASE_URL Format

```
postgresql://{username}:{password}@{host}:{port}/{database}
```

| Component | Source |
|-----------|--------|
| `username` | `{project_name}_user` (auto-created) |
| `password` | Auto-generated (32 chars) |
| `host` | `postgres` (Docker) or `localhost` |
| `port` | `5432` |
| `database` | `{project_name}_db` (auto-created) |

---

## 🤖 Agent Guide: Database Modifications

### How to Read Current Database Schema

**Option 1: Read Models**
```python
# Check models/ folder for all table definitions
# Each model class = one database table
```

**Option 2: Query Database Directly**
```python
from core.database import engine
from sqlalchemy import inspect, text

inspector = inspect(engine)

# List all tables
tables = inspector.get_table_names()
print(f"Tables: {tables}")

# Get columns for a table
columns = inspector.get_columns('users')
for col in columns:
    print(f"  {col['name']}: {col['type']}")
```

### How to Add a New Table

**Step 1: Create Model File**

```python
# models/product.py
from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.sql import func
from core.database import Base

class Product(Base):
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    price = Column(Float, nullable=False)
    description = Column(String(500))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
```

**Step 2: Import in models/__init__.py**

```python
from models.user import User
from models.product import Product  # Add this

__all__ = ["User", "Product"]
```

**Step 3: Register in core/database.py**

```python
# Ensure model is imported so Base.metadata.create_all() creates table
import models.product  # Add this
```

**Step 4: Tables Auto-Create on Startup**

The `init_db()` function in `core/database.py` creates all tables:
```python
Base.metadata.create_all(bind=engine)
```

### How to Add a New Column to Existing Table

**Step 1: Update Model**

```python
# models/user.py
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    telegram_user_id = Column(Integer, unique=True, nullable=False)
    email = Column(String(255))  # ← NEW COLUMN
    created_at = Column(DateTime, server_default=func.now())
```

**Step 2: Manual SQL (Quick Fix):**

```python
from core.database import engine
from sqlalchemy import text

with engine.connect() as conn:
    conn.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(255)"))
    conn.commit()
```

### How to Create a New Relationship

**Step 1: Add Foreign Key**

```python
# models/order.py
from sqlalchemy import Column, Integer, ForeignKey
from sqlalchemy.orm import relationship
from core.database import Base

class Order(Base):
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.telegram_user_id"))
    total = Column(Float)
    
    # Relationship
    user = relationship("User", back_populates="orders")
```

**Step 2: Add Back-Reference**

```python
# models/user.py
class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    telegram_user_id = Column(Integer, unique=True)
    
    # Back-reference
    orders = relationship("Order", back_populates="user")
```

### How to Query Database

```python
from sqlalchemy.orm import Session
from core.database import SessionLocal
from models.user import User

# Get database session
db: Session = SessionLocal()

# Create
new_user = User(telegram_user_id=123456, telegram_chat_id=123456)
db.add(new_user)
db.commit()
db.refresh(new_user)

# Read
user = db.query(User).filter(User.telegram_user_id == 123456).first()
users = db.query(User).all()

# Update
user.email = "new@example.com"
db.commit()

# Delete
db.delete(user)
db.commit()

# Always close
db.close()
```

### Database Modification Checklist

| Action | Update Model | Migration | Restart | Update AI Index |
|--------|:------------:|:---------:|:-------:|:---------------:|
| Add table | ✅ | Auto | ✅ | ✅ |
| Add column | ✅ | Manual SQL | ✅ | ✅ |
| Remove column | ✅ | Manual SQL | ✅ | ✅ |
| Add relationship | ✅ | Manual SQL | ✅ | ✅ |
| Change column type | ✅ | Manual SQL | ✅ | ✅ |

---

## 🎯 Bot Command Structure

### Command Handlers

All bot commands are in `handlers/` directory:

| File | Command | Description |
|------|---------|-------------|
| `handlers/start.py` | `/start` | Initial user setup |
| `handlers/help.py` | `/help` | Display available commands |
| `handlers/message.py` | Text messages | Main user input handler |

### Adding a New Command

**Step 1: Create Handler File**

```python
# handlers/status.py
from telegram import Update
from telegram.ext import ContextTypes

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot status"""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    await update.message.reply_text(
        f"✅ Bot is running!\n"
        f"User ID: {user_id}\n"
        f"Chat ID: {chat_id}"
    )
```

**Step 2: Register in main.py**

```python
from telegram.ext import CommandHandler
from handlers.status import status_command

# Register command
app.add_handler(CommandHandler("status", status_command))
```

**Step 3: Update AI Index**

Add to `ai_index/symbols.json`:
```json
"status_command": {
  "type": "command",
  "file": "handlers/status.py",
  "start_line": 1,
  "end_line": 10,
  "module": "handlers",
  "description": "/status command - Show bot status"
}
```

### Message Handler

The main message handler in `handlers/message.py` routes user input to appropriate logic:

```python
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all text messages"""
    user_input = update.message.text
    user_id = update.effective_user.id
    
    # Get user from database
    user = get_or_create_user(user_id)
    
    # Process through AI logic
    response = process_user_input(user, user_input)
    
    await update.message.reply_text(response)
```

---

## 🧠 AI Logic (services/ai_logic.py)

This is the **brain of the bot** where all user interaction logic lives.

### Core Function

```python
async def process_user_input(
    user: User,
    user_input: str
) -> str:
    """
    Process user input and return response.
    
    This is the main entry point for all bot intelligence.
    AI agents should modify this function to add new features.
    
    Args:
        user: Database user object
        user_input: Text message from user
    
    Returns:
        Response text to send back
    """
```

### Adding New Features

**Example: Add Price Tracking**

```python
async def process_user_input(
    user: User,
    user_input: str
) -> str:
    user_input_lower = user_input.lower()
    
    # Feature 1: Bitcoin price (existing)
    if "btc" in user_input_lower or "bitcoin" in user_input_lower:
        price = get_bitcoin_price()
        return f"💰 Bitcoin Price: ${price}"
    
    # Feature 2: Price tracking (NEW)
    if "track" in user_input_lower:
        # Parse price to track
        parts = user_input_lower.split()
        if len(parts) >= 3:
            crypto = parts[1]
            price = float(parts[2])
            
            # Save to database
            alert = create_price_alert(user, crypto, price)
            return f"✅ Tracking {crypto.upper()} at ${price}"
    
    # Default
    return "I didn't understand. Type /help for commands."
```

### Calling External APIs

All external API calls should be in `services/api_client.py`:

```python
# services/api_client.py
import requests

def get_bitcoin_price():
    """Get current Bitcoin price from CoinGecko API"""
    response = requests.get(
        "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
    )
    data = response.json()
    return f"{data['bitcoin']['usd']:.2f}"
```

### Best Practices

1. **Keep ai_logic.py clean** - Only decision logic
2. **Use services/api_client.py** - All external API calls
3. **Return strings, not messages** - Handlers send the response
4. **Handle errors gracefully** - Return helpful error messages
5. **Log important actions** - Use logger for debugging

---

## 🔌 Webhook Configuration

### Webhook Setup

The bot uses **webhooks** (not polling) for real-time message delivery:

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Telegram    │────▶│  Webhook      │────▶│  Bot Server  │
│  Servers    │     │  Request      │     │  (main.py)   │
└─────────────┘     └──────────────┘     └─────────────┘
                                                        │
                                                        ▼
                                                 ┌─────────────┐
                                                 │  PM2 Process  │
                                                 └─────────────┘
```

### Webhook URL Format

```
https://{domain}.dreambigwithai.com/webhook
```

| Component | Value |
|-----------|-------|
| Protocol | `https://` |
| Domain | `{WEBHOOK_DOMAIN}.dreambigwithai.com` |
| Path | `/webhook` |

### Webhook Registration

Webhook is registered automatically during deployment:

1. **Initial registration** - During `run_telegram_bot_pipeline()` (Step 9)
2. **Re-registration** - After PM2 restart in `buildpublish.py`
3. **Manual registration** - If automatic fails:
   ```bash
   curl -X POST "https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url=https://{domain}/webhook"
   ```

### Allowed Updates

Bot registers for these update types:
- `message` - New messages
- `edited_message` - Edited messages
- `callback_query` - Button clicks (inline keyboards)

---

## 🔌 FastAPI Server (Optional)

Some bot templates include a FastAPI server for additional features:

### API Endpoints

| Endpoint | Method | Description |
|----------|---------|-------------|
| `/health` | GET | Health check (PM2 monitoring) |
| `/webhook` | POST | Telegram webhook endpoint |
| `/auth/register` | POST | Email-based user registration |
| `/auth/login` | POST | Email-based user login |

### Health Check

```python
@app.get("/health")
async def health_check():
    """Health check endpoint for PM2/monitoring"""
    return {
        "status": "healthy",
        "service": "telegram-bot",
        "timestamp": datetime.utcnow().isoformat()
    }
```

### Webhook Endpoint

```python
@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Receive webhook updates from Telegram"""
    body = await request.json()
    
    # Pass to bot application
    await app.process_update(
        Update.de_json(data=body),
        application
    )
    
    return {"status": "ok"}
```

---

## 🧠 AI Index Files

| File | Purpose | When to Update |
|------|---------|----------------|
| `ai_index/symbols.json` | Functions, classes, commands with line numbers | After adding/editing/removing any code |
| `ai_index/modules.json` | Logical module groupings | After adding new files/modules |
| `ai_index/dependencies.json` | Import relationships between files | After changing imports |
| `ai_index/summaries.json` | Semantic descriptions per file | After significant file changes |
| `ai_index/files.json` | File metadata (lines, handlers) | After adding/removing files |

---

## 📝 How to Add New Feature

### 1. Understand the Request
```
User requirement: Add weather updates to bot
```

### 2. Plan the Implementation

```python
# services/api_client.py - Add weather API
def get_weather(city: str) -> str:
    response = requests.get(f"https://api.weather.com/{city}")
    return response.json()['weather']
```

### 3. Update AI Logic

```python
# services/ai_logic.py
async def process_user_input(user: User, user_input: str) -> str:
    user_input_lower = user_input.lower()
    
    # Add weather command
    if "weather" in user_input_lower:
        city = user_input_lower.replace("weather", "").strip()
        weather = get_weather(city)
        return f"🌤 Weather in {city}: {weather}"
    
    # ... existing logic
```

### 4. Test Locally

```bash
# Run bot locally
python3 main.py

# Test via Telegram
# Send /start and then "weather London"
```

### 5. Deploy

```bash
# Publish changes
python3 buildpublish.py
```

---

## 🔧 How to Edit Existing Feature

### 1. Find Feature Location

```bash
# Search ai_index/symbols.json
grep -r "price" ai_index/symbols.json

# Or find in code
grep -r "bitcoin" handlers/ services/
```

### 2. Edit the Code

```python
# Modify api_client.py - Add more coins
def get_crypto_price(coin: str):
    response = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies=usd")
    return f"{data[coin]['usd']:.2f}"
```

### 3. Update AI Logic

```python
# services/ai_logic.py
async def process_user_input(user: User, user_input: str) -> str:
    # Add more crypto detection
    for coin in ["btc", "bitcoin", "eth", "ethereum"]:
        if coin in user_input_lower:
            price = get_crypto_price(coin)
            return f"💰 {coin.upper()} Price: ${price}"
```

### 4. Update AI Index

Update `ai_index/symbols.json` with new functions/line numbers.

### 5. Deploy

```bash
python3 buildpublish.py
```

---

## 📋 Quick Reference: AI Index Update Checklist

| Action | symbols | modules | dependencies | summaries | files |
|--------|:-------:|:-------:|:------------:|:---------:|:-----:|
| Add command | ✅ | - | - | - | - |
| Edit command | ✅ | - | - | - | - |
| Remove command | ✅ | - | - | - | - |
| Add handler | ✅ | ✅ | ✅ | ✅ | ✅ |
| Delete handler | ✅ | ✅ | ✅ | ✅ | ✅ |
| Add API function | ✅ | - | - | - | - |
| Add new file | ✅ | ✅ | ✅ | ✅ | ✅ |
| Delete file | ✅ | ✅ | ✅ | ✅ | ✅ |
| Change imports | - | - | ✅ | - | - |

---

## 🔄 Common Workflows

### Workflow 1: Add New Command

```
1. Create handlers/new_command.py
2. Implement async function
3. Register in main.py with CommandHandler
4. Update ai_index/symbols.json
5. Run buildpublish.py
```

### Workflow 2: Add External API

```
1. Add function to services/api_client.py
2. Call from services/ai_logic.py
3. Handle errors gracefully
4. Update ai_index/symbols.json
5. Test and deploy
```

### Workflow 3: Add Database Feature

```
1. Create model in models/
2. Import in models/__init__.py
3. Use in handlers/ or services/
4. Restart bot (creates table automatically)
5. Update ai_index/symbols.json
```

### Workflow 4: Debug Bot Issue

```
1. Check PM2 logs: pm2 logs {domain}-bot
2. Verify .env variables are correct
3. Check database connection
4. Test with simple message
5. Add logging to isolate issue
```

---

## 🐛 Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `Bot token is invalid` | Wrong BOT_TOKEN in .env | Get token from @BotFather |
| `Webhook failed` | Domain not resolving | Check DNS, wait for propagation |
| `Database connection failed` | Wrong DATABASE_URL | Verify credentials, host, port |
| `Port already in use` | Port conflict | Change PORT in .env |
| `Module not found` | Missing dependency | Run buildpublish.py |
| `Handler not found` | Not registered in main.py | Check app.add_handler() calls |

---

## 📝 Best Practices

1. **Use async/await** for all bot handlers
2. **Keep handlers minimal** - Logic in ai_logic.py
3. **Handle all exceptions** - Don't crash the bot
4. **Log important actions** - Use logger module
5. **Use database sessions** - Always close them
6. **Test locally** - Deploy after verifying
7. **Update AI index** - After code changes
8. **Use .env for config** - No hardcoded values
9. **Keep responses user-friendly** - Use emojis, clear messages
10. **Document new features** - Update README

---

## 🎯 File Structure Summary

```
telegram_bot_template/
├── main.py              # Entry point (register handlers)
├── config.py            # Configuration
├── requirements.txt     # Dependencies
├── .env.example         # Environment template
├── buildpublish.py      # Build & deploy script
├── handlers/            # Command/message handlers
│   ├── start.py         # /start command
│   ├── help.py          # /help command
│   └── message.py       # Text message handler
├── services/            # Business logic
│   ├── api_client.py    # External API calls
│   └── ai_logic.py      # Core bot intelligence
├── core/                # Core infrastructure
│   └── database.py      # PostgreSQL connection
├── models/              # Database models
│   └── user.py          # User model
├── routes/              # FastAPI routes (optional)
│   └── auth.py          # Auth endpoints
├── utils/               # Utilities
│   └── logger.py        # Logging setup
└── agent/               # AI guide (this folder)
    └── README.md          # This file
```

---

## 🚀 Deployment Flow

```
1. Template copied to project directory
2. .env injected (BOT_TOKEN, DATABASE_URL, WEBHOOK_URL)
3. Dependencies installed
4. PM2 started
5. Nginx configured (webhook routing)
6. DNS provisioned (optional)
7. Webhook registered
8. Bot verified (health check)
9. AI enhancement (optional)
10. PM2 restarted with enhanced code
11. Final verification
```

---

## 📝 License

MIT
