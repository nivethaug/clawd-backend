"""
Recent Activity Service

Provides optimized queries for fetching recent work/activity
grouped by project, sorted by latest message timestamp.

Performance: Uses PostgreSQL DISTINCT ON for single-pass query.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from database_postgres import get_db

logger = logging.getLogger(__name__)


# ============================================================================
# Performance Indexes
# ============================================================================

def ensure_activity_indexes():
    """
    Create performance indexes for recent activity queries.
    Safe to call multiple times - uses IF NOT EXISTS.
    """
    indexes = [
        # Composite index for messages by session + time (covers most queries)
        """CREATE INDEX IF NOT EXISTS idx_messages_session_created 
           ON messages(session_id, created_at DESC)""",
        
        # Index for session-project joins
        """CREATE INDEX IF NOT EXISTS idx_sessions_project 
           ON sessions(project_id)""",
        
        # Index for project-user filtering
        """CREATE INDEX IF NOT EXISTS idx_projects_user 
           ON projects(user_id)""",
        
        # Index for messages with role filter (user messages for previews)
        """CREATE INDEX IF NOT EXISTS idx_messages_session_role_created 
           ON messages(session_id, role, created_at DESC)""",
    ]
    
    try:
        from database_postgres import get_connection_pool
        pool = get_connection_pool()
        conn = pool.getconn()
        try:
            with conn.cursor() as cur:
                for index_sql in indexes:
                    try:
                        cur.execute(index_sql)
                        conn.commit()
                        logger.debug(f"✓ Index created/verified: {index_sql.split('idx_')[1].split()[0]}")
                    except Exception as e:
                        conn.rollback()
                        logger.debug(f"Index check (expected): {e}")
        finally:
            pool.putconn(conn)
        logger.info("✓ Recent activity indexes verified")
    except Exception as e:
        logger.warning(f"Index creation warning: {e}")


# ============================================================================
# Core Query Functions
# ============================================================================

def get_recent_activity_optimized(
    user_id: int,
    limit: int = 20,
    offset: int = 0,
    include_preview: bool = True,
    preview_length: int = 100
) -> List[Dict[str, Any]]:
    """
    Fetch recent activity grouped by project, sorted by latest message.
    
    Uses PostgreSQL DISTINCT ON for optimal single-pass query.
    
    Args:
        user_id: User ID to filter projects
        limit: Max projects to return (default 20)
        offset: Pagination offset (default 0)
        include_preview: Include last message preview (default True)
        preview_length: Max chars for preview (default 100)
    
    Returns:
        List of project activity dicts with:
        - project_id: int
        - project_name: str
        - project_description: str (optional)
        - project_status: str (optional)
        - domain: str (optional)
        - last_activity: datetime
        - total_messages: int
        - total_sessions: int
        - last_message_preview: str (optional)
        - last_session_id: int
        - last_session_label: str
        - active_session_id: int (optional, for lock badge)
    """
    
    # Preview substring logic
    preview_expr = ""
    preview_field = ""
    
    if include_preview:
        # Truncate preview to avoid large responses
        preview_expr = f", LEFT(m.content, {preview_length}) AS last_message_preview"
        preview_field = "last_message_preview"
    
    # OPTIMIZED QUERY using DISTINCT ON
    # Gets one row per project (the one with latest message)
    query = f"""
    WITH latest_messages AS (
        -- Get latest message per project using DISTINCT ON
        SELECT DISTINCT ON (p.id)
            p.id AS project_id,
            p.name AS project_name,
            p.description AS project_description,
            p.status AS project_status,
            p.domain,
            p.active_session_id,
            m.id AS last_message_id,
            m.content AS last_message_content,
            m.created_at AS last_activity,
            m.role AS last_message_role,
            s.id AS last_session_id,
            s.label AS last_session_label
        FROM projects p
        INNER JOIN sessions s ON s.project_id = p.id
        INNER JOIN messages m ON m.session_id = s.id
        WHERE p.user_id = %s
        ORDER BY p.id, m.created_at DESC
    ),
    project_stats AS (
        -- Aggregate stats per project
        SELECT 
            p.id AS project_id,
            COUNT(DISTINCT s.id) AS total_sessions,
            COUNT(m.id) AS total_messages
        FROM projects p
        LEFT JOIN sessions s ON s.project_id = p.id
        LEFT JOIN messages m ON m.session_id = s.id
        WHERE p.user_id = %s
        GROUP BY p.id
    )
    SELECT 
        lm.project_id,
        lm.project_name,
        lm.project_description,
        lm.project_status,
        lm.domain,
        lm.active_session_id,
        lm.last_activity,
        lm.last_session_id,
        lm.last_session_label,
        lm.last_message_role,
        {f"LEFT(lm.last_message_content, {preview_length}) AS last_message_preview" if include_preview else "NULL AS last_message_preview"},
        COALESCE(ps.total_sessions, 0) AS total_sessions,
        COALESCE(ps.total_messages, 0) AS total_messages
    FROM latest_messages lm
    LEFT JOIN project_stats ps ON ps.project_id = lm.project_id
    ORDER BY lm.last_activity DESC
    LIMIT %s OFFSET %s;
    """
    
    try:
        with get_db() as cur:
            cur.execute(query, (user_id, user_id, limit, offset))
            rows = cur.fetchall()
            
            results = []
            for row in rows:
                # Handle RealDictCursor vs tuple
                if isinstance(row, dict):
                    result = dict(row)
                else:
                    # Tuple result (if cursor_factory not set)
                    result = {
                        "project_id": row[0],
                        "project_name": row[1],
                        "project_description": row[2],
                        "project_status": row[3],
                        "domain": row[4],
                        "active_session_id": row[5],
                        "last_activity": row[6],
                        "last_session_id": row[7],
                        "last_session_label": row[8],
                        "last_message_role": row[9],
                        "last_message_preview": row[10],
                        "total_sessions": row[11],
                        "total_messages": row[12]
                    }
                
                # Format datetime to ISO string
                if result.get("last_activity"):
                    if isinstance(result["last_activity"], datetime):
                        result["last_activity"] = result["last_activity"].isoformat() + "Z"
                    elif hasattr(result["last_activity"], 'isoformat'):
                        result["last_activity"] = result["last_activity"].isoformat() + "Z"
                
                results.append(result)
            
            logger.info(f"✓ Fetched {len(results)} recent activity items for user {user_id}")
            return results
            
    except Exception as e:
        logger.error(f"❌ Failed to fetch recent activity: {e}")
        raise


def get_recent_activity_simple(
    user_id: int,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """
    Simplified version without preview (faster).
    Use when preview is not needed.
    """
    query = """
    SELECT 
        p.id AS project_id,
        p.name AS project_name,
        p.status AS project_status,
        p.active_session_id,
        MAX(m.created_at) AS last_activity,
        COUNT(DISTINCT s.id) AS total_sessions,
        COUNT(m.id) AS total_messages
    FROM projects p
    INNER JOIN sessions s ON s.project_id = p.id
    INNER JOIN messages m ON m.session_id = s.id
    WHERE p.user_id = %s
    GROUP BY p.id
    ORDER BY MAX(m.created_at) DESC
    LIMIT %s;
    """
    
    try:
        with get_db() as cur:
            cur.execute(query, (user_id, limit))
            rows = cur.fetchall()
            
            results = []
            for row in rows:
                if isinstance(row, dict):
                    result = dict(row)
                else:
                    result = {
                        "project_id": row[0],
                        "project_name": row[1],
                        "project_status": row[2],
                        "active_session_id": row[3],
                        "last_activity": row[4],
                        "total_sessions": row[5],
                        "total_messages": row[6]
                    }
                
                # Format datetime
                if result.get("last_activity"):
                    if isinstance(result["last_activity"], datetime):
                        result["last_activity"] = result["last_activity"].isoformat() + "Z"
                    elif hasattr(result["last_activity"], 'isoformat'):
                        result["last_activity"] = result["last_activity"].isoformat() + "Z"
                
                results.append(result)
            
            return results
            
    except Exception as e:
        logger.error(f"❌ Failed to fetch recent activity (simple): {e}")
        raise


def get_project_activity_detail(
    project_id: int,
    message_limit: int = 10
) -> Dict[str, Any]:
    """
    Get detailed activity for a single project.
    Includes recent messages across all sessions.
    
    Args:
        project_id: Project ID
        message_limit: Max recent messages to include
    
    Returns:
        Project details with recent messages
    """
    
    query = """
    WITH recent_messages AS (
        SELECT 
            m.id,
            m.session_id,
            s.label AS session_label,
            m.role,
            m.content,
            m.created_at
        FROM messages m
        JOIN sessions s ON s.id = m.session_id
        WHERE s.project_id = %s
        ORDER BY m.created_at DESC
        LIMIT %s
    )
    SELECT 
        p.id AS project_id,
        p.name AS project_name,
        p.description,
        p.status,
        p.domain,
        p.active_session_id,
        (SELECT MAX(created_at) FROM messages m JOIN sessions s ON s.id = m.session_id WHERE s.project_id = p.id) AS last_activity,
        (SELECT COUNT(*) FROM sessions WHERE project_id = p.id) AS total_sessions,
        (SELECT COUNT(*) FROM messages m JOIN sessions s ON s.id = m.session_id WHERE s.project_id = p.id) AS total_messages,
        (SELECT json_agg(rm) FROM recent_messages rm) AS recent_messages
    FROM projects p
    WHERE p.id = %s;
    """
    
    try:
        with get_db() as cur:
            cur.execute(query, (project_id, message_limit, project_id))
            row = cur.fetchone()
            
            if not row:
                return None
            
            if isinstance(row, dict):
                result = dict(row)
            else:
                result = {
                    "project_id": row[0],
                    "project_name": row[1],
                    "description": row[2],
                    "status": row[3],
                    "domain": row[4],
                    "active_session_id": row[5],
                    "last_activity": row[6],
                    "total_sessions": row[7],
                    "total_messages": row[8],
                    "recent_messages": row[9]
                }
            
            # Format datetime
            if result.get("last_activity"):
                if isinstance(result["last_activity"], datetime):
                    result["last_activity"] = result["last_activity"].isoformat() + "Z"
                elif hasattr(result["last_activity"], 'isoformat'):
                    result["last_activity"] = result["last_activity"].isoformat() + "Z"
            
            # Format message timestamps
            if result.get("recent_messages"):
                for msg in result["recent_messages"]:
                    if msg.get("created_at"):
                        if isinstance(msg["created_at"], datetime):
                            msg["created_at"] = msg["created_at"].isoformat() + "Z"
                        elif hasattr(msg["created_at"], 'isoformat'):
                            msg["created_at"] = msg["created_at"].isoformat() + "Z"
            
            return result
            
    except Exception as e:
        logger.error(f"❌ Failed to fetch project activity detail: {e}")
        raise


# ============================================================================
# Response Models (for FastAPI)
# ============================================================================

from pydantic import BaseModel, Field
from typing import Optional


class RecentActivityItem(BaseModel):
    """Single project activity item in recent work list."""
    project_id: int = Field(..., description="Project ID")
    project_name: str = Field(..., description="Project name")
    project_description: Optional[str] = Field(None, description="Project description")
    project_status: Optional[str] = Field(None, description="Project status")
    domain: Optional[str] = Field(None, description="Project domain")
    last_activity: str = Field(..., description="ISO timestamp of last message")
    total_messages: int = Field(0, description="Total messages across all sessions")
    total_sessions: int = Field(0, description="Total sessions count")
    last_message_preview: Optional[str] = Field(None, description="Preview of last message (truncated)")
    last_session_id: Optional[int] = Field(None, description="ID of session with latest message")
    last_session_label: Optional[str] = Field(None, description="Label of session with latest message")
    active_session_id: Optional[int] = Field(None, description="Active session ID (for lock badge)")


class RecentActivityResponse(BaseModel):
    """Response for recent activity endpoint."""
    items: list[RecentActivityItem] = Field(..., description="List of recent activity items")
    total: int = Field(..., description="Total items available (for pagination)")
    limit: int = Field(..., description="Items per page")
    offset: int = Field(..., description="Current page offset")


class ProjectActivityDetailResponse(BaseModel):
    """Detailed activity for a single project."""
    project_id: int
    project_name: str
    description: Optional[str] = None
    status: Optional[str] = None
    domain: Optional[str] = None
    active_session_id: Optional[int] = None
    last_activity: Optional[str] = None
    total_sessions: int = 0
    total_messages: int = 0
    recent_messages: Optional[list[dict]] = None


# ============================================================================
# Initialize on module load
# ============================================================================

# Create indexes when module loads
ensure_activity_indexes()
