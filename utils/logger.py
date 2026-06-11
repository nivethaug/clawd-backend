"""
Logger utility.
Centralized logging configuration.

Usage in service modules — override the logger name for correct log attribution:

    from utils.logger import logger as _logger
    import logging
    logger = logging.getLogger("services.discord.worker")

This ensures PM2 logs show the correct service name instead of a generic name.
"""

import logging
import sys

# Configure logging (guard against multiple basicConfig calls)
_logging_initialized = getattr(logging, '_dreampilot_initialized', False)
if not _logging_initialized:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    logging._dreampilot_initialized = True

# Default logger — services should override with their own logging.getLogger(__name__)
logger = logging.getLogger("root")
