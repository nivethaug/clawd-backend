"""
PostgreSQL Database Module for Clawd Backend.
Handles schema initialization, migrations, and database connections.
Supports PostgreSQL with connection pooling and transaction safety.
"""

import os
import psycopg2
from psycopg2 import pool, sql
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from typing import Optional, Dict, Any, List
import logging

logger = logging.getLogger(__name__)

# PostgreSQL Connection Parameters
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "dreampilot")
DB_USER = os.getenv("DB_USER", "admin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "StrongAdminPass123")

# Connection pool (for better performance)
connection_pool: Optional[pool.ThreadedConnectionPool] = None


def get_connection_pool() -> pool.ThreadedConnectionPool:
    """
    Get or create a connection pool for PostgreSQL.
    Returns a thread-safe connection pool.
    """
    global connection_pool

    if connection_pool is None:
        logger.info("Creating PostgreSQL connection pool...")
        connection_pool = pool.ThreadedConnectionPool(
            minconn=5,
            maxconn=20,
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            cursor_factory=RealDictCursor
        )
        logger.info(f"✓ Connection pool created (host={DB_HOST}, db={DB_NAME})")

    return connection_pool


@contextmanager
def get_db():
    """
    Database connection context manager.
    Yields a connection with dict-like access (RealDictCursor).
    Automatically returns connection to pool on exit.
    Uses connection pooling for better performance.
    """
    pool = get_connection_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


def init_schema():
    """
    Initialize PostgreSQL database schema with all required tables.
    Creates tables if they don't exist.
    Uses parameterized queries for SQL injection protection.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # Users table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    name TEXT,
                    password TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info("✓ Users table created/verified")

            # Project types table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS project_types (
                    id SERIAL PRIMARY KEY,
                    type TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL,
                    template_md_path TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info("✓ Project types table created/verified")

            # Seed default project types (idempotent)
            cur.execute("""
                INSERT INTO project_types (type, display_name, template_md_path)
                VALUES (%s, %s, %s)
                ON CONFLICT (type) DO NOTHING
            """, ('website', 'Website', 'templates/website.md'))
            
            cur.execute("""
                INSERT INTO project_types (type, display_name, template_md_path)
                VALUES (%s, %s, %s)
                ON CONFLICT (type) DO NOTHING
            """, ('telegrambot', 'Telegram Bot', 'templates/telegram_bot.md'))
            
            cur.execute("""
                INSERT INTO project_types (type, display_name, template_md_path)
                VALUES (%s, %s, %s)
                ON CONFLICT (type) DO NOTHING
            """, ('discordbot', 'Discord Bot', 'templates/discord_bot.md'))
            
            cur.execute("""
                INSERT INTO project_types (type, display_name, template_md_path)
                VALUES (%s, %s, %s)
                ON CONFLICT (type) DO NOTHING
            """, ('tradingbot', 'Trading Bot', 'templates/trading_bot.md'))
            
            cur.execute("""
                INSERT INTO project_types (type, display_name, template_md_path)
                VALUES (%s, %s, %s)
                ON CONFLICT (type) DO NOTHING
            """, ('scheduler', 'Scheduler', 'templates/scheduler.md'))
            
            cur.execute("""
                INSERT INTO project_types (type, display_name, template_md_path)
                VALUES (%s, %s, %s)
                ON CONFLICT (type) DO NOTHING
            """, ('custom', 'Custom', 'templates/custom.md'))
            logger.info("✓ Default project types seeded (idempotent)")

            # Projects table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    project_path TEXT NOT NULL DEFAULT '',
                    type_id INTEGER,
                    domain VARCHAR(255) NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'creating',
                    archived INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    claude_code_session_name TEXT,
                    openclaw_session_key TEXT,
                    template_id TEXT,
                    FOREIGN KEY (type_id) REFERENCES project_types(id) ON DELETE RESTRICT ON UPDATE CASCADE
                )
            """)
            logger.info("✓ Projects table created/verified")

            # Unique index on domain
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_domain ON projects(domain)
                WHERE domain IS NOT NULL AND domain != ''
            """)
            logger.info("✓ Domain unique index created/verified")

            # Sessions table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL,
                    session_key TEXT UNIQUE NOT NULL,
                    label TEXT,
                    archived INTEGER DEFAULT 0,
                    scope TEXT,
                    channel TEXT DEFAULT 'webchat',
                    agent_id TEXT DEFAULT 'main',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info("✓ Sessions table created/verified")

            # Messages table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    session_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    image TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info("✓ Messages table created/verified")

            conn.commit()
            logger.info("✅ PostgreSQL schema initialization complete")


def is_master_database(db_name: str) -> bool:
    """
    Check if a database name is the master database (protected).
    
    Args:
        db_name: Database name to check
    
    Returns:
        True if it's the master database, False otherwise
    """
    protected_names = [DB_NAME, 'dreampilot', 'defaultdb', 'postgres']
    return db_name.lower() in [name.lower() for name in protected_names]


def validate_project_database_deletion(project_name: str, db_name: str) -> tuple[bool, str]:
    """
    Validate if a project database deletion is allowed.
    
    Args:
        project_name: Name of the project
        db_name: Database name to delete
    
    Returns:
        Tuple of (is_allowed: bool, reason: str)
    """
    # Rule 1: Database name must match project pattern
    expected_db_name = f"{project_name.replace('-', '_')}_db"
    if db_name != expected_db_name:
        return False, f"Database name '{db_name}' doesn't match expected pattern '{expected_db_name}' for project '{project_name}'"
    
    # Rule 2: Database must NOT be master database
    if is_master_database(db_name):
        return False, f"Cannot delete master database '{db_name}'. Master database is protected from deletion."
    
    # Rule 3: Database must not be critical system database
    if db_name.lower() in ['information_schema', 'pg_catalog', 'template0', 'template1']:
        return False, f"Cannot delete system database '{db_name}'."
    
    return True, "Validation passed"


def delete_project_database(project_name: str, force: bool = False) -> Dict[str, Any]:
    """
    Delete a project database and user with validation and safety checks.
    
    Args:
        project_name: Name of the project
        force: Force deletion even if validation fails (DANGEROUS)
    
    Returns:
        Dict with success status and details
    """
    db_name = f"{project_name.replace('-', '_')}_db"
    db_user = f"{project_name.replace('-', '_')}_user"
    
    # Validate before deletion
    is_allowed, reason = validate_project_database_deletion(project_name, db_name)
    
    if not is_allowed and not force:
        logger.error(f"❌ Project DB deletion rejected: {reason}")
        return {
            "success": False,
            "error": reason,
            "database": db_name,
            "force_required": True
        }
    
    if force:
        logger.warning(f"⚠️ FORCE deletion requested for database: {db_name}")
    
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                # Drop user (if exists)
                try:
                    cur.execute(sql.SQL("DROP USER IF EXISTS %s"), (sql.Identifier(db_user),))
                    logger.info(f"✓ Dropped user: {db_user}")
                except Exception as e:
                    logger.warning(f"User drop warning: {e}")
                
                # Drop database (if exists)
                cur.execute(sql.SQL("DROP DATABASE IF EXISTS %s"), (sql.Identifier(db_name),))
                logger.info(f"✓ Dropped database: {db_name}")
                
                conn.commit()
                
                return {
                    "success": True,
                    "database": db_name,
                    "user": db_user,
                    "reason": reason
                }
                
    except Exception as e:
        logger.error(f"❌ Failed to delete project database: {e}")
        return {
            "success": False,
            "error": str(e),
            "database": db_name
        }


def test_connection() -> Dict[str, Any]:
    """
    Test PostgreSQL connection and return connection details.
    
    Returns:
        Dict with connection status and details
    """
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                version = cur.fetchone()
                logger.info(f"✅ PostgreSQL connection successful: {version}")
                return {
                    "status": "ok",
                    "version": version,
                    "host": DB_HOST,
                    "port": DB_PORT,
                    "database": DB_NAME
                }
    except Exception as e:
        logger.error(f"❌ PostgreSQL connection failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "host": DB_HOST,
            "port": DB_PORT,
            "database": DB_NAME
        }


def close_pool():
    """Close all connections in the pool."""
    global connection_pool
    if connection_pool:
        connection_pool.closeall()
        logger.info("✓ PostgreSQL connection pool closed")
        connection_pool = None
