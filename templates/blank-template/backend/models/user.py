"""
User model for DreamPilot backend.
"""
from sqlalchemy import Column, Integer, String
from core.database import Base


class User(Base):
    """User model."""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    
    def __repr__(self):
        return f"<User(id={self.id}, email='{self.email}')>"
