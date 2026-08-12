#!/usr/bin/env python3
"""
/help slash command - Show available commands.
"""

import discord


async def help_handler(interaction: discord.Interaction):
    """Handle /help slash command."""
    help_text = (
        "**Available Commands:**\n\n"
        "`/start` - Register your account\n"
        "`/help` - Show this help message\n"
        "`/ask <query>` - Ask a question or send a message\n"
        "`/status` - Check bot status\n"
    )
    await interaction.response.send_message(help_text)


def setup(bot):
    """No-op. Slash commands are registered in main.py via @bot.tree.command."""
    pass
