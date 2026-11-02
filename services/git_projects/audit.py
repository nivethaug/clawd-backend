"""Git audit logging — tracks all git operations for security and debugging."""
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def audit_event(
    user_id: int,
    event: str,
    project_id: Optional[int] = None,
    detail: Optional[dict] = None,
):
    """Write a git audit event. Never includes tokens or credentials."""
    from database_adapter import get_db

    try:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO git_audit_events (user_id, project_id, event, detail)
                   VALUES (%s, %s, %s, %s::jsonb)""",
                (user_id, project_id, event, json.dumps(detail or {})),
            )
            conn.commit()
    except Exception as exc:
        logger.warning("[GIT-AUDIT] failed to write event %s for user %s: %s", event, user_id, exc)
