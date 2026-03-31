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
    """
    Get database session (optional).
    
    Yields:
        Session or None: Database session if configured, None otherwise
    
    Note:
        Routes and handlers should check if db is None and handle accordingly.
        This allows the bot to run without a database for simple use cases.
    """
    if not SessionLocal:
        # Database not configured - yield None
        yield None
    else:
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()


def init_db():
    """Initialize database tables and run migrations (optional)."""
    if not engine:
        logger.info("ℹ️ Database initialization skipped (no DATABASE_URL)")
        return
    
    try:
        # First, run migrations to add missing columns
        _run_migrations()
        
        # Then create any missing tables
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Database tables initialized")
    except Exception as e:
        logger.warning(f"⚠️ Database table creation failed: {e}")


def _run_migrations():
    """Run database migrations to add missing columns."""
    from sqlalchemy import text
    
    migrations = [
        # Add telegram columns to users table if they don't exist
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_user_id BIGINT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_chat_id BIGINT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_username VARCHAR(255)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        # Make email nullable for Telegram-only users
        "ALTER TABLE users ALTER COLUMN email DROP NOT NULL",
        # Remove unique constraint from email (allows multiple NULL values)
        "ALTER TABLE users DROP CONSTRAINT IF EXISTS users_email_key",
    ]
    
    with engine.connect() as conn:
        for migration in migrations:
            try:
                conn.execute(text(migration))
                conn.commit()
            except Exception as e:
                # Column might already exist, that's okay
                if "already exists" not in str(e).lower() and "duplicate" not in str(e).lower():
                    logger.warning(f"Migration warning: {e}")
        
        # Create indexes for telegram columns
        index_migrations = [
            "CREATE INDEX IF NOT EXISTS idx_users_telegram_user_id ON users(telegram_user_id)",
        ]
        
        for migration in index_migrations:
            try:
                conn.execute(text(migration))
                conn.commit()
            except Exception as e:
                logger.warning(f"Index creation warning: {e}")
    
    logger.info("✅ Database migrations completed")
