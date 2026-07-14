"""
Session Lock Service - Atomic session locking for single active session per project.

This module provides database-backed session locking to ensure only ONE session
can be active per project at a time. Uses PostgreSQL row-level locking (FOR UPDATE)
to prevent race conditions.

Usage:
    from services.session_lock_service import SessionLockService
    
    # Acquire lock before processing message
    result = SessionLockService.acquire_lock(project_id, session_id)
    if not result["success"]:
        raise HTTPException(423, result["error"])
    
    # Release lock when session completes
    SessionLockService.release_lock(project_id, session_id)
"""

import logging
from typing import Optional, Dict, Any
from contextlib import contextmanager
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class SessionLockService:
    """
    Service for managing session locks on projects.
    
    Uses PostgreSQL FOR UPDATE for atomic lock operations.
    """
    
    @staticmethod
    @contextmanager
    def _get_direct_connection():
        """
        Get a direct database connection (not from pool context manager).
        Needed for FOR UPDATE transactions that span multiple queries.
        """
        from database_postgres import get_connection_pool
        pool = get_connection_pool()
        conn = pool.getconn()
        try:
            yield conn
        finally:
            pool.putconn(conn)
    
    @staticmethod
    def acquire_lock(project_id: int, session_id: int) -> Dict[str, Any]:
        """
        Atomically acquire a lock on a project for a session.
        
        Uses PostgreSQL FOR UPDATE to prevent race conditions.
        If project is already locked by another session, returns failure.
        If project is locked by the SAME session, returns success (idempotent).
        
        Args:
            project_id: Project ID to lock
            session_id: Session ID acquiring the lock
            
        Returns:
            Dict with:
            - success: True if lock acquired, False if already locked
            - error: Error message if failed
            - active_session_id: Current active session ID if locked by another
        """
        from psycopg2.extras import RealDictCursor
        
        with SessionLockService._get_direct_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Lock the project row FOR UPDATE (atomic)
                cur.execute(
                    """SELECT p.active_session_id,
                              s.label AS session_name,
                              s.channel AS session_channel,
                              s.session_key AS session_key
                       FROM projects p
                       LEFT JOIN sessions s ON s.id = p.active_session_id
                       WHERE p.id = %s
                       FOR UPDATE OF p""",
                    (project_id,)
                )
                result = cur.fetchone()
                
                if not result:
                    conn.rollback()
                    return {
                        "success": False,
                        "error": "Project not found"
                    }
                
                current_lock = result["active_session_id"]
                
                # Already locked by same session (idempotent)
                if current_lock == session_id:
                    conn.commit()
                    logger.info(f"[LOCK] Session {session_id} already holds lock on project {project_id}")
                    return {"success": True, "already_held": True}
                
                # Locked by different session
                if current_lock is not None:
                    conn.rollback()
                    logger.warning(f"[LOCK] Project {project_id} locked by session {current_lock}, session {session_id} blocked")
                    return {
                        "success": False,
                        "error": "Another session is active",
                        "active_session_id": current_lock,
                        "session_name": result.get("session_name"),
                        "session_channel": result.get("session_channel"),
                        "session_key": result.get("session_key"),
                    }
                
                # Acquire lock
                cur.execute(
                    "UPDATE projects SET active_session_id = %s WHERE id = %s",
                    (session_id, project_id)
                )
                conn.commit()
                logger.info(f"[LOCK] Session {session_id} acquired lock on project {project_id}")
                return {"success": True}

    @staticmethod
    def acquire_processing(session_id: int, channel: str = "webchat", stale_after_minutes: int = 90) -> Dict[str, Any]:
        """
        Atomically mark a session as processing one chat message.

        Project locks are intentionally re-entrant for the same session so users
        can continue an active edit session. This flag is stricter: only one
        message may run inside that session at a time across web and Telegram.
        """
        from psycopg2.extras import RealDictCursor

        channel = (channel or "unknown").strip()[:50] or "unknown"

        with SessionLockService._get_direct_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT id, processing, processing_started_at, processing_channel
                       FROM sessions
                       WHERE id = %s AND archived = 0
                       FOR UPDATE""",
                    (session_id,),
                )
                result = cur.fetchone()

                if not result:
                    conn.rollback()
                    return {"success": False, "error": "Session not found"}

                if result.get("processing"):
                    started_at = result.get("processing_started_at")
                    is_stale = started_at is None
                    if not is_stale:
                        now = datetime.now(started_at.tzinfo) if getattr(started_at, "tzinfo", None) else datetime.now()
                        is_stale = (now - started_at) > timedelta(minutes=stale_after_minutes)
                    if not is_stale:
                        conn.rollback()
                        logger.info(
                            "[PROCESSING] Session %s is already processing via %s",
                            session_id,
                            result.get("processing_channel") or "unknown",
                        )
                        return {
                            "success": False,
                            "error": "Session is already processing a message",
                            "processing_channel": result.get("processing_channel"),
                            "processing_started_at": result.get("processing_started_at"),
                        }
                    logger.warning(
                        "[PROCESSING] Recovering stale processing flag for session %s started at %s",
                        session_id,
                        result.get("processing_started_at"),
                    )

                cur.execute(
                    """UPDATE sessions
                       SET processing = TRUE,
                           processing_started_at = CURRENT_TIMESTAMP,
                           processing_channel = %s,
                           last_used_at = CURRENT_TIMESTAMP
                       WHERE id = %s""",
                    (channel, session_id),
                )
                conn.commit()
                logger.info("[PROCESSING] Session %s marked processing via %s", session_id, channel)
                return {"success": True}

    @staticmethod
    def release_processing(session_id: int) -> Dict[str, Any]:
        """
        Clear the in-progress message flag for a session.
        """
        from psycopg2.extras import RealDictCursor

        with SessionLockService._get_direct_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """UPDATE sessions
                       SET processing = FALSE,
                           processing_started_at = NULL,
                           processing_channel = NULL
                       WHERE id = %s
                       RETURNING id""",
                    (session_id,),
                )
                row = cur.fetchone()
                conn.commit()
                if row:
                    logger.info("[PROCESSING] Session %s processing flag released", session_id)
                    return {"success": True, "released": True}
                return {"success": True, "released": False, "reason": "Session not found"}

    @staticmethod
    def get_processing_state(session_id: int) -> Dict[str, Any]:
        """
        Read the in-progress message flag for a session.
        """
        from psycopg2.extras import RealDictCursor

        with SessionLockService._get_direct_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT processing, processing_started_at, processing_channel
                       FROM sessions
                       WHERE id = %s""",
                    (session_id,),
                )
                result = cur.fetchone()
                if not result:
                    return {"processing": False, "processing_started_at": None, "processing_channel": None}
                return {
                    "processing": bool(result.get("processing")),
                    "processing_started_at": result.get("processing_started_at"),
                    "processing_channel": result.get("processing_channel"),
                }
    
    @staticmethod
    def release_lock(project_id: int, session_id: int) -> Dict[str, Any]:
        """
        Release a lock if held by the specified session.
        
        Only releases if the lock is held by THIS session (safe).
        If lock is held by different session or not locked, no-op.
        
        Args:
            project_id: Project ID to unlock
            session_id: Session ID releasing the lock
            
        Returns:
            Dict with:
            - success: True always
            - released: True if lock was released, False if not held
        """
        from psycopg2.extras import RealDictCursor
        
        with SessionLockService._get_direct_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Lock row and check current owner
                cur.execute(
                    "SELECT active_session_id FROM projects WHERE id = %s FOR UPDATE",
                    (project_id,)
                )
                result = cur.fetchone()
                
                if not result:
                    conn.rollback()
                    return {"success": True, "released": False, "reason": "Project not found"}
                
                current_lock = result["active_session_id"]
                
                # Not locked or locked by different session
                if current_lock != session_id:
                    conn.rollback()
                    logger.debug(f"[LOCK] Session {session_id} tried to release project {project_id} but lock held by {current_lock}")
                    return {"success": True, "released": False, "reason": "Not lock owner"}
                
                # Release lock
                cur.execute(
                    "UPDATE projects SET active_session_id = NULL WHERE id = %s",
                    (project_id,)
                )
                conn.commit()
                logger.info(f"[LOCK] Session {session_id} released lock on project {project_id}")
                return {"success": True, "released": True}
    
    @staticmethod
    def get_active_session(project_id: int) -> Dict[str, Any]:
        """
        Get the active session for a project.
        
        Args:
            project_id: Project ID to check
            
        Returns:
            Dict with:
            - active_session_id: Session ID if locked, null if unlocked
            - session_name: Session label if locked, null if unlocked
        """
        from psycopg2.extras import RealDictCursor
        
        with SessionLockService._get_direct_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT p.active_session_id,
                              s.label as session_name,
                              s.channel as session_channel,
                              s.session_key as session_key
                       FROM projects p
                       LEFT JOIN sessions s ON s.id = p.active_session_id
                       WHERE p.id = %s""",
                    (project_id,)
                )
                result = cur.fetchone()
                
                if not result:
                    return {"active_session_id": None, "session_name": None, "session_channel": None, "session_key": None}
                
                return {
                    "active_session_id": result["active_session_id"],
                    "session_name": result["session_name"],
                    "session_channel": result["session_channel"],
                    "session_key": result["session_key"],
                }
    
    @staticmethod
    def force_release_lock(project_id: int) -> Dict[str, Any]:
        """
        Force release any lock on a project (admin override).
        
        Use for crash recovery when session didn't complete properly.
        
        Args:
            project_id: Project ID to unlock
            
        Returns:
            Dict with:
            - success: True always
            - released_session_id: Session ID that was released, null if not locked
        """
        from psycopg2.extras import RealDictCursor
        
        with SessionLockService._get_direct_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get current lock
                cur.execute(
                    "SELECT active_session_id FROM projects WHERE id = %s FOR UPDATE",
                    (project_id,)
                )
                result = cur.fetchone()
                
                if not result:
                    conn.rollback()
                    return {"success": True, "released_session_id": None, "reason": "Project not found"}
                
                current_lock = result["active_session_id"]
                
                if current_lock is None:
                    conn.rollback()
                    return {"success": True, "released_session_id": None, "reason": "Not locked"}
                
                # Force release
                cur.execute(
                    "UPDATE projects SET active_session_id = NULL WHERE id = %s",
                    (project_id,)
                )
                conn.commit()
                logger.warning(f"[LOCK] Force released lock on project {project_id} (was held by session {current_lock})")
                return {
                    "success": True,
                    "released_session_id": current_lock
                }
    
    @staticmethod
    def is_locked(project_id: int) -> bool:
        """
        Check if a project is locked.
        
        Args:
            project_id: Project ID to check
            
        Returns:
            True if locked, False if unlocked
        """
        result = SessionLockService.get_active_session(project_id)
        return result["active_session_id"] is not None
