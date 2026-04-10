#!/usr/bin/env python3
"""
!start command - Register user in database and send welcome message.
"""

import discord
from discord.ext import commands

from core.database import get_db
from models.user import get_or_create_discord_user


async def start(ctx):
    """Handle !start command."""
    user_id = str(ctx.author.id)
    username = str(ctx.author)
    channel_id = str(ctx.channel.id)

    # Get or create user in database
    try:
        with get_db() as conn:
            cur = conn.cursor()
            user = get_or_create_discord_user(
                db=conn,
                discord_user_id=user_id,
                discord_username=username
            )
            conn.commit()
            cur.close()

        await ctx.send(
            f"Welcome, {ctx.author.mention}!\n"
            f"Your account has been set up.\n"
            f"Type `!help` to see available commands."
        )
    except Exception as e:
        print(f"Start command error: {e}")
        await ctx.send("Welcome! There was an issue setting up your account, but you can still use the bot.")


def setup(bot):
    """Register the start command with the bot."""
    bot.command(name="start")(start)
