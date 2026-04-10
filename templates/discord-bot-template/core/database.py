#!/usr/bin/env python3
"""
Core database connection - PostgreSQL only, raw SQL (no ORM).
"""

import psycopg2
import psycopg2.extras
from contextlib import contextmanager

from config import DATABASE_URL


def get_db():
    """
    Get a database connection.

    Usage:
        with get_db() as conn:
            cursor = conn.execute(...)
            conn.commit()
    """
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn


@contextmanager
def get_db_cursor(dict_cursor=False):
    """
    Context manager for database operations with automatic commit/rollback.

    Usage:
        with get_db_cursor() as cur:
            cur.execute("SELECT * FROM users")
            rows = cur.fetchall()

        with get_db_cursor(dict_cursor=True) as cur:
            cur.execute("SELECT * FROM users")
            rows = cur.fetchall()  # Returns dicts
    """
    conn = get_db()
    try:
        if dict_cursor:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def init_db():
    """
    Initialize database tables. Called on bot startup.
    """
    conn = get_db()
    try:
        cur = conn.cursor()

        # Create users table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email TEXT,
                password TEXT,
                discord_user_id TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        conn.commit()
        print("Database tables verified.")
    except Exception as e:
        print(f"Database init error: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()
