#!/usr/bin/env python3
"""
User model - Database operations for users.
"""

from typing import Optional, Dict, Any


def get_or_create_discord_user(
    db,
    discord_user_id: str,
    discord_username: str = ""
) -> Optional[Dict[str, Any]]:
    """
    Get existing user or create new Discord user.

    Args:
        db: Database connection
        discord_user_id: Discord user ID as string
        discord_username: Discord username

    Returns:
        User dict or None
    """
    cur = db.cursor()

    # Check if user exists
    cur.execute(
        "SELECT * FROM users WHERE discord_user_id = %s",
        (discord_user_id,)
    )
    user = cur.fetchone()

    if user:
        cur.close()
        return {
            "id": user[0],
            "email": user[1],
            "discord_user_id": user[3],
            "created_at": user[4]
        }

    # Create new user
    cur.execute(
        "INSERT INTO users (discord_user_id) VALUES (%s) RETURNING id, email, discord_user_id, created_at",
        (discord_user_id,)
    )
    new_user = cur.fetchone()
    db.commit()
    cur.close()

    if new_user:
        return {
            "id": new_user[0],
            "email": new_user[1],
            "discord_user_id": new_user[2],
            "created_at": new_user[3]
        }

    return None


def get_user_by_discord_id(db, discord_user_id: str) -> Optional[Dict[str, Any]]:
    """
    Get user by Discord ID.

    Args:
        db: Database connection
        discord_user_id: Discord user ID as string

    Returns:
        User dict or None
    """
    cur = db.cursor()
    cur.execute(
        "SELECT id, email, discord_user_id, created_at FROM users WHERE discord_user_id = %s",
        (discord_user_id,)
    )
    user = cur.fetchone()
    cur.close()

    if user:
        return {
            "id": user[0],
            "email": user[1],
            "discord_user_id": user[2],
            "created_at": user[3]
        }

    return None
