#!/usr/bin/env python3
"""
/start slash command - Register user in database and send welcome message.
"""
import logging
import discord

from core.database import get_db
from models.user import get_or_create_discord_user

logger = logging.getLogger('commands.start')


async def start_handler(interaction: discord.Interaction):
    """Handle /start slash command."""
    user_id = str(interaction.user.id)
    username = str(interaction.user)

    logger.info(f"User starting: {username} (ID: {user_id})")

    # Get or create user in database.
    # NOTE: get_db() returns a raw psycopg2 connection. We open and close it
    # explicitly here (do NOT use "with get_db() as conn" — psycopg2's
    # connection context manager only rolls back on exit, it does NOT close).
    conn = None
    try:
        conn = get_db()
        user = get_or_create_discord_user(
            db=conn,
            discord_user_id=user_id,
            discord_username=username
        )
        conn.commit()
        logger.info(f"User registered: {username}")
        await interaction.response.send_message(
            f"Welcome, {interaction.user.mention}!\n"
            f"Your account has been set up.\n"
            f"Type `/help` to see available commands."
        )
    except Exception as e:
        logger.error(f"Start command error: {e}", exc_info=True)
        # Still respond so the interaction doesn't time out
        await interaction.response.send_message(
            "Welcome! There was an issue setting up your account, "
            "but you can still use the bot."
        )
    finally:
        if conn:
            conn.close()


def setup(bot):
    """No-op. Slash commands are registered in main.py via @bot.tree.command."""
    pass
