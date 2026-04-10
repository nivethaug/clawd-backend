#!/usr/bin/env python3
"""
Discord Bot Template - Entry Point
NO business logic here. Only command registration and bot startup.
"""

import os
import sys
import json
import threading
import asyncio
import discord
from discord.ext import commands
from http.server import HTTPServer, BaseHTTPRequestHandler

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DISCORD_TOKEN
from core.database import init_db

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

    # Start health server
    port = int(os.getenv("PORT", "8010"))
    health_thread = threading.Thread(target=start_health_server, args=(port,), daemon=True)
    health_thread.start()
    print(f"Health server started on port {port}")

    # Register commands
    setup_commands()

    # Start bot
    print("Starting Discord bot...")
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
