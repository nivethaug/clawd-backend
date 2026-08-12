#!/usr/bin/env python3
"""
/status slash command - Return bot status information.
"""

import discord


async def status_handler(interaction: discord.Interaction):
    """Handle /status slash command."""
    await interaction.response.send_message(
        f"Bot running\n"
        f"Guilds: {len(interaction.client.guilds)}\n"
        f"Latency: {round(interaction.client.latency * 1000)}ms"
    )


def setup(bot):
    """No-op. Slash commands are registered in main.py via @bot.tree.command."""
    pass
