import os
import json
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

            def migrate_role():
                cur.execute("ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'user'")
            _run_migration(migrate_role)

            def migrate_subscription_tier():
                cur.execute(
                    "ALTER TABLE users ADD COLUMN subscription_tier VARCHAR(20) NOT NULL DEFAULT 'free'"
                )
            _run_migration(migrate_subscription_tier)

            def migrate_email_verified():
                cur.execute(
                    "ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT true"
                )
            _run_migration(migrate_email_verified)

            def migrate_verification_token():
                cur.execute(
                    "ALTER TABLE users ADD COLUMN verification_token TEXT"
                )
            _run_migration(migrate_verification_token)

            # GitHub OAuth connection columns (per-user GitHub Export feature)
            def migrate_github_username():
                cur.execute("ALTER TABLE users ADD COLUMN github_username VARCHAR(255)")
            _run_migration(migrate_github_username)

            def migrate_github_access_token():
                cur.execute("ALTER TABLE users ADD COLUMN github_access_token TEXT")
            _run_migration(migrate_github_access_token)

            def migrate_github_token_scope():
                cur.execute("ALTER TABLE users ADD COLUMN github_token_scope VARCHAR(255)")
            _run_migration(migrate_github_token_scope)

            def migrate_github_connected_at():
                cur.execute("ALTER TABLE users ADD COLUMN github_connected_at TIMESTAMP")
            _run_migration(migrate_github_connected_at)

            def migrate_github_avatar_url():
                cur.execute("ALTER TABLE users ADD COLUMN github_avatar_url TEXT")
            _run_migration(migrate_github_avatar_url)

            def migrate_active_project():
                cur.execute("ALTER TABLE users ADD COLUMN active_project TEXT")
                logger.info("✓ Added active_project column to users")
            _run_migration(migrate_active_project)

            # Telegram account linking columns
            def migrate_telegram_chat_id():
                cur.execute("ALTER TABLE users ADD COLUMN telegram_chat_id BIGINT")
            _run_migration(migrate_telegram_chat_id)

            def migrate_telegram_link_code():
                cur.execute("ALTER TABLE users ADD COLUMN telegram_link_code VARCHAR(6)")
            _run_migration(migrate_telegram_link_code)

            def migrate_telegram_link_expires():
                cur.execute("ALTER TABLE users ADD COLUMN telegram_link_expires_at TIMESTAMP")
            _run_migration(migrate_telegram_link_expires)

            # Ensure existing users have correct defaults
            try:
                cur.execute(
                    "UPDATE users SET role = 'user' WHERE role IS NULL OR role = ''"
                )
                cur.execute(
                    "UPDATE users SET subscription_tier = 'free' WHERE subscription_tier IS NULL OR subscription_tier = ''"
                )
                conn.commit()
                logger.info("✓ Ensured role and subscription_tier defaults on users")
            except Exception as e:
                conn.rollback()
                logger.debug(f"Role/tier default backfill skipped: {e}")

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

            def migrate_frontend_port():
                cur.execute("ALTER TABLE projects ADD COLUMN frontend_port INTEGER")
                logger.info("✓ Added frontend_port column for dynamic port allocation")
            _run_migration(migrate_frontend_port)

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

            # Backfill repo_url for existing projects that have a git remote but empty repo_url
            try:
                import subprocess
                projects = cur.execute(
                    "SELECT id, project_path FROM projects WHERE (repo_url IS NULL OR repo_url = '') AND project_path IS NOT NULL AND project_path != ''"
                ).fetchall()
                backfilled = 0
                for p in projects:
                    try:
                        result = subprocess.run(
                            ["git", "-C", p["project_path"], "remote", "get-url", "origin"],
                            capture_output=True, text=True, timeout=5
                        )
                        remote_url = result.stdout.strip()
                        if remote_url:
                            # Normalize SSH to HTTPS for consistency
                            if remote_url.startswith("git@github.com:"):
                                remote_url = remote_url.replace("git@github.com:", "https://github.com/").rstrip(".git")
                            elif remote_url.endswith(".git"):
                                remote_url = remote_url[:-4]
                            cur.execute("UPDATE projects SET repo_url = ? WHERE id = ?", (remote_url, p["id"]))
                            backfilled += 1
                    except Exception:
                        pass
                if backfilled:
                    conn.commit()
                    logger.info(f"✓ Backfilled repo_url for {backfilled} existing projects")
            except Exception as e:
                logger.warning(f"repo_url backfill failed: {e}")

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

            # Messages table migration: add token_usage column (JSONB for flexibility)
            def migrate_token_usage():
                cur.execute("ALTER TABLE messages ADD COLUMN token_usage JSONB")
                logger.info("✓ Added token_usage column to messages table")
            _run_migration(migrate_token_usage)

            # Commit log table — persistent commit history (survives session/message deletion)
            try:
                cur.execute("""CREATE TABLE IF NOT EXISTS commit_log (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL,
                    session_id INTEGER,
                    message_id INTEGER,
                    commit_hash VARCHAR(40) NOT NULL,
                    commit_message TEXT NOT NULL,
                    status VARCHAR(20) DEFAULT 'pushed',
                    reverted_by INTEGER REFERENCES commit_log(id) ON DELETE SET NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""")
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.warning(f"commit_log table creation failed (may already exist): {e}")
            try:
                cur.execute("CREATE INDEX IF NOT EXISTS idx_commit_log_project ON commit_log(project_id, created_at DESC)")
                conn.commit()
                logger.info("✓ Created commit_log table with index")
            except Exception as e:
                conn.rollback()
                logger.warning(f"commit_log index creation failed: {e}")

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

            # Gallery projects table — public showcase for community gallery
            # Future-ready schema: is_featured supports staff picks;
            # likes/comments/ratings/marketplace columns can be added later.
            try:
                cur.execute("""CREATE TABLE IF NOT EXISTS gallery_projects (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    frontend_url TEXT,
                    project_type INTEGER,
                    thumbnail_url TEXT,
                    is_featured BOOLEAN NOT NULL DEFAULT false,
                    view_count INTEGER NOT NULL DEFAULT 0,
                    clone_count INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    published_at TIMESTAMP,
                    status VARCHAR(20) NOT NULL DEFAULT 'public'
                )""")
                conn.commit()
                # Indexes: browse by status+recency, unique one-listing-per-project, type filter
                cur.execute("CREATE INDEX IF NOT EXISTS idx_gallery_projects_status ON gallery_projects(status, published_at DESC)")
                cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_gallery_projects_project ON gallery_projects(project_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_gallery_projects_type ON gallery_projects(project_type)")
                conn.commit()
                logger.info("✓ Created gallery_projects table with indexes")
            except Exception as e:
                conn.rollback()
                logger.warning(f"gallery_projects table creation failed (may already exist): {e}")

            # Templates table — admin-managed starter kits (like gallery but admin-curated)
            try:
                cur.execute("""CREATE TABLE IF NOT EXISTS templates (
                    id SERIAL PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'General',
                    frontend_url TEXT,
                    project_type INTEGER,
                    thumbnail_url TEXT,
                    is_featured BOOLEAN NOT NULL DEFAULT false,
                    use_count INTEGER NOT NULL DEFAULT 0,
                    view_count INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    published_at TIMESTAMP,
                    status VARCHAR(20) NOT NULL DEFAULT 'active'
                )""")
                conn.commit()
                cur.execute("CREATE INDEX IF NOT EXISTS idx_templates_status ON templates(status, published_at DESC)")
                cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_templates_project ON templates(project_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_templates_category ON templates(category)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_templates_type ON templates(project_type)")
                conn.commit()
                logger.info("✓ Created templates table with indexes")
            except Exception as e:
                conn.rollback()
                logger.warning(f"templates table creation failed (may already exist): {e}")

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

            # Token Usage table — tracks AI token consumption per user/project
            cur.execute("""CREATE TABLE IF NOT EXISTS token_usage (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                project_id INTEGER,
                session_id INTEGER,
                usage_type VARCHAR(30) NOT NULL,
                description TEXT,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                model VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            conn.commit()

            # Token usage indexes for fast queries
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_token_usage_user_date
                ON token_usage (user_id, created_at DESC)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_token_usage_project_date
                ON token_usage (project_id, created_at DESC)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_token_usage_type
                ON token_usage (usage_type, created_at DESC)
            """)
            conn.commit()
            logger.info("✓ Added token_usage table with indexes")

            # ----------------------------------------------------------------
            # projectchat table
            # Stores per-project chat messages for the global AI chat.
            # Max 10 messages per project enforced in repository layer.
            # Only last 4 sent to LLM for context.
            # ----------------------------------------------------------------
            cur.execute("""CREATE TABLE IF NOT EXISTS projectchat (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                project_domain TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                response_type TEXT,
                metadata JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            conn.commit()
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_projectchat_lookup
                ON projectchat(user_id, project_domain, created_at DESC)
            """)
            conn.commit()
            logger.info("✓ Added projectchat table with index")

            # ----------------------------------------------------------------
            # env_variable_registry table
            # Stores METADATA ONLY for known environment variables.
            # Actual runtime values remain in project .env files.
            # This enables a Vercel/Railway-style env variables UI with
            # descriptions, docs links, and categories that admins can
            # manage without code changes.
            # ----------------------------------------------------------------
            cur.execute("""CREATE TABLE IF NOT EXISTS env_variable_registry (
                id SERIAL PRIMARY KEY,
                key_name TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                docs_url TEXT,
                category VARCHAR(50) NOT NULL DEFAULT 'Custom',
                is_sensitive BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            conn.commit()
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_env_registry_category "
                "ON env_variable_registry(category)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_env_registry_key "
                "ON env_variable_registry(key_name)"
            )
            conn.commit()

            # Seed default registry entries (idempotent via ON CONFLICT)
            default_registry = [
                # key_name, title, description, docs_url, category, is_sensitive
                (
                    "OPENAI_API_KEY",
                    "OpenAI API Key",
                    "Used for OpenAI integrations and AI features.",
                    "https://platform.openai.com/api-keys",
                    "AI",
                    True,
                ),
                (
                    "ANTHROPIC_API_KEY",
                    "Anthropic API Key",
                    "Used for Anthropic Claude integrations.",
                    "https://console.anthropic.com/settings/keys",
                    "AI",
                    True,
                ),
                (
                    "GROQ_API_KEY",
                    "Groq API Key",
                    "Used for Groq inference engine integrations.",
                    "https://console.groq.com/keys",
                    "AI",
                    True,
                ),
                (
                    "SUPABASE_URL",
                    "Supabase Project URL",
                    "Used for database and authentication.",
                    "https://supabase.com/docs",
                    "Database",
                    False,
                ),
                (
                    "SUPABASE_ANON_KEY",
                    "Supabase Anon Key",
                    "Public anon key for Supabase client access.",
                    "https://supabase.com/docs/guides/api/api-keys",
                    "Database",
                    True,
                ),
                (
                    "SUPABASE_SERVICE_ROLE_KEY",
                    "Supabase Service Role Key",
                    "Server-side service role key for Supabase (full access).",
                    "https://supabase.com/docs/guides/api/api-keys",
                    "Database",
                    True,
                ),
                (
                    "STRIPE_SECRET_KEY",
                    "Stripe Secret Key",
                    "Used for payment processing.",
                    "https://dashboard.stripe.com/apikeys",
                    "Payments",
                    True,
                ),
                (
                    "STRIPE_WEBHOOK_SECRET",
                    "Stripe Webhook Secret",
                    "Used to verify Stripe webhook event signatures.",
                    "https://stripe.com/docs/webhooks/signatures",
                    "Payments",
                    True,
                ),
                (
                    "RESEND_API_KEY",
                    "Resend API Key",
                    "Used for transactional email delivery via Resend.",
                    "https://resend.com/api-keys",
                    "Email",
                    True,
                ),
                (
                    "SENDGRID_API_KEY",
                    "SendGrid API Key",
                    "Used for email delivery via SendGrid.",
                    "https://app.sendgrid.com/settings/api_keys",
                    "Email",
                    True,
                ),
                (
                    "SMTP_HOST",
                    "SMTP Host",
                    "Outgoing mail server hostname.",
                    "https://en.wikipedia.org/wiki/Simple_Mail_Transfer_Protocol",
                    "Email",
                    False,
                ),
                (
                    "SMTP_USER",
                    "SMTP Username",
                    "Username for SMTP authentication.",
                    None,
                    "Email",
                    False,
                ),
                (
                    "SMTP_PASSWORD",
                    "SMTP Password",
                    "Password for SMTP authentication.",
                    None,
                    "Email",
                    True,
                ),
                (
                    "DISCORD_TOKEN",
                    "Discord Bot Token",
                    "Used to connect and run the Discord bot.",
                    "https://discord.com/developers/applications",
                    "Bots",
                    True,
                ),
                (
                    "TELEGRAM_BOT_TOKEN",
                    "Telegram Bot Token",
                    "Used to connect and run the Telegram bot.",
                    "https://core.telegram.org/bots#how-do-i-create-a-bot",
                    "Bots",
                    True,
                ),
                (
                    "GITHUB_TOKEN",
                    "GitHub Personal Access Token",
                    "Used for GitHub API access and repository operations.",
                    "https://github.com/settings/tokens",
                    "Integrations",
                    True,
                ),
                (
                    "SENTRY_DSN",
                    "Sentry DSN",
                    "Used for error monitoring and performance tracing.",
                    "https://docs.sentry.io/product/sentry-basics/dsn-explainer/",
                    "Integrations",
                    False,
                ),
                (
                    "JWT_SECRET",
                    "JWT Secret",
                    "Secret key for signing JWT authentication tokens.",
                    None,
                    "Integrations",
                    True,
                ),
            ]
            for entry in default_registry:
                cur.execute(
                    """INSERT INTO env_variable_registry
                       (key_name, title, description, docs_url, category, is_sensitive)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (key_name) DO NOTHING""",
                    entry,
                )
            conn.commit()
            logger.info("✓ Added env_variable_registry table with seed data")

            # ----------------------------------------------------------------
            # custom_domains table
            # Maps custom customer domains (e.g. www.clientsite.com) to
            # DreamAgent website projects. One custom domain per project (v1).
            # ----------------------------------------------------------------
            cur.execute("""CREATE TABLE IF NOT EXISTS custom_domains (
                id SERIAL PRIMARY KEY,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                domain VARCHAR(255) NOT NULL UNIQUE,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                ssl_status VARCHAR(20) NOT NULL DEFAULT 'pending',
                verified_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
            conn.commit()
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_custom_domains_project "
                "ON custom_domains(project_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_custom_domains_status "
                "ON custom_domains(status)"
            )
            conn.commit()
            logger.info("✓ Added custom_domains table with indexes")

            # ================================================================
            # BILLING SYSTEM (v4) — Generic Credit Model
            # Plans, plan_credit_grants, user_credit_balances, ai_operations,
            # credit_transactions, credit_packs, subscriptions, billing_config.
            # Designed so adding future credit types (image/video/voice/api)
            # requires ONLY INSERTs — no schema changes.
            # ================================================================

            # --- billing_plans table (non-credit plan configuration) ---
            # NOTE: named billing_plans to avoid collision with the pre-existing
            # session/file plans table (line ~476) which has different columns.
            cur.execute("""CREATE TABLE IF NOT EXISTS billing_plans (
                id SERIAL PRIMARY KEY,
                slug VARCHAR(30) UNIQUE NOT NULL,
                name VARCHAR(50) NOT NULL,
                price_monthly_cents INTEGER DEFAULT 0,
                max_active_projects INTEGER DEFAULT 0,
                storage_mb INTEGER DEFAULT 0,
                bandwidth_gb INTEGER DEFAULT 0,
                deployment_limit INTEGER DEFAULT 0,
                custom_domains INTEGER DEFAULT 0,
                priority_queue INTEGER DEFAULT 0,
                premium_models BOOLEAN DEFAULT false,
                lemonsqueezy_variant_id VARCHAR(100),
                features JSONB DEFAULT '[]'::jsonb,
                active BOOLEAN DEFAULT true,
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )""")
            conn.commit()
            logger.info("✓ Added billing_plans table")

            # --- plan_credit_grants (per-plan × per-credit-type limits) ---
            cur.execute("""CREATE TABLE IF NOT EXISTS plan_credit_grants (
                id SERIAL PRIMARY KEY,
                plan_id INTEGER NOT NULL REFERENCES billing_plans(id) ON DELETE CASCADE,
                credit_type VARCHAR(30) NOT NULL,
                monthly_limit BIGINT DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(plan_id, credit_type)
            )""")
            conn.commit()
            logger.info("✓ Added plan_credit_grants table")

            # --- user_credit_balances (one row per user × credit_type) ---
            cur.execute("""CREATE TABLE IF NOT EXISTS user_credit_balances (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                credit_type VARCHAR(30) NOT NULL,
                monthly_limit BIGINT DEFAULT 0,
                used BIGINT DEFAULT 0,
                purchased BIGINT DEFAULT 0,
                reset_date DATE NOT NULL DEFAULT (DATE_TRUNC('month', NOW()) + INTERVAL '1 month')::date,
                updated_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(user_id, credit_type)
            )""")
            conn.commit()
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_ucb_lookup "
                "ON user_credit_balances(user_id, credit_type)"
            )
            conn.commit()
            logger.info("✓ Added user_credit_balances table with index")

            # --- ai_operations (configurable credit costs) ---
            cur.execute("""CREATE TABLE IF NOT EXISTS ai_operations (
                id SERIAL PRIMARY KEY,
                code VARCHAR(50) UNIQUE NOT NULL,
                name VARCHAR(100) NOT NULL,
                description TEXT,
                credit_cost INTEGER NOT NULL DEFAULT 1,
                category VARCHAR(20) NOT NULL DEFAULT 'edit',
                credit_type VARCHAR(30) NOT NULL DEFAULT 'project_ai',
                enabled BOOLEAN DEFAULT true,
                sort_order INTEGER DEFAULT 0
            )""")
            conn.commit()
            logger.info("✓ Added ai_operations table")

            # --- credit_transactions (audit ledger) ---
            cur.execute("""CREATE TABLE IF NOT EXISTS credit_transactions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                operation_id INTEGER REFERENCES ai_operations(id),
                credit_type VARCHAR(30) NOT NULL,
                project_id INTEGER,
                session_id INTEGER,
                credits INTEGER NOT NULL,
                source VARCHAR(20) NOT NULL DEFAULT 'monthly',
                status VARCHAR(20) NOT NULL DEFAULT 'reserved',
                cost_usd NUMERIC(12,6) DEFAULT 0,
                model VARCHAR(100),
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                duration_ms INTEGER DEFAULT 0,
                provider VARCHAR(50),
                created_at TIMESTAMP DEFAULT NOW()
            )""")
            conn.commit()
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_ct_user "
                "ON credit_transactions(user_id, created_at DESC)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_ct_status "
                "ON credit_transactions(status)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_ct_project "
                "ON credit_transactions(project_id, created_at DESC)"
            )
            conn.commit()
            logger.info("✓ Added credit_transactions table with indexes")

            # --- credit_packs (purchasable) ---
            cur.execute("""CREATE TABLE IF NOT EXISTS credit_packs (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                credits INTEGER NOT NULL,
                credit_type VARCHAR(30) NOT NULL DEFAULT 'project_ai',
                price_cents INTEGER NOT NULL,
                lemonsqueezy_variant_id VARCHAR(100),
                active BOOLEAN DEFAULT true,
                sort_order INTEGER DEFAULT 0
            )""")
            conn.commit()
            logger.info("✓ Added credit_packs table")

            # --- subscriptions (LemonSqueezy state) ---
            cur.execute("""CREATE TABLE IF NOT EXISTS subscriptions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                plan_id INTEGER REFERENCES billing_plans(id),
                lemonsqueezy_subscription_id VARCHAR(100) UNIQUE,
                lemonsqueezy_order_id VARCHAR(100),
                status VARCHAR(30) NOT NULL DEFAULT 'active',
                current_period_end TIMESTAMP,
                cancel_at_period_end BOOLEAN DEFAULT false,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )""")
            conn.commit()
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_subs_user "
                "ON subscriptions(user_id, status)"
            )
            conn.commit()
            logger.info("✓ Added subscriptions table with index")

            # --- billing_config (EARLY_ACCESS_MODE etc.) ---
            cur.execute("""CREATE TABLE IF NOT EXISTS billing_config (
                key VARCHAR(50) PRIMARY KEY,
                value JSONB NOT NULL,
                updated_by INTEGER REFERENCES users(id),
                updated_at TIMESTAMP DEFAULT NOW()
            )""")
            conn.commit()
            logger.info("✓ Added billing_config table")

            # ----------------------------------------------------------------
            # BILLING: migrations on existing tables
            # ----------------------------------------------------------------

            # users.plan_id (nullable; backfilled below)
            def migrate_users_plan_id():
                cur.execute("ALTER TABLE users ADD COLUMN plan_id INTEGER REFERENCES billing_plans(id)")
            _run_migration(migrate_users_plan_id)

            # project_types.ai_operation_id (nullable; backfilled below)
            def migrate_project_type_operation():
                cur.execute(
                    "ALTER TABLE project_types ADD COLUMN ai_operation_id INTEGER REFERENCES ai_operations(id)"
                )
            _run_migration(migrate_project_type_operation)

            # token_usage: add cost_usd, provider, operation, credits_charged, duration_ms
            # NOTE: admin SQL at app.py queries cost_usd which previously didn't exist (silent NULL).
            def migrate_token_usage_cost_usd():
                cur.execute("ALTER TABLE token_usage ADD COLUMN cost_usd NUMERIC(12,6) DEFAULT 0")
            _run_migration(migrate_token_usage_cost_usd)

            def migrate_token_usage_provider():
                cur.execute("ALTER TABLE token_usage ADD COLUMN provider VARCHAR(50)")
            _run_migration(migrate_token_usage_provider)

            def migrate_token_usage_operation():
                cur.execute("ALTER TABLE token_usage ADD COLUMN operation VARCHAR(50)")
            _run_migration(migrate_token_usage_operation)

            def migrate_token_usage_credits():
                cur.execute("ALTER TABLE token_usage ADD COLUMN credits_charged INTEGER DEFAULT 0")
            _run_migration(migrate_token_usage_credits)

            def migrate_token_usage_duration():
                cur.execute("ALTER TABLE token_usage ADD COLUMN duration_ms INTEGER DEFAULT 0")
            _run_migration(migrate_token_usage_duration)
            logger.info("✓ Added billing columns to token_usage")

            # ----------------------------------------------------------------
            # BILLING: fix stale FK constraints that point to old 'plans'
            # table instead of 'billing_plans' (table already existed from
            # prior runs when CREATE TABLE IF NOT EXISTS was a no-op)
            # ----------------------------------------------------------------
            def fix_fk_plan_credit_grants():
                cur.execute(
                    "ALTER TABLE plan_credit_grants "
                    "DROP CONSTRAINT IF EXISTS plan_credit_grants_plan_id_fkey"
                )
                cur.execute(
                    "ALTER TABLE plan_credit_grants "
                    "ADD CONSTRAINT plan_credit_grants_plan_id_fkey "
                    "FOREIGN KEY (plan_id) REFERENCES billing_plans(id) ON DELETE CASCADE"
                )
            _run_migration(fix_fk_plan_credit_grants)

            def fix_fk_subscriptions():
                cur.execute(
                    "ALTER TABLE subscriptions "
                    "DROP CONSTRAINT IF EXISTS subscriptions_plan_id_fkey"
                )
                cur.execute(
                    "ALTER TABLE subscriptions "
                    "ADD CONSTRAINT subscriptions_plan_id_fkey "
                    "FOREIGN KEY (plan_id) REFERENCES billing_plans(id)"
                )
            _run_migration(fix_fk_subscriptions)

            def fix_fk_users_plan_id():
                cur.execute(
                    "ALTER TABLE users "
                    "DROP CONSTRAINT IF EXISTS users_plan_id_fkey"
                )
                cur.execute(
                    "ALTER TABLE users "
                    "ADD CONSTRAINT users_plan_id_fkey "
                    "FOREIGN KEY (plan_id) REFERENCES billing_plans(id)"
                )
            _run_migration(fix_fk_users_plan_id)
            logger.info("✓ Fixed billing FK constraints to reference billing_plans")

            # ----------------------------------------------------------------
            # BILLING: seed data (defaults only — admin-editable)
            # ----------------------------------------------------------------

            # Seed plans
            seed_plans = [
                ('free', 'Free', 0, 3, 0, 0, 0, 0, 0, 0, False, 0,
                 json.dumps(["Unlimited Prompt Assistant", "Unlimited DevOps Assistant",
                             "Community Templates", "Community Gallery", "GitHub Export", "ZIP Download"])),
                ('pro', 'Pro', 3900, 30, 0, 0, 0, 0, 1, 1, True, 10,
                 json.dumps(["Premium Models", "Priority Queue", "Premium Templates",
                             "Unlimited Deployments", "Custom Domains", "Premium Support"])),
                ('dream', 'Dream', 9900, 100, 0, 0, 0, 0, 2, 2, True, 20,
                 json.dumps(["Premium Models", "Fastest Queue", "Premium Support",
                             "Custom Domains", "Unlimited Deployments"])),
                ('enterprise', 'Enterprise', 0, 0, 0, 0, 0, 0, 3, 3, True, 30,
                 json.dumps(["Unlimited Active Projects", "Dedicated VPS", "Self Hosted",
                             "Team Workspace", "White Label", "Dedicated Infrastructure", "Contact Sales"])),
            ]
            for slug, name, price, max_proj, stor, bw, dep, dom, prio, sort, premium, sort_o, feats in seed_plans:
                cur.execute(
                    """INSERT INTO billing_plans (slug, name, price_monthly_cents, max_active_projects,
                        storage_mb, bandwidth_gb, deployment_limit, custom_domains,
                        priority_queue, premium_models, sort_order, features)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (slug) DO NOTHING""",
                    (slug, name, price, max_proj, stor, bw, dep, dom, prio, premium, sort_o, feats)
                )
            conn.commit()
            logger.info("✓ Seeded billing_plans")

            # Seed plan_credit_grants
            cur.execute("SELECT id, slug FROM billing_plans")
            plan_map = {row["slug"]: row["id"] for row in cur.fetchall()}
            seed_grants = [
                ('free', 'project_ai', 50),
                ('free', 'edit_token', 2000000),
                ('pro', 'project_ai', 1000),
                ('pro', 'edit_token', 25000000),
                ('dream', 'project_ai', 5000),
                ('dream', 'edit_token', 100000000),
                ('enterprise', 'project_ai', 0),
                ('enterprise', 'edit_token', 0),
            ]
            for slug, ctype, limit in seed_grants:
                pid = plan_map.get(slug)
                if pid:
                    cur.execute(
                        """INSERT INTO plan_credit_grants (plan_id, credit_type, monthly_limit)
                           VALUES (%s, %s, %s)
                           ON CONFLICT (plan_id, credit_type) DO NOTHING""",
                        (pid, ctype, limit)
                    )
            conn.commit()
            logger.info("✓ Seeded plan_credit_grants")

            # Seed ai_operations
            seed_ops = [
                ('WEBSITE', 'Website Creation', 'Generate a complete website', 10, 'creation', 'project_ai', 1),
                ('LANDING_PAGE', 'Landing Page', 'Generate a landing page', 10, 'creation', 'project_ai', 2),
                ('DASHBOARD', 'Dashboard', 'Generate a dashboard application', 8, 'creation', 'project_ai', 3),
                ('DISCORD_BOT', 'Discord Bot', 'Generate a Discord bot', 8, 'creation', 'project_ai', 4),
                ('TELEGRAM_BOT', 'Telegram Bot', 'Generate a Telegram bot', 8, 'creation', 'project_ai', 5),
                ('AUTOMATION', 'Automation Project', 'Generate an automation/scheduler project', 6, 'creation', 'project_ai', 6),
                ('SCHEDULER', 'Scheduler', 'Generate a scheduler project', 6, 'creation', 'project_ai', 7),
                ('API_GENERATION', 'API Generation', 'Generate an API', 5, 'creation', 'project_ai', 8),
                ('LARGE_REFACTOR', 'Large Refactor', 'Large-scale refactoring', 5, 'edit', 'project_ai', 20),
                ('REFACTOR', 'Refactor', 'Refactor existing code', 3, 'edit', 'project_ai', 21),
                ('ADD_FEATURE', 'Add Feature', 'Add a new feature', 2, 'edit', 'project_ai', 22),
                ('BUG_FIX', 'Bug Fix', 'Fix a bug', 1, 'edit', 'project_ai', 23),
                ('UI_EDIT', 'UI Edit', 'Edit UI components', 1, 'edit', 'project_ai', 24),
            ]
            for code, name, desc, cost, cat, ctype, sort in seed_ops:
                cur.execute(
                    """INSERT INTO ai_operations (code, name, description, credit_cost, category, credit_type, sort_order)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (code) DO NOTHING""",
                    (code, name, desc, cost, cat, ctype, sort)
                )
            conn.commit()
            logger.info("✓ Seeded ai_operations")

            # Seed credit_packs
            seed_packs = [
                ('100 AI Credits', 100, 'project_ai', 500, 1),
                ('500 AI Credits', 500, 'project_ai', 2000, 2),
                ('1000 AI Credits', 1000, 'project_ai', 3500, 3),
            ]
            for name, credits, ctype, price, sort in seed_packs:
                cur.execute(
                    """INSERT INTO credit_packs (name, credits, credit_type, price_cents, sort_order)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT DO NOTHING""",
                    (name, credits, ctype, price, sort)
                )
            conn.commit()
            logger.info("✓ Seeded credit_packs")

            # Seed billing_config
            cur.execute(
                """INSERT INTO billing_config (key, value)
                   VALUES ('EARLY_ACCESS_MODE', 'true'::jsonb)
                   ON CONFLICT (key) DO NOTHING"""
            )
            conn.commit()
            logger.info("✓ Seeded billing_config (EARLY_ACCESS_MODE)")

            # Backfill project_types.ai_operation_id
            type_to_op = {
                'website': 'WEBSITE',
                'telegrambot': 'TELEGRAM_BOT',
                'discordbot': 'DISCORD_BOT',
                'scheduler': 'AUTOMATION',
                'tradingbot': 'WEBSITE',
                'custom': 'WEBSITE',
            }
            cur.execute("SELECT id, code FROM ai_operations")
            op_map = {row["code"]: row["id"] for row in cur.fetchall()}
            for type_slug, op_code in type_to_op.items():
                op_id = op_map.get(op_code)
                if op_id:
                    cur.execute(
                        """UPDATE project_types SET ai_operation_id = %s
                           WHERE type = %s AND ai_operation_id IS NULL""",
                        (op_id, type_slug)
                    )
            conn.commit()
            logger.info("✓ Backfilled project_types.ai_operation_id")

            # Backfill users.plan_id (slug join — zero remapping)
            try:
                cur.execute(
                    """UPDATE users SET plan_id = (
                           SELECT p.id FROM billing_plans p WHERE p.slug = users.subscription_tier
                       ) WHERE plan_id IS NULL"""
                )
                conn.commit()
                logger.info("✓ Backfilled users.plan_id from subscription_tier")
            except Exception as e:
                conn.rollback()
                logger.warning(f"users.plan_id backfill skipped: {e}")

            # Backfill user_credit_balances for existing users
            try:
                # Create project_ai + edit_token balance rows for every user,
                # copying monthly_limit from their plan's grants.
                cur.execute(
                    """INSERT INTO user_credit_balances (user_id, credit_type, monthly_limit, used, purchased, reset_date)
                       SELECT u.id, g.credit_type, g.monthly_limit, 0, 0,
                              (DATE_TRUNC('month', NOW()) + INTERVAL '1 month')::date
                       FROM users u
                       JOIN billing_plans p ON u.plan_id = p.id
                       JOIN plan_credit_grants g ON g.plan_id = p.id
                       WHERE NOT EXISTS (
                           SELECT 1 FROM user_credit_balances b
                           WHERE b.user_id = u.id AND b.credit_type = g.credit_type
                       )"""
                )
                conn.commit()
                logger.info("✓ Backfilled user_credit_balances for existing users")
            except Exception as e:
                conn.rollback()
                logger.warning(f"user_credit_balances backfill skipped: {e}")

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
            # CRITICAL: Drop DATABASE first, then USER.
            # If we drop user first, it fails because the user owns objects in the database.
            # Dropping the database first removes all objects, then the user can be dropped cleanly.

            # Step 1: Terminate active connections to the database (required before DROP DATABASE)
            try:
                cur.execute(
                    sql.SQL("SELECT pg_terminate_backend(pg_stat_activity.pid) "
                            "FROM pg_stat_activity "
                            "WHERE pg_stat_activity.datname = {} "
                            "AND pid <> pg_backend_pid()").format(sql.Literal(db_name))
                )
                logger.info(f"✓ Terminated active connections to: {db_name}")
            except Exception as e:
                logger.warning(f"Connection termination warning: {e}")

            # Step 2: Drop database (if exists)
            try:
                drop_db_sql = sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(db_name))
                cur.execute(drop_db_sql)
                logger.info(f"✓ Dropped database: {db_name}")
            except Exception as e:
                logger.error(f"Database drop error: {e}")
                raise
            
            # Step 3: Drop user (now safe - database and all objects are gone)
            try:
                drop_user_sql = sql.SQL("DROP USER IF EXISTS {}").format(sql.Identifier(db_user))
                cur.execute(drop_user_sql)
                logger.info(f"✓ Dropped user: {db_user}")
            except Exception as e:
                logger.warning(f"User drop warning: {e}")
            
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
