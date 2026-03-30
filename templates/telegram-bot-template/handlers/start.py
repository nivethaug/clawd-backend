"""
Start command handler.
Routes /start to AI logic layer for dynamic welcome messages.
"""
from core.database import SessionLocal
from utils.user_helpers import get_or_create_telegram_user
from services.ai_logic import process_user_input
from models.user import User


async def start(update, context):
    """Handle /start command - routes through ai_logic.py for customization."""
    # Extract Telegram user info
    tg_user = update.effective_user
    chat_id = update.effective_chat.id
    user_id = tg_user.id
    username = tg_user.username
    
    # Get or create user in database (if available)
    db = None
    user = None
    
    if SessionLocal:
        try:
            db = SessionLocal()
            user = get_or_create_telegram_user(
                db=db,
                telegram_user_id=user_id,
                telegram_chat_id=chat_id,
                telegram_username=username
            )
        except Exception as e:
            # Database error - continue without user context
            from utils.logger import logger
            logger.error(f"Database error in start handler: {e}")
    
    # Route through ai_logic.py for customizable welcome message
    try:
        response = process_user_input("/start", user)
        await update.message.reply_text(response)
    except Exception as e:
        from utils.logger import logger
        logger.error(f"Error sending welcome: {e}")
        # Fallback to basic welcome if ai_logic fails
        await update.message.reply_text(
            f"👋 Welcome{f' @{username}' if username else ''}!\n\n"
            f"Type /help to see what I can do."
        )
    finally:
        if db:
            db.close()
