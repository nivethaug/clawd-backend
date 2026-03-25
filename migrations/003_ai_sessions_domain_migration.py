"""
Migration: Change active_project_id from INTEGER to TEXT
Date: 2026-03-25

This migration changes the active_project_id column in ai_sessions table
from INTEGER (referencing projects.id) to TEXT (storing project domain).

This ensures consistent domain-based project identification throughout the system.
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database_postgres import get_db
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate():
    """Run migration to change active_project_id to TEXT."""
    
    logger.info("=" * 60)
    logger.info("Migration 003: ai_sessions.active_project_id → TEXT")
    logger.info("=" * 60)
    
    with get_db() as conn:
        cur = conn.cursor()
        
        try:
            # Check if migration already done
            cur.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'ai_sessions' 
                AND column_name = 'active_project_id'
            """)
            result = cur.fetchone()
            
            if result and result[1] == 'text':
                logger.info("✓ Migration already applied (active_project_id is TEXT)")
                return
            
            logger.info(f"Current type: {result[1] if result else 'unknown'}")
            
            # Step 1: Create a temporary column
            logger.info("Step 1: Creating temporary column...")
            cur.execute("""
                ALTER TABLE ai_sessions 
                ADD COLUMN IF NOT EXISTS active_project_domain TEXT
            """)
            conn.commit()
            
            # Step 2: Migrate existing data (INTEGER ID → domain string)
            logger.info("Step 2: Migrating existing data...")
            cur.execute("""
                UPDATE ai_sessions s
                SET active_project_domain = p.domain
                FROM projects p
                WHERE s.active_project_id = p.id
                AND s.active_project_id IS NOT NULL
            """)
            migrated_count = cur.rowcount
            logger.info(f"  Migrated {migrated_count} sessions")
            conn.commit()
            
            # Step 3: Drop the old column
            logger.info("Step 3: Dropping old column...")
            cur.execute("""
                ALTER TABLE ai_sessions 
                DROP COLUMN IF EXISTS active_project_id
            """)
            conn.commit()
            
            # Step 4: Rename temp column to final name
            logger.info("Step 4: Renaming column...")
            cur.execute("""
                ALTER TABLE ai_sessions 
                RENAME COLUMN active_project_domain TO active_project_id
            """)
            conn.commit()
            
            # Step 5: Recreate index
            logger.info("Step 5: Recreating index...")
            cur.execute("""
                DROP INDEX IF EXISTS idx_ai_sessions_active_project_id
            """)
            cur.execute("""
                CREATE INDEX idx_ai_sessions_active_project_id 
                ON ai_sessions(active_project_id)
            """)
            conn.commit()
            
            logger.info("✓ Migration completed successfully!")
            logger.info(f"  - Column type changed: INTEGER → TEXT")
            logger.info(f"  - {migrated_count} sessions migrated from numeric ID to domain")
            
        except Exception as e:
            logger.error(f"✗ Migration failed: {e}")
            conn.rollback()
            raise


if __name__ == "__main__":
    migrate()
