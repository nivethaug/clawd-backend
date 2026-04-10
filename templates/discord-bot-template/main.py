#!/usr/bin/env python3
"""
Discord Bot Template - Entry Point
NO business logic here. Only command registration and bot startup.
"""

import os
import sys
import asyncio
import discord
from discord.ext import commands

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DISCORD_TOKEN
from core.database import init_db

# Bot setup with intents
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    """Called when bot is connected and ready."""
    print(f"Bot connected as {bot.user}")
    print(f"Guilds: {len(bot.guilds)}")
    print("Bot is ready!")


@bot.event
async def on_command_error(ctx, error):
    """Global error handler."""
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("Unknown command. Type `!help` for available commands.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"Missing argument: {error.param.name}")
    else:
        print(f"Command error: {error}")
        await ctx.send("An error occurred. Please try again.")


def setup_commands():
    """Register all command modules."""
    from commands.start import setup as setup_start
    from commands.help import setup as setup_help
    from commands.ask import setup as setup_ask
    from commands.status import setup as setup_status

    setup_start(bot)
    setup_help(bot)
    setup_ask(bot)
    setup_status(bot)

    print("All commands registered.")


def main():
    """Start the bot."""
    if not DISCORD_TOKEN:
        print("ERROR: DISCORD_TOKEN not set. Check your .env file.")
        sys.exit(1)

    # Initialize database tables
    init_db()
    print("Database initialized.")

    # Register commands
    setup_commands()

    # Start bot
    print("Starting Discord bot...")
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
