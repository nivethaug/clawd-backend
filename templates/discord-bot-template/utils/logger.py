#!/usr/bin/env python3
"""
Logger setup - Simple logging configuration.
"""

import logging


def setup_logger(name: str = "discord_bot", level: int = logging.INFO) -> logging.Logger:
    """
    Create and configure a logger.

    Args:
        name: Logger name
        level: Logging level

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Console handler
    handler = logging.StreamHandler()
    handler.setLevel(level)

    # Format
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)

    if not logger.handlers:
        logger.addHandler(handler)

    return logger


# Default logger instance
logger = setup_logger()
