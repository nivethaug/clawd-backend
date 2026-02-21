"""
Universal Database Adapter Module
Supports both SQLite and PostgreSQL based on environment configuration.
Provides a unified interface for the application.
"""

import os
import logging

logger = logging.getLogger(__name__)

# Database type configuration
USE_POSTGRES = os.getenv("USE_POSTGRES", "true").lower() == "true"

# Import appropriate database module
if USE_POSTGRES:
    logger.info("Using PostgreSQL database backend")
    from database_postgres import (
        get_db,
        init_schema,
        is_master_database,
        validate_project_database_deletion,
        delete_project_database,
        test_connection,
        close_pool
    )
else:
    logger.info("Using SQLite database backend")
    from database import (
        get_db,
        init_schema
    )
    
    # PostgreSQL-specific functions not available in SQLite mode
    def is_master_database(db_name: str) -> bool:
        """SQLite has no master database concept."""
        logger.warning("is_master_database() not available in SQLite mode")
        return False
    
    def validate_project_database_deletion(project_name: str, db_name: str):
        """SQLite deletion always allowed (no master DB protection needed)."""
        return True, "SQLite mode - no validation required"
    
    def delete_project_database(project_name: str, force: bool = False):
        """SQLite deletion (simplified)."""
        import sqlite3
        DB_PATH = os.getenv("DB_PATH", "/root/clawd-backend/clawdbot_adapter.db")
        db_name = f"{project_name.replace('-', '_')}_db"
        
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute(f"DROP TABLE IF EXISTS {db_name}")
            conn.commit()
            conn.close()
            logger.info(f"✓ Dropped SQLite table: {db_name}")
            return {"success": True, "database": db_name}
        except Exception as e:
            logger.error(f"❌ Failed to drop SQLite table: {e}")
            return {"success": False, "error": str(e), "database": db_name}
    
    def test_connection():
        """Test SQLite connection."""
        import sqlite3
        DB_PATH = os.getenv("DB_PATH", "/root/clawd-backend/clawdbot_adapter.db")
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.execute("SELECT 1")
            conn.close()
            logger.info(f"✅ SQLite connection successful: {DB_PATH}")
            return {
                "status": "ok",
                "database": DB_PATH,
                "backend": "sqlite"
            }
        except Exception as e:
            logger.error(f"❌ SQLite connection failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "database": DB_PATH,
                "backend": "sqlite"
            }
    
    def close_pool():
        """SQLite has no connection pool."""
        logger.debug("close_pool() no-op in SQLite mode")


# Export all public functions
__all__ = [
    'get_db',
    'init_schema',
    'is_master_database',
    'validate_project_database_deletion',
    'delete_project_database',
    'test_connection',
    'close_pool',
    'USE_POSTGRES'
]


def get_database_info() -> dict:
    """
    Get current database configuration info.
    
    Returns:
        Dict with database backend and connection details
    """
    if USE_POSTGRES:
        from database_postgres import (
            DB_HOST, DB_PORT, DB_NAME, DB_USER
        )
        return {
            "backend": "postgresql",
            "host": DB_HOST,
            "port": DB_PORT,
            "database": DB_NAME,
            "user": DB_USER,
            "connection_pool": True
        }
    else:
        DB_PATH = os.getenv("DB_PATH", "/root/clawd-backend/clawdbot_adapter.db")
        return {
            "backend": "sqlite",
            "database": DB_PATH,
            "connection_pool": False
        }


def require_postgres() -> bool:
    """
    Check if PostgreSQL is required and available.
    Returns True if PostgreSQL mode is enabled, False otherwise.
    """
    if not USE_POSTGRES:
        logger.warning("PostgreSQL mode not enabled. Set USE_POSTGRES=true to enable.")
        return False
    
    try:
        result = test_connection()
        return result["status"] == "ok"
    except Exception as e:
        logger.error(f"PostgreSQL connection test failed: {e}")
        return False


def get_master_database_name() -> str:
    """
    Get the name of the master database.
    Returns empty string if SQLite mode.
    """
    if USE_POSTGRES:
        from database_postgres import DB_NAME
        return DB_NAME
    return ""
