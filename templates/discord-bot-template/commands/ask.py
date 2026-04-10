#!/usr/bin/env python3
"""
!ask command - Process user queries through AI logic.
"""
import logging
import discord
from discord.ext import commands

from services.ai_logic import process_user_input

logger = logging.getLogger('commands.ask')


async def ask(ctx, *, query: str = ""):
    """Handle !ask <query> command."""
    if not query:
        await ctx.send("Please provide a question. Usage: `!ask <your question>`")
        return

    logger.info(f"Processing query from {ctx.author}: {query[:100]}")

    # Process through AI logic
    try:
        response = process_user_input(query)
        logger.info(f"Response ({len(response)} chars): {response[:100]}...")
        await ctx.send(response)
    except Exception as e:
        logger.error(f"Ask command error: {e}", exc_info=True)
        await ctx.send("Sorry, I couldn't process your request. Please try again.")


def setup(bot):
    """Register the ask command with the bot."""
    bot.command(name="ask")(ask)
