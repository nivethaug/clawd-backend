"""
User helper functions for Telegram bot.
Handles Telegram user auto-creation and retrieval.
"""
from typing import Optional
from sqlalchemy.orm import Session
from models.user import User
from utils.logger import logger


def get_or_create_telegram_user(
    db: Session,
    telegram_user_id: int,
    telegram_chat_id: int,
    telegram_username: Optional[str] = None
) -> User:
    """
    Get existing user or create new Telegram user.
    
    Args:
        db: Database session
        telegram_user_id: Telegram user ID
        telegram_chat_id: Telegram chat ID
        telegram_username: Optional Telegram username
    
    Returns:
        User object
    """
    try:
        # Try to find existing user
        user = db.query(User).filter(
            User.telegram_user_id == telegram_user_id
        ).first()
        
        if user:
            # Update chat_id and username if changed
            if user.telegram_chat_id != telegram_chat_id:
                user.telegram_chat_id = telegram_chat_id
            if telegram_username and user.telegram_username != telegram_username:
                user.telegram_username = telegram_username
            db.commit()
            db.refresh(user)
            logger.info(f"✓ Found existing Telegram user: {telegram_user_id}")
            return user
        
        # Create new user
        new_user = User(
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            telegram_username=telegram_username
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        logger.info(f"✓ Created new Telegram user: {telegram_user_id}")
        return new_user
        
    except Exception as e:
        logger.error(f"Error creating/getting Telegram user: {e}")
        db.rollback()
        raise
