#!/usr/bin/env python3
"""
!ask command - Process user queries through AI logic.
"""

import discord
from discord.ext import commands

from services.ai_logic import process_user_input


async def ask(ctx, *, query: str = ""):
    """Handle !ask <query> command."""
    if not query:
        await ctx.send("Please provide a question. Usage: `!ask <your question>`")
        return

    # Process through AI logic
    try:
        response = process_user_input(query)
        await ctx.send(response)
    except Exception as e:
        print(f"Ask command error: {e}")
        await ctx.send("Sorry, I couldn't process your request. Please try again.")


def setup(bot):
    """Register the ask command with the bot."""
    bot.command(name="ask")(ask)
