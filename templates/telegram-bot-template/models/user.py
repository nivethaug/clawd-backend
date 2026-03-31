"""
User model for Telegram bot backend.
Supports both Telegram users and email-based users.
"""
from sqlalchemy import Column, Integer, String, BigInteger, TIMESTAMP, text
from core.database import Base


class User(Base):
    """
    Telegram user model.
    Users are identified by their Telegram user ID.
    """
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Email (optional, for notifications)
    email = Column(String(255), unique=True, index=True, nullable=True)
    
    # Telegram identity
    telegram_user_id = Column(BigInteger, unique=True, nullable=True, index=True)
    telegram_chat_id = Column(BigInteger, nullable=True)
    telegram_username = Column(String(255), nullable=True)
    
    # Timestamps
    created_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"))
    updated_at = Column(TIMESTAMP, server_default=text("CURRENT_TIMESTAMP"), onupdate=text("CURRENT_TIMESTAMP"))
    
    def __repr__(self):
        if self.telegram_user_id:
            return f"<User(id={self.id}, telegram_id={self.telegram_user_id})>"
        return f"<User(id={self.id}, email='{self.email}')>"
