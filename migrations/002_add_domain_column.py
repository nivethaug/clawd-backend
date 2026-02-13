"""
Migration 002: Add domain column to projects table

Adds:
- domain VARCHAR(255) NOT NULL UNIQUE to projects table
- Index on domain for faster lookups
"""

import os
import sqlite3
from database import get_db

DB_PATH = os.getenv("DB_PATH", "/root/clawd/clawdbot_adapter.db")


def migrate():
    """Add domain column to projects table."""
    print("Running migration 002: Add domain column...")

    with get_db() as conn:
        try:
            # Add domain column
            conn.execute("""
                ALTER TABLE projects
                ADD COLUMN domain VARCHAR(255) NOT NULL DEFAULT ''
            """)
            print("✓ Added domain column")

            # Create unique index on domain
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_domain
                ON projects(domain)
            """)
            print("✓ Created unique index on domain")

            conn.commit()
            print("✓ Migration 002 completed successfully")

        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print("✓ Domain column already exists, skipping")
                conn.rollback()
            else:
                print(f"✗ Migration failed: {e}")
                conn.rollback()
                raise


if __name__ == "__main__":
    migrate()
