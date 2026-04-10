"""
Discord Bot Webhook Registration (No-op)

Discord bots use WebSocket gateway connections, not HTTP webhooks.
This module is a placeholder for architectural consistency with the
telegram pipeline structure.
"""
import logging
from typing import Tuple, Dict

logger = logging.getLogger(__name__)


def register_discord_interactions_endpoint(
    bot_token: str,
    domain: str,
    project_id: int
) -> Tuple[bool, str]:
    """
    No-op for Discord bots (they use WebSocket gateway, not webhooks).

    Args:
        bot_token: Discord bot token
        domain: Domain (unused for Discord)
        project_id: Project ID

    Returns:
        Always returns (True, message)
    """
    logger.info(f"Discord bot project {project_id}: Skipping webhook registration (uses WebSocket gateway)")
    return True, "Discord bots use WebSocket gateway, no webhook registration needed"


def register_interactions_async(
    bot_token: str,
    domain: str,
    project_id: int,
    max_retries: int = 9,
    initial_delay: int = 10
) -> None:
    """
    No-op async registration placeholder.

    Args:
        bot_token: Discord bot token
        domain: Domain
        project_id: Project ID
        max_retries: Unused
        initial_delay: Unused
    """
    logger.info(f"[DISCORD] project {project_id}: No webhook registration needed (WebSocket gateway)")
