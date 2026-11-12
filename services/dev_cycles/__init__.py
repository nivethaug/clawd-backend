"""Dev Cycle — autonomous delivery orchestrator (PM/engineer/lead).

Chat intake → plan → task-board execution, driven by Postgres
LISTEN/NOTIFY (channel: dev_cycle_events). All state in dev_cycles /
cycle_messages / cycle_tasks so the engine is restart-safe.
"""
