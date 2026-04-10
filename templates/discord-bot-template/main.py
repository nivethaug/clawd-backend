#!/usr/bin/env python3
"""
Discord Bot Template - Entry Point
NO business logic here. Only command registration and bot startup.
"""

import os
import sys
import json
import logging
import threading
import asyncio
import discord
from discord.ext import commands
from http.server import HTTPServer, BaseHTTPRequestHandler

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DISCORD_TOKEN
from core.database import init_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('bot')

# Bot setup with intents
intents = discord.Intents.default()
intents.message_content = True  # Requires "Message Content Intent" in Developer Portal

bot = commands.Bot(command_prefix="!", intents=intents)


# Health server for infrastructure verification
class HealthHandler(BaseHTTPRequestHandler):
    """Lightweight HTTP health endpoint for pipeline verification."""

    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "healthy",
                "service": "discord-bot"
            }).encode())
        else:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ok",
                "service": "discord-bot",
                "path": self.path
            }).encode())

    def log_message(self, format, *args):
        pass  # Suppress access logs


def start_health_server(port):
    """Start health check HTTP server in background thread."""
    try:
        server = HTTPServer(('0.0.0.0', port), HealthHandler)
        server.serve_forever()
    except Exception:
        pass


@bot.event
async def on_ready():
    """Called when bot is connected and ready."""
    logger.info(f"Connected as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Guilds: {len(bot.guilds)}")
    for guild in bot.guilds:
        logger.info(f"  - {guild.name} (ID: {guild.id}, members: {guild.member_count})")
    logger.info("Bot is ready!")


@bot.event
async def on_message(message):
    """Log every message the bot can see."""
    # Ignore own messages
    if message.author == bot.user:
        return

    guild_name = message.guild.name if message.guild else "DM"
    channel_name = message.channel.name if hasattr(message.channel, 'name') else "DM"

    logger.info(f"[MSG] {guild_name}/#{channel_name} | {message.author}: {message.content[:200]}")

    # Process commands
    await bot.process_commands(message)


@bot.event
async def on_command(ctx):
    """Log every command execution."""
    guild_name = ctx.guild.name if ctx.guild else "DM"
    channel_name = ctx.channel.name if hasattr(ctx.channel, 'name') else "DM"
    logger.info(f"[CMD] !{ctx.command.name} | by {ctx.author} in {guild_name}/#{channel_name} | args: {ctx.args[2:]}")


@bot.event
async def on_command_completion(ctx):
    """Log when a command completes successfully."""
    logger.info(f"[CMD-DONE] !{ctx.command.name} completed for {ctx.author}")


@bot.event
async def on_command_error(ctx, error):
    """Global error handler."""
    if isinstance(error, commands.CommandNotFound):
        logger.warning(f"[CMD-404] Unknown command from {ctx.author}: {ctx.message.content[:100]}")
        await ctx.send("Unknown command. Type `!help` for available commands.")
    elif isinstance(error, commands.MissingRequiredArgument):
        logger.warning(f"[CMD-ERR] Missing argument for !{ctx.command.name}: {error.param.name}")
        await ctx.send(f"Missing argument: {error.param.name}")
    else:
        logger.error(f"[CMD-ERR] Error in !{ctx.command.name}: {error}", exc_info=True)
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

    logger.info("All commands registered.")


def main():
    """Start the bot."""
    if not DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN not set. Check your .env file.")
        sys.exit(1)

    # Initialize database tables
    init_db()
    logger.info("Database initialized.")

    # Start health server
    port = int(os.getenv("PORT", "8010"))
    health_thread = threading.Thread(target=start_health_server, args=(port,), daemon=True)
    health_thread.start()
    logger.info(f"Health server started on port {port}")

    # Register commands
    setup_commands()

    # Start bot
    logger.info("Starting Discord bot...")
    bot.run(DISCORD_TOKEN, log_handler=None)  # We handle logging ourselves


if __name__ == "__main__":
    main()
