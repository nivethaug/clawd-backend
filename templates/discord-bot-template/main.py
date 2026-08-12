#!/usr/bin/env python3
"""
Discord Bot Template - Entry Point (SLASH COMMANDS ONLY)
NO business logic here. Only slash command registration and bot startup.

This bot uses Discord Application Commands (slash commands) exclusively.
No text/prefix commands (!cmd) are registered.
"""

import os
import sys
import json
import logging
import threading
import asyncio
import discord
from discord import app_commands
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

# Bot setup with intents.
# Slash commands do NOT require the message_content privileged intent.
# If you add moderation/message-reading features, uncomment the line below
# AND enable "Message Content Intent" in the Discord Developer Portal:
#   intents.message_content = True
intents = discord.Intents.default()
# intents.message_content = True  # Uncomment ONLY for moderation/message-reading

# command_prefix is inert — no text commands are registered. Kept because
# commands.Bot requires it and provides bot.tree for slash commands.
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)


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

    # Sync slash commands to Discord.
    # "Synced 0 commands" is NORMAL if commands haven't changed since last sync.
    # Global commands take up to 1 hour to propagate to all servers.
    try:
        synced = await bot.tree.sync()
        logger.info(f"Synced {len(synced)} slash commands")
    except Exception as e:
        logger.error(f"Failed to sync slash commands: {e}")

    logger.info("Bot is ready!")


@bot.event
async def on_app_command_completion(interaction: discord.Interaction, command: app_commands.Command):
    """Log when a slash command completes successfully."""
    guild_name = interaction.guild.name if interaction.guild else "DM"
    logger.info(f"[SLASH-DONE] /{command.name} completed for {interaction.user} in {guild_name}")


@bot.event
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Global error handler for slash commands."""
    logger.error(f"[SLASH-ERR] Error in slash command: {error}", exc_info=True)
    try:
        if interaction.response.is_done():
            await interaction.followup.send("An error occurred. Please try again.", ephemeral=True)
        else:
            await interaction.response.send_message("An error occurred. Please try again.", ephemeral=True)
    except Exception:
        pass  # Don't crash on double-response


def setup_commands():
    """Register ALL slash commands via @bot.tree.command.

    This is the SINGLE registration point. To add a new slash command:
    1. Write the handler function (in commands/*.py or services/ai_logic.py)
    2. Add a @bot.tree.command block below that calls the handler
    3. bot.tree.sync() in on_ready() will push it to Discord automatically
    """
    from commands.start import start_handler
    from commands.help import help_handler
    from commands.ask import ask_handler
    from commands.status import status_handler

    @bot.tree.command(name="start", description="Register your account")
    async def start_cmd(interaction: discord.Interaction):
        await start_handler(interaction)

    @bot.tree.command(name="help", description="Show available commands")
    async def help_cmd(interaction: discord.Interaction):
        await help_handler(interaction)

    @bot.tree.command(name="ask", description="Ask a question or send a message")
    @app_commands.describe(query="Your question or request")
    async def ask_cmd(interaction: discord.Interaction, query: str):
        await ask_handler(interaction, query)

    @bot.tree.command(name="status", description="Check bot status and latency")
    async def status_cmd(interaction: discord.Interaction):
        await status_handler(interaction)

    logger.info("All slash commands registered.")


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

    # Register slash commands
    setup_commands()

    # Start bot
    logger.info("Starting Discord bot...")
    bot.run(DISCORD_TOKEN, log_handler=None)  # We handle logging ourselves


if __name__ == "__main__":
    main()
