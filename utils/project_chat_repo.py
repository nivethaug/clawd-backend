"""
Project Chat Repository
Handles persistence of per-project chat messages and active project selection.

Stores max 10 messages per project (trims older ones).
Only last 4 messages are typically sent to LLM for context.
"""

import json
import logging
from typing import Optional, List, Dict, Any

from database_postgres import get_db

logger = logging.getLogger(__name__)

MAX_MESSAGES_PER_PROJECT = 10


class ProjectChatRepository:
    """
    Repository for project-scoped chat messages and active project selection.

    All methods are synchronous (use context-managed DB connections from the pool).
    Call from async endpoints directly — get_db() is thread-safe.
    """

    # ──────────────────────────────────────────────────────────────
    # Message persistence
    # ──────────────────────────────────────────────────────────────

    def add_message(
        self,
        user_id: int,
        project_domain: str,
        role: str,
        content: str,
        response_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Insert a message, then trim to MAX_MESSAGES_PER_PROJECT.

        Args:
            user_id: Authenticated user ID.
            project_domain: Project domain (e.g. 'thinkai-likrt6').
            role: 'user' or 'assistant'.
            content: Message text.
            response_type: 'text'|'execution'|'selection'|'confirmation'|'error'|None.
            metadata: Dict with rich response fields (progress, options, intent, etc.).

        Returns:
            The inserted row as dict, or None on failure.
        """
        metadata_json = json.dumps(metadata, default=str) if metadata else None

        try:
            with get_db() as conn:
                # Insert the message and capture the returned row
                row = conn.execute(
                    """INSERT INTO projectchat
                       (user_id, project_domain, role, content, response_type, metadata)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       RETURNING *""",
                    (user_id, project_domain, role, content, response_type, metadata_json),
                ).fetchone()

                conn.commit()

                if row:
                    inserted = dict(row)
                else:
                    inserted = None

                # Trim: keep only newest MAX_MESSAGES_PER_PROJECT for this project
                conn.execute(
                    """DELETE FROM projectchat
                       WHERE user_id = %s
                         AND project_domain = %s
                         AND id NOT IN (
                             SELECT id FROM projectchat
                             WHERE user_id = %s AND project_domain = %s
                             ORDER BY created_at DESC
                             LIMIT %s
                         )""",
                    (
                        user_id,
                        project_domain,
                        user_id,
                        project_domain,
                        MAX_MESSAGES_PER_PROJECT,
                    ),
                )
                conn.commit()

                logger.debug(
                    f"[PROJECT-CHAT] Added message (user={user_id}, "
                    f"project={project_domain}, role={role})"
                )
                return inserted

        except Exception as e:
            logger.error(f"[PROJECT-CHAT] Failed to add message: {e}", exc_info=True)
            return None

    def get_messages(
        self,
        user_id: int,
        project_domain: str,
        limit: int = MAX_MESSAGES_PER_PROJECT,
    ) -> List[Dict[str, Any]]:
        """
        Get messages for a project (oldest first, for UI display).

        Returns up to `limit` messages ordered oldest→newest.
        """
        try:
            with get_db() as conn:
                rows = conn.execute(
                    """SELECT * FROM (
                           SELECT * FROM projectchat
                           WHERE user_id = %s AND project_domain = %s
                           ORDER BY created_at DESC
                           LIMIT %s
                       ) AS recent
                       ORDER BY created_at ASC""",
                    (user_id, project_domain, limit),
                ).fetchall()

                return [self._row_to_dict(r) for r in rows]

        except Exception as e:
            logger.error(f"[PROJECT-CHAT] Failed to get messages: {e}", exc_info=True)
            return []

    def get_recent_messages(
        self,
        user_id: int,
        project_domain: str,
        limit: int = 4,
    ) -> List[Dict[str, Any]]:
        """
        Get the most recent N messages for LLM context (oldest→newest order).

        Used to build conversation history sent to GLM.
        """
        try:
            with get_db() as conn:
                rows = conn.execute(
                    """SELECT * FROM (
                           SELECT * FROM projectchat
                           WHERE user_id = %s AND project_domain = %s
                           ORDER BY created_at DESC
                           LIMIT %s
                       ) AS recent
                       ORDER BY created_at ASC""",
                    (user_id, project_domain, limit),
                ).fetchall()

                return [self._row_to_dict(r) for r in rows]

        except Exception as e:
            logger.error(f"[PROJECT-CHAT] Failed to get recent messages: {e}", exc_info=True)
            return []

    def clear_messages(self, user_id: int, project_domain: str) -> bool:
        """Delete all messages for a project (e.g. when switching projects)."""
        try:
            with get_db() as conn:
                conn.execute(
                    """DELETE FROM projectchat
                       WHERE user_id = %s AND project_domain = %s""",
                    (user_id, project_domain),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"[PROJECT-CHAT] Failed to clear messages: {e}", exc_info=True)
            return False

    # ──────────────────────────────────────────────────────────────
    # Active project persistence (users table)
    # ──────────────────────────────────────────────────────────────

    def get_active_project(self, user_id: int) -> Optional[str]:
        """Read active project domain from users table."""
        try:
            with get_db() as conn:
                row = conn.execute(
                    "SELECT active_project FROM users WHERE id = %s",
                    (user_id,),
                ).fetchone()
                return row["active_project"] if row else None
        except Exception as e:
            logger.error(f"[PROJECT-CHAT] Failed to get active project: {e}", exc_info=True)
            return None

    def set_active_project(self, user_id: int, domain: str) -> bool:
        """Store active project domain in users table."""
        try:
            with get_db() as conn:
                conn.execute(
                    "UPDATE users SET active_project = %s WHERE id = %s",
                    (domain, user_id),
                )
                conn.commit()
                logger.info(f"[PROJECT-CHAT] Set active_project={domain} for user {user_id}")
                return True
        except Exception as e:
            logger.error(f"[PROJECT-CHAT] Failed to set active project: {e}", exc_info=True)
            return False

    def clear_active_project(self, user_id: int) -> bool:
        """Set active project to NULL in users table."""
        try:
            with get_db() as conn:
                conn.execute(
                    "UPDATE users SET active_project = NULL WHERE id = %s",
                    (user_id,),
                )
                conn.commit()
                logger.info(f"[PROJECT-CHAT] Cleared active_project for user {user_id}")
                return True
        except Exception as e:
            logger.error(f"[PROJECT-CHAT] Failed to clear active project: {e}", exc_info=True)
            return False

    # ──────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────

    def _row_to_dict(self, row) -> Dict[str, Any]:
        """Convert a DB row to dict, parsing metadata JSONB."""
        d = dict(row)
        # Parse metadata back to dict if present
        meta = d.get("metadata")
        if meta and isinstance(meta, str):
            try:
                d["metadata"] = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                pass  # Leave as-is if unparseable
        # Normalize created_at to ISO string for JSON transport
        if d.get("created_at") and hasattr(d["created_at"], "isoformat"):
            d["created_at"] = d["created_at"].isoformat()
        return d
