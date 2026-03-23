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
                    "SELECT active_session_id FROM projects WHERE id = %s FOR UPDATE",
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
                        "active_session_id": current_lock
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
                    """SELECT p.active_session_id, s.label as session_name
                       FROM projects p
                       LEFT JOIN sessions s ON s.id = p.active_session_id
                       WHERE p.id = %s""",
                    (project_id,)
                )
                result = cur.fetchone()
                
                if not result:
                    return {"active_session_id": None, "session_name": None}
                
                return {
                    "active_session_id": result["active_session_id"],
                    "session_name": result["session_name"]
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
