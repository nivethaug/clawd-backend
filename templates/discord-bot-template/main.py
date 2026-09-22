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

    def do_POST(self):
        """Dev verifier — agent-facing synthetic invocation.

        POST /dev/invoke  (Authorization: Bearer <SECRET_KEY>)
        body {"text": "...", "guild_id": "...", "channel_id": "...",
              "user_id": "..."} -> runs process_user_input() (the same
        function slash commands use) in THIS process and returns the reply
        JSON plus the pipeline stage that produced it.

        Context ids are OPTIONAL but load-bearing: bots that keep per-guild
        or per-channel state (knowledge bases, configs) MUST be invoked with
        the real ids, or the handler silently searches an empty store and
        the fallback reply looks like correct behavior. Pass the guild the
        user actually reported the problem from.

        No Discord API involvement; lets the platform agent verify changes
        end-to-end instead of guessing from logs.
        """
        import hmac
        import time
        if self.path != '/dev/invoke':
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length else b'{}'
        try:
            body = json.loads(raw or b'{}')
        except Exception:
            body = {}
        supplied = (self.headers.get('Authorization') or '').removeprefix('Bearer ').strip()
        from config import SECRET_KEY
        if not SECRET_KEY or not hmac.compare_digest(supplied, SECRET_KEY):
            self._json(403, {"ok": False, "error": "unauthorized"})
            return
        text = str(body.get('text') or '').strip()
        if not text:
            self._json(400, {"ok": False, "error": "text is required"})
            return
        # Per-guild/per-channel state lookups need the REAL ids — without
        # them handlers fall back to defaults and search empty stores.
        ctx = {
            k: str(body.get(k) or '').strip()
            for k in ('guild_id', 'channel_id', 'user_id')
            if str(body.get(k) or '').strip()
        }
        started = time.monotonic()
        try:
            from services import ai_logic
            response = ai_logic.process_user_input(text, ctx or None)
            self._json(200, {
                "ok": True,
                "response": str(response),
                # Which pipeline stage produced the reply — "fallback:*" /
                # "*_not_found" means the primary path degraded; a plain
                # fallback STRING reply is not proof the bot works.
                "stage": dict(ai_logic.LAST_STAGE),
                "context": ctx,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            })
        except Exception as e:
            import traceback
            self._json(200, {
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "trace": traceback.format_exc()[-1500:],
                "context": ctx,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            })

    def _json(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

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
