"""
AI Session Manager
Manage AI chat sessions with PostgreSQL backend
"""

import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from database_postgres import get_db

logger = logging.getLogger(__name__)


class AISessionManager:
    """
    Manage AI chat sessions with PostgreSQL persistence.
    
    Stores:
    - active_project_id: Currently selected project
    - pending_intent: Intent awaiting user confirmation
    """
    
    async def get_or_create_session(self, session_key: str) -> Dict[str, Any]:
        """
        Get existing session or create new one.
        
        Args:
            session_key: Unique session identifier (UUID)
            
        Returns:
            Session dict with all fields
        """
        with get_db() as conn:
            # Check if exists
            result = conn.execute(
                "SELECT * FROM ai_sessions WHERE session_key = %s",
                (session_key,)
            ).fetchone()
            
            if result:
                logger.debug(f"[AI-SESSION] Found existing session: {session_key}")
                session = dict(result)
                # Parse pending_intent if present
                if session.get("pending_intent"):
                    try:
                        session["pending_intent"] = json.loads(session["pending_intent"])
                    except:
                        session["pending_intent"] = None
                return session
            
            # Create new session
            logger.info(f"[AI-SESSION] Creating new session: {session_key}")
            conn.execute(
                "INSERT INTO ai_sessions (session_key, created_at, updated_at) VALUES (%s, NOW(), NOW())",
                (session_key,)
            )
            conn.commit()
            
            return {
                "session_key": session_key,
                "active_project_id": None,
                "pending_intent": None
            }
    
    async def set_active_project(self, session_key: str, project_domain: str) -> None:
        """
        Update active project for session.
        
        Args:
            session_key: Session identifier
            project_domain: Project domain (string identifier)
        """
        with get_db() as conn:
            conn.execute(
                "UPDATE ai_sessions SET active_project_id = %s, updated_at = NOW() WHERE session_key = %s",
                (project_domain, session_key)
            )
            conn.commit()
            logger.info(f"[AI-SESSION] Set active project '{project_domain}' for session {session_key}")
    
    async def get_active_project(self, session_key: str) -> Optional[Dict[str, Any]]:
        """
        Get active project for session.
        
        Args:
            session_key: Session identifier
            
        Returns:
            Project dict or None
        """
        with get_db() as conn:
            # Match by domain (active_project_id stores domain string)
            result = conn.execute("""
                SELECT p.*
                FROM ai_sessions s
                JOIN projects p ON s.active_project_id = p.domain
                WHERE s.session_key = %s
            """, (session_key,)).fetchone()
            
            return dict(result) if result else None
    
    async def clear_active_project(self, session_key: str) -> None:
        """
        Clear active project for session.
        
        Args:
            session_key: Session identifier
        """
        with get_db() as conn:
            conn.execute(
                "UPDATE ai_sessions SET active_project_id = NULL, updated_at = NOW() WHERE session_key = %s",
                (session_key,)
            )
            conn.commit()
            logger.info(f"[AI-SESSION] Cleared active project for session {session_key}")
    
    async def set_pending_intent(self, session_key: str, intent: Dict[str, Any]) -> None:
        """
        Store intent awaiting confirmation.
        
        Args:
            session_key: Session identifier
            intent: Intent dict with tool name and args
        """
        intent_json = json.dumps(intent)
        
        with get_db() as conn:
            conn.execute(
                "UPDATE ai_sessions SET pending_intent = %s, updated_at = NOW() WHERE session_key = %s",
                (intent_json, session_key)
            )
            conn.commit()
            logger.info(f"[AI-SESSION] Stored pending intent for session {session_key}: {intent.get('tool')}")
    
    async def get_pending_intent(self, session_key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve pending intent without clearing.
        
        Args:
            session_key: Session identifier
            
        Returns:
            Intent dict or None
        """
        with get_db() as conn:
            result = conn.execute(
                "SELECT pending_intent FROM ai_sessions WHERE session_key = %s",
                (session_key,)
            ).fetchone()
            
            if result and result["pending_intent"]:
                try:
                    return json.loads(result["pending_intent"])
                except:
                    return None
            
            return None
    
    async def clear_pending_intent(self, session_key: str) -> None:
        """
        Clear pending intent after confirmation/cancel.
        
        Args:
            session_key: Session identifier
        """
        with get_db() as conn:
            conn.execute(
                "UPDATE ai_sessions SET pending_intent = NULL, updated_at = NOW() WHERE session_key = %s",
                (session_key,)
            )
            conn.commit()
            logger.info(f"[AI-SESSION] Cleared pending intent for session {session_key}")
    
    async def update_last_used(self, session_key: str) -> None:
        """
        Update session last_used_at timestamp.
        
        Args:
            session_key: Session identifier
        """
        with get_db() as conn:
            conn.execute(
                "UPDATE ai_sessions SET updated_at = NOW() WHERE session_key = %s",
                (session_key,)
            )
            conn.commit()


# Singleton instance
_manager: Optional[AISessionManager] = None


def get_session_manager() -> AISessionManager:
    """Get or create session manager singleton."""
    global _manager
    if _manager is None:
        _manager = AISessionManager()
    return _manager
