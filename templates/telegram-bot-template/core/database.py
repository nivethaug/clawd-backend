"""
Database configuration for Telegram bot backend.
Follows same architecture as website backend.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from utils.logger import logger

# Get database URL from environment (optional)
DATABASE_URL = os.getenv("DATABASE_URL")

# Database is optional - only create engine if URL is provided
engine = None
SessionLocal = None

if DATABASE_URL:
    try:
        # Create engine with connection pooling
        engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10
        )

        # Create session factory
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        logger.info("✅ Database connection initialized")
    except Exception as e:
        logger.warning(f"⚠️ Database initialization failed: {e}")
        logger.warning("Bot will run without database (user context unavailable)")
else:
    logger.info("ℹ️ No DATABASE_URL configured - running without database")

# Base class for models
Base = declarative_base()


def get_db():
    """Get database session (optional)."""
    if not SessionLocal:
        # Database not configured - return None
        yield None
    else:
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()


def init_db():
    """Initialize database tables (optional)."""
    if not engine:
        logger.info("ℹ️ Database initialization skipped (no DATABASE_URL)")
        return
    
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Database tables initialized")
    except Exception as e:
        logger.warning(f"⚠️ Database table creation failed: {e}")
