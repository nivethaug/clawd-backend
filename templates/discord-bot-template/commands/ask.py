#!/usr/bin/env python3
"""
/ask slash command - Process user queries through AI logic.

This is the free-text command. It routes the user's query through
process_user_input() in services/ai_logic.py, which is the AI brain
that parses intent and calls APIs as needed.
"""
import logging
import discord

from services.ai_logic import process_user_input

logger = logging.getLogger('commands.ask')


async def ask_handler(interaction: discord.Interaction, query: str):
    """Handle /ask <query> slash command.

    Args:
        interaction: The Discord slash command interaction.
        query: The user's free-text question (arrives as plain text, no prefix).
    """
    logger.info(f"Processing query from {interaction.user}: {query[:100]}")

    try:
        response = process_user_input(query)
        logger.info(f"Response ({len(response)} chars): {response[:100]}...")
        await interaction.response.send_message(response)
    except Exception as e:
        logger.error(f"Ask command error: {e}", exc_info=True)
        await interaction.response.send_message(
            "Sorry, I couldn't process your request. Please try again."
        )


def setup(bot):
    """No-op. Slash commands are registered in main.py via @bot.tree.command."""
    pass
