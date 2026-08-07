#!/usr/bin/env python3
"""
!help command - Show available commands.
"""

import discord
from discord.ext import commands


async def help_command(ctx):
    """Handle !help command."""
    help_text = (
        "**Available Commands:**\n\n"
        "`!start` - Register your account\n"
        "`!help` - Show this help message\n"
        "`!ask <query>` - Ask a question or send a message\n"
        "`!status` - Check bot status\n\n"
        "You can also just send a message without a command prefix!"
    )
    await ctx.send(help_text)


def setup(bot):
    """Register the help command with the bot.

    main.py uses commands.Bot(help_command=None) so discord.py's built-in
    !help is disabled — no need to call bot.remove_command("help") here.
    """
    @bot.command(name="help")
    async def _help(ctx):
        await help_command(ctx)
