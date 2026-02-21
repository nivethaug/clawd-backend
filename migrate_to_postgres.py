#!/usr/bin/env python3
"""
SQLite to PostgreSQL Migration Script
Migrates master database data from SQLite to PostgreSQL.
Preserves IDs, relationships, and validates data integrity.
"""

import sys
import os
import sqlite3
import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# SQLite path
SQLITE_DB = "/root/clawd-backend/clawdbot_adapter.db"

# PostgreSQL connection
POSTGRES_HOST = os.getenv("DB_HOST", "localhost")
POSTGRES_PORT = os.getenv("DB_PORT", "5432")
POSTGRES_DB = os.getenv("DB_NAME", "dreampilot")
POSTGRES_USER = os.getenv("DB_USER", "admin")
POSTGRES_PASSWORD = os.getenv("DB_PASSWORD", "StrongAdminPass123")


def get_sqlite_connection():
    """Get SQLite connection."""
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row
    return conn


def get_postgres_connection():
    """Get PostgreSQL connection."""
    return psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        cursor_factory=RealDictCursor
    )


def migrate_users():
    """Migrate users table from SQLite to PostgreSQL."""
    logger.info("Migrating users...")
    
    sqlite_conn = get_sqlite_connection()
    postgres_conn = get_postgres_connection()
    
    try:
        sqlite_cur = sqlite_conn.cursor()
        postgres_cur = postgres_conn.cursor()
        
        # Get all users from SQLite
        sqlite_cur.execute("SELECT * FROM users")
        users = sqlite_cur.fetchall()
        
        logger.info(f"  Found {len(users)} users in SQLite")
        
        # Insert into PostgreSQL
        migrated_count = 0
        for user in users:
            try:
                postgres_cur.execute("""
                    INSERT INTO users (email, name, password, created_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (email) DO NOTHING
                    RETURNING id
                """, (user['email'], user['name'], user['password'], user['created_at']))
                
                if postgres_cur.fetchone():
                    migrated_count += 1
                    
            except Exception as e:
                logger.error(f"  Failed to migrate user {user['email']}: {e}")
        
        postgres_conn.commit()
        logger.info(f"✓ Migrated {migrated_count}/{len(users)} users")
        
        return {"total": len(users), "migrated": migrated_count}
        
    except Exception as e:
        logger.error(f"❌ Users migration failed: {e}")
        raise
    finally:
        sqlite_conn.close()
        postgres_conn.close()


def migrate_project_types():
    """Migrate project_types table from SQLite to PostgreSQL."""
    logger.info("Migrating project_types...")
    
    sqlite_conn = get_sqlite_connection()
    postgres_conn = get_postgres_connection()
    
    try:
        sqlite_cur = sqlite_conn.cursor()
        postgres_cur = postgres_conn.cursor()
        
        # Get all project types from SQLite
        sqlite_cur.execute("SELECT * FROM project_types")
        types = sqlite_cur.fetchall()
        
        logger.info(f"  Found {len(types)} project types in SQLite")
        
        # Insert into PostgreSQL (idempotent via ON CONFLICT)
        migrated_count = 0
        for ptype in types:
            try:
                postgres_cur.execute("""
                    INSERT INTO project_types (type, display_name, template_md_path, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (type) DO UPDATE
                        SET display_name = EXCLUDED.display_name,
                            template_md_path = EXCLUDED.template_md_path,
                            updated_at = EXCLUDED.updated_at
                """, (ptype['type'], ptype['display_name'], ptype['template_md_path'], 
                      ptype['created_at'], ptype['updated_at']))
                migrated_count += 1
                    
            except Exception as e:
                logger.error(f"  Failed to migrate project type {ptype['type']}: {e}")
        
        postgres_conn.commit()
        logger.info(f"✓ Migrated {migrated_count}/{len(types)} project types")
        
        return {"total": len(types), "migrated": migrated_count}
        
    except Exception as e:
        logger.error(f"❌ Project types migration failed: {e}")
        raise
    finally:
        sqlite_conn.close()
        postgres_conn.close()


def migrate_projects():
    """Migrate projects table from SQLite to PostgreSQL."""
    logger.info("Migrating projects...")
    
    sqlite_conn = get_sqlite_connection()
    postgres_conn = get_postgres_connection()
    
    try:
        sqlite_cur = sqlite_conn.cursor()
        postgres_cur = postgres_conn.cursor()
        
        # Get all projects from SQLite
        sqlite_cur.execute("SELECT * FROM projects")
        projects = sqlite_cur.fetchall()
        
        logger.info(f"  Found {len(projects)} projects in SQLite")
        
        # Insert into PostgreSQL
        migrated_count = 0
        for project in projects:
            try:
                postgres_cur.execute("""
                    INSERT INTO projects (
                        id, user_id, name, description, project_path, type_id, 
                        domain, status, archived, created_at, updated_at,
                        claude_code_session_name, openclaw_session_key, template_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                        SET user_id = EXCLUDED.user_id,
                            name = EXCLUDED.name,
                            description = EXCLUDED.description,
                            project_path = EXCLUDED.project_path,
                            type_id = EXCLUDED.type_id,
                            domain = EXCLUDED.domain,
                            status = EXCLUDED.status,
                            archived = EXCLUDED.archived,
                            updated_at = EXCLUDED.updated_at,
                            claude_code_session_name = EXCLUDED.claude_code_session_name,
                            openclaw_session_key = EXCLUDED.openclaw_session_key,
                            template_id = EXCLUDED.template_id
                """, (
                    project['id'], project['user_id'], project['name'], 
                    project['description'], project['project_path'], 
                    project.get('type_id'),
                    project.get('domain', ''), project.get('status', 'creating'),
                    project.get('archived', 0), project['created_at'], project['updated_at'],
                    project.get('claude_code_session_name'), project.get('openclaw_session_key'),
                    project.get('template_id')
                ))
                migrated_count += 1
                    
            except Exception as e:
                logger.error(f"  Failed to migrate project {project['id']}: {e}")
        
        postgres_conn.commit()
        
        # Reset sequence to max ID
        postgres_cur.execute("""
            SELECT setval('projects_id_seq', COALESCE(MAX(id), 1))
            FROM projects
        """)
        postgres_conn.commit()
        
        logger.info(f"✓ Migrated {migrated_count}/{len(projects)} projects")
        logger.info("✓ Reset projects ID sequence")
        
        return {"total": len(projects), "migrated": migrated_count}
        
    except Exception as e:
        logger.error(f"❌ Projects migration failed: {e}")
        raise
    finally:
        sqlite_conn.close()
        postgres_conn.close()


def migrate_sessions():
    """Migrate sessions table from SQLite to PostgreSQL."""
    logger.info("Migrating sessions...")
    
    sqlite_conn = get_sqlite_connection()
    postgres_conn = get_postgres_connection()
    
    try:
        sqlite_cur = sqlite_conn.cursor()
        postgres_cur = postgres_conn.cursor()
        
        # Get all sessions from SQLite
        sqlite_cur.execute("SELECT * FROM sessions")
        sessions = sqlite_cur.fetchall()
        
        logger.info(f"  Found {len(sessions)} sessions in SQLite")
        
        # Insert into PostgreSQL
        migrated_count = 0
        for session in sessions:
            try:
                postgres_cur.execute("""
                    INSERT INTO sessions (
                        id, project_id, session_key, label, archived, scope,
                        channel, agent_id, created_at, last_used_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (session_key) DO UPDATE
                        SET project_id = EXCLUDED.project_id,
                            label = EXCLUDED.label,
                            archived = EXCLUDED.archived,
                            last_used_at = EXCLUDED.last_used_at
                """, (
                    session['id'], session['project_id'], session['session_key'], 
                    session.get('label'), session.get('archived', 0), session.get('scope'),
                    session.get('channel', 'webchat'), session.get('agent_id', 'main'),
                    session['created_at'], session.get('last_used_at', session['created_at'])
                ))
                migrated_count += 1
                    
            except Exception as e:
                logger.error(f"  Failed to migrate session {session['id']}: {e}")
        
        postgres_conn.commit()
        
        # Reset sequence
        postgres_cur.execute("""
            SELECT setval('sessions_id_seq', COALESCE(MAX(id), 1))
            FROM sessions
        """)
        postgres_conn.commit()
        
        logger.info(f"✓ Migrated {migrated_count}/{len(sessions)} sessions")
        
        return {"total": len(sessions), "migrated": migrated_count}
        
    except Exception as e:
        logger.error(f"❌ Sessions migration failed: {e}")
        raise
    finally:
        sqlite_conn.close()
        postgres_conn.close()


def migrate_messages():
    """Migrate messages table from SQLite to PostgreSQL."""
    logger.info("Migrating messages...")
    
    sqlite_conn = get_sqlite_connection()
    postgres_conn = get_postgres_connection()
    
    try:
        sqlite_cur = sqlite_conn.cursor()
        postgres_cur = postgres_conn.cursor()
        
        # Get all messages from SQLite
        sqlite_cur.execute("SELECT * FROM messages")
        messages = sqlite_cur.fetchall()
        
        logger.info(f"  Found {len(messages)} messages in SQLite")
        
        # Insert into PostgreSQL
        migrated_count = 0
        for message in messages:
            try:
                postgres_cur.execute("""
                    INSERT INTO messages (id, session_id, role, content, image, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                        SET session_id = EXCLUDED.session_id,
                            role = EXCLUDED.role,
                            content = EXCLUDED.content,
                            image = EXCLUDED.image
                """, (
                    message['id'], message['session_id'], message['role'], 
                    message['content'], message.get('image'), message['created_at']
                ))
                migrated_count += 1
                    
            except Exception as e:
                logger.error(f"  Failed to migrate message {message['id']}: {e}")
        
        postgres_conn.commit()
        
        # Reset sequence
        postgres_cur.execute("""
            SELECT setval('messages_id_seq', COALESCE(MAX(id), 1))
            FROM messages
        """)
        postgres_conn.commit()
        
        logger.info(f"✓ Migrated {migrated_count}/{len(messages)} messages")
        
        return {"total": len(messages), "migrated": migrated_count}
        
    except Exception as e:
        logger.error(f"❌ Messages migration failed: {e}")
        raise
    finally:
        sqlite_conn.close()
        postgres_conn.close()


def validate_migration() -> bool:
    """
    Validate migration by comparing record counts.
    
    Returns:
        True if validation passed, False otherwise
    """
    logger.info("Validating migration...")
    
    try:
        sqlite_conn = get_sqlite_connection()
        postgres_conn = get_postgres_connection()
        
        sqlite_cur = sqlite_conn.cursor()
        postgres_cur = postgres_conn.cursor()
        
        # Validate each table
        tables = ['users', 'project_types', 'projects', 'sessions', 'messages']
        all_valid = True
        
        for table in tables:
            # SQLite count
            sqlite_cur.execute(f"SELECT COUNT(*) as count FROM {table}")
            sqlite_count = sqlite_cur.fetchone()['count']
            
            # PostgreSQL count
            postgres_cur.execute(f"SELECT COUNT(*) as count FROM {table}")
            postgres_count = postgres_cur.fetchone()['count']
            
            if sqlite_count == postgres_count:
                logger.info(f"  ✓ {table}: {sqlite_count} records")
            else:
                logger.error(f"  ✗ {table}: SQLite={sqlite_count}, PostgreSQL={postgres_count}")
                all_valid = False
        
        sqlite_conn.close()
        postgres_conn.close()
        
        return all_valid
        
    except Exception as e:
        logger.error(f"❌ Migration validation failed: {e}")
        return False


def run_migration(dry_run: bool = False) -> Dict[str, Any]:
    """
    Run full migration from SQLite to PostgreSQL.
    
    Args:
        dry_run: If True, only validate without migrating
    
    Returns:
        Dict with migration results
    """
    logger.info("=" * 60)
    logger.info("Starting SQLite to PostgreSQL Migration")
    logger.info("=" * 60)
    
    results = {
        "dry_run": dry_run,
        "tables": {},
        "success": False
    }
    
    try:
        # Validate PostgreSQL connection
        logger.info("Testing PostgreSQL connection...")
        try:
            test_conn = get_postgres_connection()
            test_conn.close()
            logger.info("✅ PostgreSQL connection successful")
        except Exception as e:
            logger.error(f"❌ PostgreSQL connection failed: {e}")
            return {
                "success": False,
                "error": f"PostgreSQL connection failed: {e}"
            }
        
        if dry_run:
            logger.info("⚠️ DRY RUN - No data will be migrated")
            return {
                "success": True,
                "dry_run": True,
                "message": "Dry run completed successfully"
            }
        
        # Migrate each table
        results["tables"]["users"] = migrate_users()
        results["tables"]["project_types"] = migrate_project_types()
        results["tables"]["projects"] = migrate_projects()
        results["tables"]["sessions"] = migrate_sessions()
        results["tables"]["messages"] = migrate_messages()
        
        # Validate migration
        validation_passed = validate_migration()
        
        if validation_passed:
            logger.info("=" * 60)
            logger.info("✅ Migration completed successfully!")
            logger.info("=" * 60)
            results["success"] = True
        else:
            logger.error("=" * 60)
            logger.error("❌ Migration validation failed!")
            logger.error("=" * 60)
            results["success"] = False
            results["validation_failed"] = True
        
        return results
        
    except Exception as e:
        logger.error("=" * 60)
        logger.error(f"❌ Migration failed: {e}")
        logger.error("=" * 60)
        return {
            "success": False,
            "error": str(e)
        }


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Migrate SQLite to PostgreSQL")
    parser.add_argument("--dry-run", action="store_true", help="Validate without migrating")
    parser.add_argument("--force", action="store_true", help="Force migration even if validation fails")
    
    args = parser.parse_args()
    
    results = run_migration(dry_run=args.dry_run)
    
    if results["success"]:
        print("\n✅ Migration completed successfully")
        sys.exit(0)
    else:
        print(f"\n❌ Migration failed: {results.get('error', 'Unknown error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
