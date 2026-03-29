"""
Start command handler.
Welcomes users to the bot.
"""
from core.database import SessionLocal
from utils.user_helpers import get_or_create_telegram_user


async def start(update, context):
    """Handle /start command."""
    # Extract Telegram user info
    tg_user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = tg_user.id
    username = tg_user.username
    
    # Get or create user in database
    db = SessionLocal()
    try:
        user = get_or_create_telegram_user(
            db=db,
            telegram_user_id=user_id,
            telegram_chat_id=chat_id,
            telegram_username=username
        )
        
        welcome_msg = (
            f"👋 Welcome{f' @{username}' if username else ''}!\n\n"
            f"I am your AI-powered bot.\n\n"
            f"Send me a message to get started.\n"
            f"Type /help to see what I can do."
        )
        
        await update.message.reply_text(welcome_msg)
        
    except Exception as e:
        # Fallback: show welcome without database
        from utils.logger import logger
        logger.error(f"Database error in start handler: {e}")
        
        await update.message.reply_text(
            "👋 Welcome! I am your AI-powered bot.\n\n"
            "Send me a message to get started.\n"
            "Type /help to see what I can do."
        )
        
    finally:
        db.close()
