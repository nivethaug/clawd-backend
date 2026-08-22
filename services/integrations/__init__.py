"""Managed integrations for user projects (Phase 1 — API-key integrations).

See INTEGRATIONS_PLAN.md. Clean separation: everything for this feature
lives in services/integrations/ + api/integrations_router.py; existing
code is untouched beyond the router mount, the link-table schema block,
and a 1-line reconcile hook in the GI delete handler.
"""
