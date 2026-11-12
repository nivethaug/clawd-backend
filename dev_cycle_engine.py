#!/usr/bin/env python3
"""Dev Cycle engine entrypoint — pm2 daemon.

Sources .env.postgres (DB creds) via start-cycle-engine.sh, then runs the
LISTEN/NOTIFY event loop in services.dev_cycles.engine.main().
"""
import asyncio

from services.dev_cycles.engine import main

if __name__ == "__main__":
    asyncio.run(main())
