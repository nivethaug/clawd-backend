#!/usr/bin/env python3
"""
!status command - Return bot status information.
"""

import discord
from discord.ext import commands


async def status(ctx):
    """Handle !status command."""
    await ctx.send(
        f"Bot running\n"
        f"Guilds: {len(ctx.bot.guilds)}\n"
        f"Latency: {round(ctx.bot.latency * 1000)}ms"
    )


def setup(bot):
    """Register the status command with the bot."""
    bot.command(name="status")(status)
