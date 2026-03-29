"""
Message handler.
Routes all text messages to AI logic layer.
"""
from core.database import SessionLocal
from models.user import User
from utils.user_helpers import get_or_create_telegram_user
from services.ai_logic import process_user_input


async def handle_message(update, context):
    """Handle incoming text messages."""
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
        
        # Process message with user context
        user_input = update.message.text
        response = process_user_input(user_input, user)
        
        await update.message.reply_text(response)
        
    except Exception as e:
        # Fallback: process without user context if database fails
        from utils.logger import logger
        logger.error(f"Database error in message handler: {e}")
        
        user_input = update.message.text
        response = process_user_input(user_input, user=None)
        await update.message.reply_text(response)
        
    finally:
        db.close()
