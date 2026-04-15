import os
import psycopg2
from psycopg2 import pool, sql
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

# Use RealDictCursor (dict-like rows) for SQLite compatibility
# This makes psycopg2 behave like SQLite's Row factory
USE_DICT_CURSOR = os.getenv("USE_DICT_CURSOR", "true").lower() == "true"


def get_connection_pool() -> pool.ThreadedConnectionPool:
    """
    Get or create a connection pool for PostgreSQL.
    Returns a thread-safe connection pool.
    """
    global connection_pool

    if connection_pool is None:
        logger.info("Creating PostgreSQL connection pool...")
        
        # Set cursor_factory based on environment
        cursor_factory = None
        if USE_DICT_CURSOR:
            try:
                from psycopg2.extras import RealDictCursor as _RealDictCursor
                cursor_factory = _RealDictCursor
                logger.info("✓ Using RealDictCursor for dict-like rows")
            except ImportError:
                logger.warning("RealDictCursor not available, using standard cursor")
                cursor_factory = None
        
        connection_pool = pool.ThreadedConnectionPool(
            minconn=5,
            maxconn=50,  # Increased from 20 to handle concurrent operations
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            cursor_factory=cursor_factory,
            connect_timeout=5  # Prevent hanging on unreachable database
        )
        logger.info(f"✓ Connection pool created (host={DB_HOST}, db={DB_NAME}, pool_size=50)")

    return connection_pool


class CursorAsConnection:
    """
    Wrapper to make a psycopg2 cursor behave like a SQLite connection.
    This allows app.py code to use conn.execute() without modification.
    """
    def __init__(self, cursor, connection):
        self._cursor = cursor
        self._connection = connection
        self.closed = False

    def execute(self, query, params=None):
        """
        Execute query through cursor and return self for chaining.
        Converts SQLite-style '?' placeholders to PostgreSQL '%s'.
        """
        # Convert SQLite-style ? placeholders to PostgreSQL %s
        postgres_query = query.replace('?', '%s')
        if query != postgres_query:
            logger.debug(f"Converted query placeholders: '?' → '%s'")
        self._cursor.execute(postgres_query, params or ())
        return self

    def executemany(self, query, params):
        """
        Execute many queries through cursor.
        Converts SQLite-style '?' placeholders to PostgreSQL '%s'.
        """
        # Convert SQLite-style ? placeholders to PostgreSQL %s
        postgres_query = query.replace('?', '%s')
        return self._cursor.executemany(postgres_query, params)

    def fetchall(self):
        """Fetch all results."""
        return self._cursor.fetchall()

    def fetchone(self):
        """Fetch one result."""
        return self._cursor.fetchone()

    def fetchmany(self, size=1):
        """Fetch many results."""
        return self._cursor.fetchmany(size)

    def commit(self):
        """Commit transaction."""
        return self._connection.commit()

    def rollback(self):
        """Rollback transaction."""
        return self._connection.rollback()

    def cursor(self):
        """Return the underlying cursor (for cursor operations)."""
        return self._cursor

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if exc_type is None:
            self._connection.commit()
        else:
            self._connection.rollback()
        self.closed = True


@contextmanager
def get_db():
    """
    Database connection context manager.
    Yields a cursor-as-connection wrapper for SQLite compatibility.
    Automatically returns connection to pool on exit.
    Uses connection pooling for better performance.

    Note: Uses CursorAsConnection wrapper to make psycopg2 cursor
    behave like SQLite connection (execute(), fetchall(), etc.).
    """
    pool = get_connection_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            yield CursorAsConnection(cur, conn)
    finally:
        pool.putconn(conn)


def init_schema():
    """
    Initialize database schema with all required tables and migrations.
    Creates tables if they don't exist, runs migrations for missing columns.
    Uses direct cursor/connection access for schema operations.
    """
    pool = get_connection_pool()
    conn = pool.getconn()
    try:
        def _run_migration(migration_fn):
            """Helper to run migrations safely with rollback on error."""
            try:
                migration_fn()
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.debug(f"Migration failed (expected if already exists): {e}")

        with conn.cursor() as cur:
            # Users table
            cur.execute("""CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email TEXT UNIQUE,
                name TEXT,
                password TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            conn.commit()

            # Users table migrations (each in its own transaction)
            def migrate_email():
                cur.execute("ALTER TABLE users ADD COLUMN email TEXT")
            _run_migration(migrate_email)

            def migrate_password():
                cur.execute("ALTER TABLE users ADD COLUMN password TEXT")
            _run_migration(migrate_password)

            # Project types table
            cur.execute("""CREATE TABLE IF NOT EXISTS project_types (
                id SERIAL PRIMARY KEY,
                type TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                template_md_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            conn.commit()

            # Seed default project types
            default_types = [
                ('website', 'Website', 'templates/website.md'),
                ('telegrambot', 'Telegram Bot', 'templates/telegram_bot.md'),
                ('discordbot', 'Discord Bot', 'templates/discord_bot.md'),
                ('tradingbot', 'Trading Bot', 'templates/trading_bot.md'),
                ('scheduler', 'Scheduler', 'templates/scheduler.md'),
                ('custom', 'Custom', 'templates/custom.md'),
            ]
            
            for type_slug, display_name, template_path in default_types:
                cur.execute(
                    "INSERT INTO project_types (type, display_name, template_md_path) VALUES (%s, %s, %s) ON CONFLICT (type) DO NOTHING",
                    (type_slug, display_name, template_path)
                )
            conn.commit()

            # Projects table
            cur.execute("""CREATE TABLE IF NOT EXISTS projects (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                project_path TEXT NOT NULL DEFAULT '',
                type_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (type_id) REFERENCES project_types(id) ON DELETE RESTRICT ON UPDATE CASCADE
            )""")
            conn.commit()

            # Projects table migrations (each in its own transaction)
            def migrate_description():
                cur.execute("ALTER TABLE projects ADD COLUMN description TEXT")
            _run_migration(migrate_description)

            def migrate_project_path():
                cur.execute("ALTER TABLE projects ADD COLUMN project_path TEXT NOT NULL DEFAULT ''")
            _run_migration(migrate_project_path)

            def migrate_type_id():
                cur.execute("ALTER TABLE projects ADD COLUMN type_id INTEGER")
            _run_migration(migrate_type_id)

            def migrate_domain():
                cur.execute("ALTER TABLE projects ADD COLUMN domain VARCHAR(255) NOT NULL DEFAULT ''")
                cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_domain ON projects(domain)")
                logger.info("✓ Added domain column and unique index")
            _run_migration(migrate_domain)

            def migrate_status():
                cur.execute("ALTER TABLE projects ADD COLUMN status TEXT NOT NULL DEFAULT 'creating'")
                logger.info("✓ Added status column with default 'creating'")
            _run_migration(migrate_status)

            def migrate_openclaw_session_key():
                cur.execute("ALTER TABLE projects ADD COLUMN openclaw_session_key TEXT")
                logger.info("✓ Added openclaw_session_key column")
            _run_migration(migrate_openclaw_session_key)

            def rename_claude_code_session_name():
                cur.execute("ALTER TABLE projects RENAME COLUMN openclaw_session_key TO claude_code_session_name")
                logger.info("✓ Renamed column to claude_code_session_name")
            _run_migration(rename_claude_code_session_name)

            def migrate_backend_port():
                cur.execute("ALTER TABLE projects ADD COLUMN backend_port INTEGER")
                logger.info("✓ Added backend_port column for dynamic port allocation")
            _run_migration(migrate_backend_port)

            def migrate_pipeline_status():
                cur.execute("ALTER TABLE projects ADD COLUMN pipeline_status JSONB DEFAULT '{}'::jsonb")
                logger.info("✓ Added pipeline_status column for structured progress tracking")
            _run_migration(migrate_pipeline_status)

            def migrate_error_code():
                cur.execute("ALTER TABLE projects ADD COLUMN error_code VARCHAR(100)")
                logger.info("✓ Added error_code column for detailed failure reasons")
            _run_migration(migrate_error_code)

            def migrate_repo_url():
                cur.execute("ALTER TABLE projects ADD COLUMN repo_url TEXT")
                logger.info("✓ Added repo_url column for GitHub repository URL")
            _run_migration(migrate_repo_url)

            def migrate_active_session_id():
                cur.execute("ALTER TABLE projects ADD COLUMN active_session_id INTEGER")
                logger.info("✓ Added active_session_id column for session locking")
            _run_migration(migrate_active_session_id)

            # Sessions table
            cur.execute("""CREATE TABLE IF NOT EXISTS sessions (
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
            )""")
            conn.commit()

            # Messages table
            cur.execute("""CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                session_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                image TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            conn.commit()

            # Messages table migration
            def migrate_image():
                cur.execute("ALTER TABLE messages ADD COLUMN image TEXT")
            _run_migration(migrate_image)

            # Messages table migration: add mode column
            def migrate_mode():
                cur.execute("ALTER TABLE messages ADD COLUMN mode VARCHAR(20) DEFAULT 'dream'")
                logger.info("✓ Added mode column to messages table")
            _run_migration(migrate_mode)

            # Messages table migration: add commit tracking columns
            def migrate_commit_tracking():
                cur.execute("ALTER TABLE messages ADD COLUMN commit_hash VARCHAR(40)")
                cur.execute("ALTER TABLE messages ADD COLUMN commit_status VARCHAR(20) DEFAULT 'pending'")
                cur.execute("ALTER TABLE messages ADD COLUMN reverted_message_id INTEGER REFERENCES messages(id) ON DELETE SET NULL")
                logger.info("✓ Added commit tracking columns to messages table")
            _run_migration(migrate_commit_tracking)

            # Plans table
            cur.execute("""CREATE TABLE IF NOT EXISTS plans (
                id SERIAL PRIMARY KEY,
                session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                file_path TEXT NOT NULL,
                title TEXT,
                status VARCHAR(20) DEFAULT 'draft',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_at TIMESTAMP,
                executed_at TIMESTAMP
            )""")
            conn.commit()
            logger.info("✓ Created plans table")

            # AI Sessions table (for AI chat system)
            # active_project_id stores project domain (TEXT), not numeric ID
            cur.execute("""CREATE TABLE IF NOT EXISTS ai_sessions (
                id SERIAL PRIMARY KEY,
                session_key TEXT UNIQUE NOT NULL,
                active_project_id TEXT,
                pending_intent JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            conn.commit()
            
            # AI Sessions indexes
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_sessions_session_key ON ai_sessions(session_key)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_sessions_active_project_id ON ai_sessions(active_project_id)")
            conn.commit()
            logger.info("✓ Added ai_sessions table with indexes")

            # Migration: Change active_project_id from INTEGER to TEXT (domain-based)
            def migrate_ai_sessions_domain():
                """Migrate ai_sessions.active_project_id from INTEGER to TEXT."""
                # Check current column type
                cur.execute("""
                    SELECT data_type 
                    FROM information_schema.columns 
                    WHERE table_name = 'ai_sessions' 
                    AND column_name = 'active_project_id'
                """)
                result = cur.fetchone()
                
                if not result:
                    logger.warning("⚠️ Column active_project_id not found in ai_sessions")
                    return
                
                # Handle both RealDictCursor (dict) and regular cursor (tuple)
                if isinstance(result, dict):
                    current_type = result['data_type']
                else:
                    current_type = result[0]
                
                logger.info(f"🔍 ai_sessions.active_project_id current type: {current_type}")
                
                if current_type == 'integer':
                    logger.info("🔄 Migrating ai_sessions.active_project_id from INTEGER to TEXT...")
                    
                    # Create temporary column
                    cur.execute("ALTER TABLE ai_sessions ADD COLUMN IF NOT EXISTS active_project_domain TEXT")
                    conn.commit()
                    
                    # Migrate data: INTEGER ID → domain string
                    cur.execute("""
                        UPDATE ai_sessions s
                        SET active_project_domain = p.domain
                        FROM projects p
                        WHERE s.active_project_id = p.id
                        AND s.active_project_id IS NOT NULL
                    """)
                    migrated_count = cur.rowcount
                    conn.commit()
                    
                    # Drop old column
                    cur.execute("ALTER TABLE ai_sessions DROP COLUMN active_project_id")
                    conn.commit()
                    
                    # Rename temp column
                    cur.execute("ALTER TABLE ai_sessions RENAME COLUMN active_project_domain TO active_project_id")
                    conn.commit()
                    
                    # Recreate index
                    cur.execute("DROP INDEX IF EXISTS idx_ai_sessions_active_project_id")
                    cur.execute("CREATE INDEX idx_ai_sessions_active_project_id ON ai_sessions(active_project_id)")
                    conn.commit()
                    
                    logger.info(f"✅ Migrated {migrated_count} sessions from INTEGER to TEXT (domain-based)")
                else:
                    logger.info("✓ ai_sessions.active_project_id already TEXT (migration not needed)")
            
            _run_migration(migrate_ai_sessions_domain)

            # Scheduler Jobs table (centralized, ALL scheduler projects)
            cur.execute("""CREATE TABLE IF NOT EXISTS scheduler_jobs (
                id SERIAL PRIMARY KEY,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                job_type VARCHAR(20) CHECK (job_type IN ('interval', 'daily', 'once')),
                schedule_value VARCHAR(100) NOT NULL,
                task_type VARCHAR(50) NOT NULL,
                payload JSONB DEFAULT '{}',
                last_run TIMESTAMP,
                next_run TIMESTAMP,
                status VARCHAR(20) DEFAULT 'active',
                created_at TIMESTAMP DEFAULT NOW()
            )""")
            conn.commit()

            # Scheduler jobs indexes
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_scheduler_jobs_due
                ON scheduler_jobs (status, next_run)
                WHERE status = 'active'
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_scheduler_jobs_project
                ON scheduler_jobs (project_id, status)
            """)
            conn.commit()

            # Scheduler Logs table
            cur.execute("""CREATE TABLE IF NOT EXISTS scheduler_logs (
                id SERIAL PRIMARY KEY,
                job_id INTEGER REFERENCES scheduler_jobs(id) ON DELETE CASCADE,
                status VARCHAR(20) CHECK (status IN ('success', 'failed')),
                message TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )""")
            conn.commit()

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_scheduler_logs_job
                ON scheduler_logs (job_id, created_at DESC)
            """)
            conn.commit()

            logger.info("✓ Added scheduler_jobs and scheduler_logs tables")

            logger.info("✓ Database schema initialized")
    finally:
        pool.putconn(conn)


def is_master_database(db_name: str) -> bool:
    """
    Check if a database name is master database (protected).
    
    Args:
        db_name: Database name to check
    
    Returns:
        True if it's master database, False otherwise
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
    
    conn = None
    try:
        pool = get_connection_pool()
        
        # Log pool status before getting connection
        logger.debug(f"Pool status before getconn: used={len(pool._used)}, idle={len(pool._pool)}")
        
        conn = pool.getconn()
        
        # CRITICAL: Set autocommit FIRST, before any statements
        # DROP DATABASE requires autocommit mode (cannot run in transaction)
        # Setting autocommit after executing statements causes "set_session cannot be used inside a transaction"
        conn.autocommit = True
        
        with conn.cursor() as cur:
            # Drop user (if exists) - use sql.SQL().format() for proper identifier handling
            try:
                drop_user_sql = sql.SQL("DROP USER IF EXISTS {}").format(sql.Identifier(db_user))
                cur.execute(drop_user_sql)
                logger.info(f"✓ Dropped user: {db_user}")
            except Exception as e:
                logger.warning(f"User drop warning: {e}")
            
            # Drop database (if exists)
            try:
                drop_db_sql = sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db_name))
                cur.execute(drop_db_sql)
                logger.info(f"✓ Dropped database: {db_name}")
            except Exception as e:
                logger.error(f"Database drop error: {e}")
                raise
            
            # Log pool status after operation
            logger.debug(f"Pool status after DROP: used={len(pool._used)}, idle={len(pool._pool)}")
                
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
    finally:
        # CRITICAL: Always return connection to pool to prevent leaks
        if conn:
            try:
                pool.putconn(conn)
                logger.debug(f"✓ Connection returned to pool (pool status: used={len(pool._used)}, idle={len(pool._pool)})")
            except Exception as e:
                logger.error(f"❌ Failed to return connection to pool: {e}")


def get_pool_status() -> Dict[str, Any]:
    """
    Get connection pool status for monitoring.
    
    Returns:
        Dict with pool statistics
    """
    try:
        pool = get_connection_pool()
        return {
            "status": "ok",
            "pool_size": 50,
            "used_connections": len(pool._used),
            "idle_connections": len(pool._pool),
            "available": len(pool._pool),
            "utilization": f"{(len(pool._used) / 50) * 100:.1f}%"
        }
    except Exception as e:
        logger.error(f"Failed to get pool status: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


def test_connection() -> Dict[str, Any]:
    """
    Test PostgreSQL connection and return connection details.

    Returns:
        Dict with connection status and details
    """
    try:
        with get_db() as cur:
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
    """Close all connections in pool."""
    global connection_pool
    if connection_pool:
        connection_pool.closeall()
        logger.info("✓ PostgreSQL connection pool closed")
        connection_pool = None
