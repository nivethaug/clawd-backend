"""
Dashboard Service

Single API powering the entire Home page.
Returns all dashboard data in ONE response (no multiple calls).

Performance: Single aggregated queries, <100ms target.
"""

import logging
import time
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from database_postgres import get_db

logger = logging.getLogger(__name__)

# ============================================================================
# Server Metrics
# ============================================================================

def get_server_metrics() -> Dict[str, Any]:
    """
    Get server performance metrics using psutil.
    
    Returns:
        Dict with cpu_usage, ram_usage, ram_total, ram_used, uptime_seconds
    """
    try:
        import psutil
        
        mem = psutil.virtual_memory()
        
        return {
            "cpu_usage": round(psutil.cpu_percent(interval=0.3), 1),
            "ram_usage": round(mem.percent, 1),
            "ram_total": mem.total // (1024 * 1024),  # MB
            "ram_used": mem.used // (1024 * 1024),    # MB
            "uptime_seconds": int(time.time() - psutil.boot_time())
        }
    except ImportError:
        logger.warning("psutil not installed, using fallback metrics")
        return {
            "cpu_usage": 0.0,
            "ram_usage": 0.0,
            "ram_total": 0,
            "ram_used": 0,
            "uptime_seconds": 0
        }
    except Exception as e:
        logger.error(f"Failed to get server metrics: {e}")
        return {
            "cpu_usage": 0.0,
            "ram_usage": 0.0,
            "ram_total": 0,
            "ram_used": 0,
            "uptime_seconds": 0
        }


def get_server_status() -> Dict[str, Any]:
    """
    Get server status with label and message.
    
    Returns:
        Dict with status, label, message, and metrics
    """
    metrics = get_server_metrics()
    
    # Determine status based on metrics
    cpu_ok = metrics["cpu_usage"] < 90
    ram_ok = metrics["ram_usage"] < 90
    
    if cpu_ok and ram_ok:
        return {
            "status": "connected",
            "label": "My Server",
            "message": "Connected and running smoothly",
            "metrics": metrics
        }
    else:
        return {
            "status": "warning",
            "label": "My Server",
            "message": "High resource usage detected",
            "metrics": metrics
        }


# ============================================================================
# Status Mapping
# ============================================================================

# Status to UI status mapping
STATUS_MAP = {
    "ready": ("running", "Running"),
    "error": ("needs_fix", "Needs Fix"),
    "failed": ("needs_fix", "Needs Fix"),
    "stopped": ("stopped", "Stopped"),
    "creating": ("creating", "Setting up..."),
    "infrastructure_provisioning": ("creating", "Provisioning..."),
    "ai_provisioning": ("creating", "AI customizing..."),
}

# Status to progress mapping
PROGRESS_MAP = {
    "creating": 1,
    "infrastructure_provisioning": 4,
    "ai_provisioning": 8,
    "ready": 9,
    "error": 0,
    "failed": 0,
    "stopped": 0,
}

# Status to actions mapping
ACTIONS_MAP = {
    "ready": ["view", "pause", "code", "publish", "delete"],
    "error": ["fix", "code", "delete"],
    "failed": ["fix", "code", "delete"],
    "stopped": ["start", "code", "delete"],
    "creating": [],
    "infrastructure_provisioning": [],
    "ai_provisioning": [],
}


def map_status(status: Optional[str]) -> Tuple[str, str]:
    """
    Map database status to UI status.
    
    Args:
        status: Database status string
    
    Returns:
        Tuple of (ui_status, status_label)
    """
    if not status:
        return ("unknown", "Unknown")
    
    return STATUS_MAP.get(status, ("unknown", "Unknown"))


def get_progress(status: Optional[str]) -> int:
    """
    Get progress percentage based on status.
    
    Args:
        status: Database status string
    
    Returns:
        Progress percentage (0-9)
    """
    if not status:
        return 0
    
    return PROGRESS_MAP.get(status, 0)


def get_actions(status: Optional[str]) -> List[str]:
    """
    Get available actions for a status.
    
    Args:
        status: Database status string
    
    Returns:
        List of action strings
    """
    if not status:
        return []
    
    return ACTIONS_MAP.get(status, [])


# ============================================================================
# Database Queries
# ============================================================================

def get_project_stats(user_id: int) -> Dict[str, int]:
    """
    Get project counts by status category.
    
    Uses FILTER for single-pass aggregation.
    
    Args:
        user_id: User ID to filter
    
    Returns:
        Dict with running, needs_fix, stopped, creating counts
    """
    query = """
    SELECT 
        COUNT(*) FILTER (WHERE status = 'ready') AS running,
        COUNT(*) FILTER (WHERE status IN ('error', 'failed')) AS needs_fix,
        COUNT(*) FILTER (WHERE status = 'stopped') AS stopped,
        COUNT(*) FILTER (WHERE status IN ('creating', 'infrastructure_provisioning', 'ai_provisioning')) AS creating
    FROM projects
    WHERE user_id = %s;
    """
    
    try:
        with get_db() as cur:
            cur.execute(query, (user_id,))
            row = cur.fetchone()
            
            if isinstance(row, dict):
                return {
                    "running": row.get("running", 0) or 0,
                    "needs_fix": row.get("needs_fix", 0) or 0,
                    "stopped": row.get("stopped", 0) or 0,
                    "creating": row.get("creating", 0) or 0
                }
            else:
                return {
                    "running": row[0] or 0,
                    "needs_fix": row[1] or 0,
                    "stopped": row[2] or 0,
                    "creating": row[3] or 0
                }
    except Exception as e:
        logger.error(f"Failed to get project stats: {e}")
        return {"running": 0, "needs_fix": 0, "stopped": 0, "creating": 0}


def get_projects_with_activity(user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Get projects with last activity timestamp.
    
    Single query with LEFT JOIN to avoid N+1.
    
    Args:
        user_id: User ID to filter
        limit: Max projects to return
    
    Returns:
        List of project dicts with UI-ready fields
    """
    query = """
    SELECT 
        p.id,
        p.name,
        p.description,
        p.status,
        p.domain,
        p.project_path,
        MAX(m.created_at) AS last_active
    FROM projects p
    LEFT JOIN sessions s ON s.project_id = p.id
    LEFT JOIN messages m ON m.session_id = s.id
    WHERE p.user_id = %s
    GROUP BY p.id
    ORDER BY last_active DESC NULLS LAST
    LIMIT %s;
    """
    
    try:
        with get_db() as cur:
            cur.execute(query, (user_id, limit))
            rows = cur.fetchall()
            
            projects = []
            for row in rows:
                if isinstance(row, dict):
                    raw_status = row.get("status")
                    last_active = row.get("last_active")
                    domain = row.get("domain")
                else:
                    raw_status = row[4]
                    last_active = row[6]
                    domain = row[5]
                
                # Map status to UI values
                ui_status, status_label = map_status(raw_status)
                
                # Format last_active
                if last_active:
                    if isinstance(last_active, datetime):
                        last_active_str = last_active.isoformat() + "Z"
                    elif hasattr(last_active, 'isoformat'):
                        last_active_str = last_active.isoformat() + "Z"
                    else:
                        last_active_str = str(last_active)
                else:
                    last_active_str = None
                
                # Build domain URL
                domain_url = None
                if domain:
                    domain_url = f"https://{domain}" if not domain.startswith("http") else domain
                
                # Build project dict
                project = {
                    "id": row["id"] if isinstance(row, dict) else row[0],
                    "name": row["name"] if isinstance(row, dict) else row[1],
                    "description": row["description"] if isinstance(row, dict) else row[2],
                    "status": ui_status,
                    "status_label": status_label,
                    "domain": domain_url,
                    "last_active": last_active_str,
                    "actions": get_actions(raw_status)
                }
                
                # Add progress for creating status
                if ui_status == "creating":
                    project["progress"] = get_progress(raw_status)
                
                projects.append(project)
            
            return projects
    except Exception as e:
        logger.error(f"Failed to get projects with activity: {e}")
        return []


def get_needs_fix_highlight(user_id: int) -> Optional[Dict[str, Any]]:
    """
    Get the most recent project that needs fixing.
    
    Args:
        user_id: User ID to filter
    
    Returns:
        Dict with id and name, or None
    """
    query = """
    SELECT id, name
    FROM projects
    WHERE status IN ('error', 'failed') AND user_id = %s
    ORDER BY updated_at DESC NULLS LAST
    LIMIT 1;
    """
    
    try:
        with get_db() as cur:
            cur.execute(query, (user_id,))
            row = cur.fetchone()
            
            if not row:
                return None
            
            if isinstance(row, dict):
                return {"id": row["id"], "name": row["name"]}
            else:
                return {"id": row[0], "name": row[1]}
    except Exception as e:
        logger.error(f"Failed to get needs fix highlight: {e}")
        return None


# ============================================================================
# Suggestions Builder
# ============================================================================

def build_suggestions(stats: Dict[str, int], highlight_project: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build suggestions list based on user's projects.
    
    Args:
        stats: Project stats dict
        highlight_project: Project that needs fix (if any)
    
    Returns:
        List of suggestion dicts
    """
    suggestions = []
    
    # Suggest fixing broken project
    if stats["needs_fix"] > 0 and highlight_project:
        suggestions.append({
            "type": "fix",
            "title": f"Fix the {highlight_project['name']}",
            "project_id": highlight_project["id"]
        })
    
    # Always suggest creating new project
    suggestions.append({
        "type": "create",
        "title": "Create something new"
    })
    
    # Suggest reviewing activity
    suggestions.append({
        "type": "activity",
        "title": "Review recent activity"
    })
    
    return suggestions


# ============================================================================
# Main Dashboard Assembly
# ============================================================================

def get_home_dashboard(user_id: int, project_limit: int = 50) -> Dict[str, Any]:
    """
    Get complete dashboard data for home page.
    
    SINGLE API CALL - returns everything needed.
    
    Args:
        user_id: User ID
        project_limit: Max projects to include
    
    Returns:
        Complete dashboard dict with:
        - server: Server status and metrics
        - stats: Project counts by status
        - projects: List of projects with activity
        - highlight: Needs fix project highlight
        - suggestions: Action suggestions
    """
    start_time = time.time()
    
    # 1. Server status (parallel-ready)
    server = get_server_status()
    
    # 2. Project stats (single query)
    stats = get_project_stats(user_id)
    
    # 3. Projects with activity (single query)
    projects = get_projects_with_activity(user_id, limit=project_limit)
    
    # 4. Needs fix highlight (single query)
    highlight_project = get_needs_fix_highlight(user_id)
    
    # 5. Build highlight section
    highlight = {}
    if highlight_project:
        highlight["needs_fix_project_id"] = highlight_project["id"]
    
    # 6. Build suggestions
    suggestions = build_suggestions(stats, highlight_project)
    
    # Log performance
    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(f"Dashboard assembled in {elapsed_ms:.1f}ms for user {user_id}")
    
    return {
        "server": server,
        "stats": stats,
        "projects": projects,
        "highlight": highlight,
        "suggestions": suggestions
    }


# ============================================================================
# Response Models (for FastAPI)
# ============================================================================

from pydantic import BaseModel, Field
from typing import Optional


class ServerMetrics(BaseModel):
    cpu_usage: float = Field(..., description="CPU usage percentage")
    ram_usage: float = Field(..., description="RAM usage percentage")
    ram_total: int = Field(..., description="Total RAM in MB")
    ram_used: int = Field(..., description="Used RAM in MB")
    uptime_seconds: int = Field(..., description="Server uptime in seconds")


class ServerStatus(BaseModel):
    status: str = Field(..., description="Server status (connected, warning, error)")
    label: str = Field(..., description="Server label")
    message: str = Field(..., description="Status message")
    metrics: ServerMetrics = Field(..., description="Performance metrics")


class ProjectStats(BaseModel):
    running: int = Field(0, description="Running projects count")
    needs_fix: int = Field(0, description="Projects needing fix count")
    stopped: int = Field(0, description="Stopped projects count")
    creating: int = Field(0, description="Creating projects count")


class DashboardProject(BaseModel):
    id: int = Field(..., description="Project ID")
    name: str = Field(..., description="Project name")
    description: Optional[str] = Field(None, description="Project description")
    status: str = Field(..., description="UI status (running, needs_fix, stopped, creating)")
    status_label: str = Field(..., description="Human-readable status")
    domain: Optional[str] = Field(None, description="Project URL")
    last_active: Optional[str] = Field(None, description="Last activity ISO timestamp")
    actions: list[str] = Field(default_factory=list, description="Available actions")
    progress: Optional[int] = Field(None, description="Progress percentage (for creating status)")


class Highlight(BaseModel):
    needs_fix_project_id: Optional[int] = Field(None, description="ID of project needing fix")


class Suggestion(BaseModel):
    type: str = Field(..., description="Suggestion type (fix, create, activity)")
    title: str = Field(..., description="Suggestion title")
    project_id: Optional[int] = Field(None, description="Project ID (for fix type)")


class HomeDashboardResponse(BaseModel):
    """Complete dashboard response for home page."""
    server: ServerStatus = Field(..., description="Server status and metrics")
    stats: ProjectStats = Field(..., description="Project counts by status")
    projects: list[DashboardProject] = Field(..., description="User's projects")
    highlight: Highlight = Field(default_factory=dict, description="Highlighted items")
    suggestions: list[Suggestion] = Field(..., description="Action suggestions")
