"""
Autonomous Developer — Codex-powered self-healing maintenance agent.

This package runs autonomously to:
1. Read QA test failures from the ai-qa-tester database
2. Feed failures to Codex for fixing context_api.py
3. Restart PM2 wrapper, create test projects, validate results
4. Loop until all failures are resolved or safety limits are hit

Safety:
  - Codex is NEVER used in production user-facing flows
  - Daily 5-hour usage limit enforced via codex_usage_tracker
  - Lock files prevent concurrent runs
  - MAX_ITERATIONS caps loop count per invocation
"""

__version__ = "1.0.0"
