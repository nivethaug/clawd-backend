#!/usr/bin/env python3
"""
Scheduler Project - Thin entry point.
No database, no scheduler loop — all managed centrally by services/scheduler/.
This file exists for project structure consistency.
"""

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger('scheduler')

logger.info("Scheduler project loaded. Jobs managed by core scheduler_worker.")
