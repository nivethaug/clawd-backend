"""
Quick migration script to fix ai_sessions.active_project_id column
Run this immediately to fix the INTEGER to TEXT issue
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database_postgres import get_connection_pool
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def migrate_now():
    """Run migration immediately"""
    
    logger.info("=" * 60)
    logger.info("MIGRATION: ai_sessions.active_project_id INTEGER → TEXT")
    logger.info("=" * 60)
    
    pool = get_connection_pool()
    conn = pool.getconn()
    
    try:
        # CRITICAL: Set autocommit for DDL operations
        conn.autocommit = True
        
        with conn.cursor() as cur:
            # Check current column type
            cur.execute("""
                SELECT data_type 
                FROM information_schema.columns 
                WHERE table_name = 'ai_sessions' 
                AND column_name = 'active_project_id'
            """)
            result = cur.fetchone()
            
            if not result:
                logger.error("✗ Column active_project_id not found!")
                return False
            
            current_type = result[0]
            logger.info(f"Current type: {current_type}")
            
            if current_type == 'text':
                logger.info("✓ Already TEXT type - migration not needed")
                return True
            
            logger.info("🔄 Starting migration...")
            
            # Step 1: Create temporary column
            logger.info("Step 1: Creating temporary column...")
            cur.execute("ALTER TABLE ai_sessions ADD COLUMN IF NOT EXISTS active_project_domain TEXT")
            logger.info("✓ Created active_project_domain (TEXT)")
            
            # Step 2: Migrate data
            logger.info("Step 2: Migrating data...")
            cur.execute("""
                UPDATE ai_sessions s
                SET active_project_domain = p.domain
                FROM projects p
                WHERE s.active_project_id = p.id
                AND s.active_project_id IS NOT NULL
            """)
            migrated_count = cur.rowcount
            logger.info(f"✓ Migrated {migrated_count} sessions")
            
            # Step 3: Drop old column
            logger.info("Step 3: Dropping old column...")
            cur.execute("ALTER TABLE ai_sessions DROP COLUMN IF EXISTS active_project_id")
            logger.info("✓ Dropped old column")
            
            # Step 4: Rename temp column
            logger.info("Step 4: Renaming column...")
            cur.execute("ALTER TABLE ai_sessions RENAME COLUMN active_project_domain TO active_project_id")
            logger.info("✓ Renamed to active_project_id")
            
            # Step 5: Recreate index
            logger.info("Step 5: Recreating index...")
            cur.execute("DROP INDEX IF EXISTS idx_ai_sessions_active_project_id")
            cur.execute("CREATE INDEX idx_ai_sessions_active_project_id ON ai_sessions(active_project_id)")
            logger.info("✓ Index recreated")
            
            logger.info("=" * 60)
            logger.info("✓ MIGRATION COMPLETE!")
            logger.info(f"✓ Migrated {migrated_count} sessions from INTEGER to TEXT")
            logger.info("=" * 60)
            
            return True
    
    except Exception as e:
        logger.error("=" * 60)
        logger.error(f"✗ MIGRATION FAILED: {e}")
        logger.error("=" * 60)
        return False
    
    finally:
        pool.putconn(conn)


if __name__ == "__main__":
    success = migrate_now()
    sys.exit(0 if success else 1)
