"""
DevOps chat project-session context helpers.

This keeps the selected editor session for the AI DevOps assistant in one
place, shared by web chat, Telegram, and tool execution.
"""

import logging
import uuid
from typing import Any, Dict, List, Optional

from database_postgres import get_db
from services.session_lock_service import SessionLockService

logger = logging.getLogger(__name__)


class DevOpsSessionContext:
    """Repository-style helper for active DevOps project-session state."""

    def get_user_active_session_id(self, user_id: int) -> Optional[int]:
        try:
            with get_db() as conn:
                row = conn.execute(
                    "SELECT active_project_session_id FROM users WHERE id = %s",
                    (user_id,),
                ).fetchone()
                value = row["active_project_session_id"] if row else None
                return int(value) if value is not None else None
        except Exception as e:
            logger.error("[DEVOPS-SESSION] Failed to get user active session: %s", e, exc_info=True)
            return None

    def set_user_active_session_id(self, user_id: int, session_id: int) -> bool:
        try:
            with get_db() as conn:
                conn.execute(
                    "UPDATE users SET active_project_session_id = %s WHERE id = %s",
                    (session_id, user_id),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.error("[DEVOPS-SESSION] Failed to set user active session: %s", e, exc_info=True)
            return False

    def clear_user_active_session_id(self, user_id: int) -> bool:
        try:
            with get_db() as conn:
                conn.execute(
                    "UPDATE users SET active_project_session_id = NULL WHERE id = %s",
                    (user_id,),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.error("[DEVOPS-SESSION] Failed to clear user active session: %s", e, exc_info=True)
            return False

    def get_session(self, user_id: int, session_id: int) -> Optional[Dict[str, Any]]:
        try:
            with get_db() as conn:
                row = conn.execute(
                    """
                    SELECT s.*, p.user_id, p.name AS project_name, p.domain AS project_domain
                    FROM sessions s
                    JOIN projects p ON p.id = s.project_id
                    WHERE s.id = %s AND s.archived = 0 AND p.user_id = %s
                    """,
                    (session_id, user_id),
                ).fetchone()
                return self._row_to_dict(row) if row else None
        except Exception as e:
            logger.error("[DEVOPS-SESSION] Failed to get session: %s", e, exc_info=True)
            return None

    def get_active_session(
        self,
        user_id: int,
        active_project: Optional[Dict[str, Any]],
        session_active_id: Optional[int] = None,
        user_active_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        if not active_project:
            return None

        candidates = [session_active_id, user_active_id]
        for candidate in candidates:
            if candidate is None:
                continue
            session = self.get_session(user_id, int(candidate))
            if session and int(session["project_id"]) == int(active_project["id"]):
                return session

        # Clear stale user-level session if it belongs elsewhere or was deleted.
        if user_active_id:
            self.clear_user_active_session_id(user_id)
        return None

    def list_project_sessions(self, user_id: int, project_id: int) -> List[Dict[str, Any]]:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT s.*
                FROM sessions s
                JOIN projects p ON p.id = s.project_id
                WHERE s.project_id = %s AND s.archived = 0 AND p.user_id = %s
                ORDER BY s.last_used_at DESC, s.created_at DESC
                """,
                (project_id, user_id),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def create_project_session(
        self,
        user_id: int,
        project_id: int,
        label: str,
        channel: str = "webchat",
        agent_id: str = "main",
    ) -> Dict[str, Any]:
        label = (label or "Untitled Session").strip()[:120] or "Untitled Session"
        channel = (channel or "webchat").strip()[:50] or "webchat"
        session_key = str(uuid.uuid4())

        with get_db() as conn:
            project = conn.execute(
                "SELECT id, name FROM projects WHERE id = %s AND user_id = %s",
                (project_id, user_id),
            ).fetchone()
            if not project:
                return {"status": "error", "message": "Project not found or not accessible"}

            conn.execute(
                """
                INSERT INTO sessions (project_id, session_key, label, channel, agent_id)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (project_id, session_key, label, channel, agent_id),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_key = %s",
                (session_key,),
            ).fetchone()

        return {"status": "success", "session": self._row_to_dict(row)}

    def get_project_lock(self, project_id: int) -> Dict[str, Any]:
        return SessionLockService.get_active_session(project_id)

    def can_select_session(self, project_id: int, session_id: int) -> Dict[str, Any]:
        lock = self.get_project_lock(project_id)
        active_session_id = lock.get("active_session_id")
        if active_session_id is not None and int(active_session_id) != int(session_id):
            return {
                "allowed": False,
                "lock": lock,
                "message": (
                    f"Project is locked by {lock.get('session_name') or f'session #{active_session_id}'}. "
                    "Complete or release that session before switching."
                ),
            }
        return {"allowed": True, "lock": lock}

    def select_session(self, user_id: int, session_key: str, session_id: int) -> Dict[str, Any]:
        session = self.get_session(user_id, session_id)
        if not session:
            return {"status": "error", "message": "Session not found or not accessible"}

        project_id = int(session["project_id"])
        lock_check = self.can_select_session(project_id, session_id)
        if not lock_check["allowed"]:
            return {
                "status": "error",
                "message": lock_check["message"],
                "result": {"lock": lock_check["lock"]},
            }

        lock_result = SessionLockService.acquire_lock(project_id, session_id)
        if not lock_result.get("success"):
            return {
                "status": "error",
                "message": lock_result.get("error", "Could not acquire session lock"),
                "result": lock_result,
            }

        self.set_user_active_session_id(user_id, session_id)
        self.set_ai_active_session_id(session_key, session_id)
        self.touch_session(session_id)
        return {
            "status": "success",
            "message": (
                f"Using session: {session.get('label') or f'#{session_id}'}. "
                "All normal messages now continue in this session until `/complete` or `/clearsession`."
            ),
            "result": {"session": session, "lock": lock_result},
        }

    def clear_context(self, user_id: int, session_key: str) -> None:
        self.clear_user_active_session_id(user_id)
        self.clear_ai_active_session_id(session_key)

    def release_selected_session(self, user_id: int, session_key: str, session_id: int) -> Dict[str, Any]:
        session = self.get_session(user_id, session_id)
        if not session:
            return {"status": "error", "message": "Session not found or not accessible"}

        result = SessionLockService.release_lock(int(session["project_id"]), int(session_id))
        self.clear_context(user_id, session_key)
        if result.get("released"):
            message = f"Completed and released {session.get('label') or f'session #{session_id}'}."
        else:
            message = "Session context cleared. No lock was released."
        return {"status": "success", "message": message, "result": result}

    def set_ai_active_session_id(self, session_key: str, session_id: int) -> bool:
        try:
            with get_db() as conn:
                conn.execute(
                    "UPDATE ai_sessions SET active_project_session_id = %s, updated_at = NOW() WHERE session_key = %s",
                    (session_id, session_key),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.error("[DEVOPS-SESSION] Failed to set AI active session: %s", e, exc_info=True)
            return False

    def clear_ai_active_session_id(self, session_key: str) -> bool:
        try:
            with get_db() as conn:
                conn.execute(
                    "UPDATE ai_sessions SET active_project_session_id = NULL, updated_at = NOW() WHERE session_key = %s",
                    (session_key,),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.error("[DEVOPS-SESSION] Failed to clear AI active session: %s", e, exc_info=True)
            return False

    def touch_session(self, session_id: int) -> None:
        try:
            with get_db() as conn:
                conn.execute("UPDATE sessions SET last_used_at = NOW() WHERE id = %s", (session_id,))
                conn.commit()
        except Exception as e:
            logger.warning("[DEVOPS-SESSION] Failed to touch session %s: %s", session_id, e)

    def _row_to_dict(self, row) -> Dict[str, Any]:
        data = dict(row)
        for key in ("created_at", "last_used_at"):
            value = data.get(key)
            if value and hasattr(value, "isoformat"):
                data[key] = value.isoformat()
        return data


_context: Optional[DevOpsSessionContext] = None


def get_devops_session_context() -> DevOpsSessionContext:
    global _context
    if _context is None:
        _context = DevOpsSessionContext()
    return _context
