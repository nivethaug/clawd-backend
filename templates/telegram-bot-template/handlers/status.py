"""
Status command handler.
Routes /status to AI logic layer for dynamic status messages.
"""
from core.database import SessionLocal
from utils.user_helpers import get_or_create_telegram_user
from services.ai_logic import process_user_input


async def status(update, context):
    """Handle /status command - routes through ai_logic.py for customization."""
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
            logger.error(f"Database error in status handler: {e}")
    
    # Route through ai_logic.py for customizable status message
    try:
        response = process_user_input("/status", user)
        await update.message.reply_text(response)
    except Exception as e:
        from utils.logger import logger
        logger.error(f"Error sending status: {e}")
        # Fallback to basic status if ai_logic fails
        import datetime
        await update.message.reply_text(
            f"✅ Bot Status\n\n"
            f"🟢 Status: Online\n"
            f"🕐 Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
    finally:
        if db:
            db.close()
