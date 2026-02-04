"""
Database module for Clawd Backend.
Handles schema initialization, migrations, and database connections.
"""

import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.getenv("DB_PATH", "/root/clawd/clawdbot_adapter.db")


@contextmanager
def get_db():
    """
    Database connection context manager.
    Yields a connection with Row factory for dict-like access.
    Automatically closes connection on exit.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_schema():
    """
    Initialize database schema with all required tables and migrations.
    Creates tables if they don't exist, runs migrations for missing columns.
    """
    with get_db() as conn:
        # Users table
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            name TEXT,
            password TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")

        # Users table migrations
        try:
            conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
            conn.execute("ALTER TABLE users ADD COLUMN password TEXT")
            conn.commit()
        except:
            pass

        # Projects table
        conn.execute("""CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            project_path TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")

        # Projects table migrations
        try:
            conn.execute("ALTER TABLE projects ADD COLUMN description TEXT")
            conn.commit()
        except:
            pass

        try:
            conn.execute("ALTER TABLE projects ADD COLUMN project_path TEXT NOT NULL DEFAULT ''")
            conn.commit()
        except:
            pass

        # Sessions table
        conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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

        # Messages table
        conn.execute("""CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            image TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")

        # Messages table migration
        try:
            conn.execute("ALTER TABLE messages ADD COLUMN image TEXT")
            conn.commit()
        except:
            pass

        conn.commit()
