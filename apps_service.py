"""
Apps Service

API for Running Apps page - lists running apps with uptime from PM2,
and other apps (needs fix + stopped).

Performance: Caches PM2 data for 2 seconds to avoid repeated calls.
"""

import logging
import subprocess
import json
import time
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from database_postgres import get_db

logger = logging.getLogger(__name__)

# ============================================================================
# PM2 Integration
# ============================================================================

# Cache for PM2 data (avoid repeated calls)
_pm2_cache: Dict[str, Any] = {"data": None, "timestamp": 0}
PM2_CACHE_TTL = 2  # seconds


def get_pm2_processes(force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
    """
    Get all PM2 processes with their status and uptime.
    
    Uses caching to avoid repeated PM2 calls.
    
    Args:
        force_refresh: Skip cache and fetch fresh data
    
    Returns:
        Dict mapping process name to process data:
        {
            "crypto-frontend": {
                "status": "online",
                "pm_uptime": 1710000000000,
                "cpu": 0.5,
                "memory": 50000000
            }
        }
    """
    global _pm2_cache
    
    # Check cache
    if not force_refresh and _pm2_cache["data"]:
        elapsed = time.time() - _pm2_cache["timestamp"]
        if elapsed < PM2_CACHE_TTL:
            return _pm2_cache["data"]
    
    try:
        # Call pm2 jlist for JSON output
        result = subprocess.run(
            ["pm2", "jlist"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            logger.warning(f"PM2 command failed: {result.stderr}")
            return {}
        
        # Parse JSON
        processes = json.loads(result.stdout)
        
        # Build lookup dict by name
        process_map = {}
        for proc in processes:
            name = proc.get("name", "")
            pm2_env = proc.get("pm2_env", {})
            
            process_map[name] = {
                "status": pm2_env.get("status", "unknown"),
                "pm_uptime": pm2_env.get("pm_uptime", 0),
                "cpu": proc.get("monit", {}).get("cpu", 0),
                "memory": proc.get("monit", {}).get("memory", 0),
                "restarts": pm2_env.get("restart_time", 0)
            }
        
        # Update cache
        _pm2_cache["data"] = process_map
        _pm2_cache["timestamp"] = time.time()
        
        logger.debug(f"PM2 data refreshed: {len(process_map)} processes")
        return process_map
        
    except subprocess.TimeoutExpired:
        logger.error("PM2 command timed out")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse PM2 output: {e}")
        return {}
    except FileNotFoundError:
        logger.warning("PM2 not found - returning empty process list")
        return {}
    except Exception as e:
        logger.error(f"Failed to get PM2 processes: {e}")
        return {}


def get_pm2_process_for_project(project_name: str, pm2_processes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Get PM2 process data for a project.
    
    Convention: {project_name}-frontend or {project_name}-backend
    
    Args:
        project_name: Project name (e.g., "crypto")
        pm2_processes: PM2 process map from get_pm2_processes()
    
    Returns:
        Process data dict or None
    """
    # Try frontend first (for UI apps)
    frontend_name = f"{project_name}-frontend"
    if frontend_name in pm2_processes:
        return pm2_processes[frontend_name]
    
    # Try backend
    backend_name = f"{project_name}-backend"
    if backend_name in pm2_processes:
        return pm2_processes[backend_name]
    
    # Try exact name match
    if project_name in pm2_processes:
        return pm2_processes[project_name]
    
    return None


# ============================================================================
# Uptime Utilities
# ============================================================================

def calculate_uptime_seconds(pm_uptime: Optional[int]) -> int:
    """
    Calculate uptime in seconds from PM2 uptime timestamp.
    
    Args:
        pm_uptime: PM2 uptime timestamp in milliseconds
    
    Returns:
        Uptime in seconds
    """
    if not pm_uptime:
        return 0
    
    # PM2 uptime is in milliseconds
    uptime_ms = pm_uptime
    current_ms = int(time.time() * 1000)
    
    return max(0, (current_ms - uptime_ms) // 1000)


def format_uptime(seconds: int) -> str:
    """
    Format uptime seconds to human-readable string.
    
    Args:
        seconds: Uptime in seconds
    
    Returns:
        Formatted string like "5 days, 3 hours" or "12 hours"
    """
    if seconds <= 0:
        return "0 hours"
    
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    
    if days > 0:
        return f"{days} day{'s' if days != 1 else ''}, {hours} hour{'s' if hours != 1 else ''}"
    elif hours > 0:
        return f"{hours} hour{'s' if hours != 1 else ''}"
    elif minutes > 0:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    else:
        return "just started"


# ============================================================================
# Status & Type Mapping
# ============================================================================

# Status mapping (same as dashboard)
STATUS_MAP = {
    "ready": "running",
    "error": "needs_fix",
    "failed": "needs_fix",
    "stopped": "stopped",
    "creating": "creating",
    "infrastructure_provisioning": "creating",
    "ai_provisioning": "creating",
}

# Actions by status
ACTIONS_MAP = {
    "running": ["open", "code", "pause"],
    "needs_fix": ["fix", "code", "restart"],
    "stopped": ["start", "code"],
    "creating": [],
}

# Type mapping from type_id
TYPE_MAP = {
    1: "website",
    2: "telegrambot",
    3: "discordbot",
    4: "tradingbot",
    5: "scheduler",
    6: "custom",
}


def map_status(status: Optional[str]) -> str:
    """Map database status to UI status."""
    if not status:
        return "unknown"
    return STATUS_MAP.get(status, "unknown")


def get_actions(status: str) -> List[str]:
    """Get available actions for a status."""
    return ACTIONS_MAP.get(status, [])


def map_type(type_id: Optional[int]) -> str:
    """Map type_id to type string."""
    if not type_id:
        return "custom"
    return TYPE_MAP.get(type_id, "custom")


# ============================================================================
# Database Queries
# ============================================================================

def get_user_projects(user_id: int) -> List[Dict[str, Any]]:
    """
    Get all projects for a user.
    
    Args:
        user_id: User ID
    
    Returns:
        List of project dicts
    """
    query = """
    SELECT 
        p.id,
        p.name,
        p.domain,
        p.status,
        p.type_id,
        p.project_path
    FROM projects p
    WHERE p.user_id = %s
    ORDER BY p.id DESC;
    """
    
    try:
        with get_db() as cur:
            cur.execute(query, (user_id,))
            rows = cur.fetchall()
            
            projects = []
            for row in rows:
                if isinstance(row, dict):
                    projects.append({
                        "id": row["id"],
                        "name": row["name"],
                        "domain": row["domain"],
                        "status": row["status"],
                        "type_id": row["type_id"],
                        "project_path": row["project_path"]
                    })
                else:
                    projects.append({
                        "id": row[0],
                        "name": row[1],
                        "domain": row[2],
                        "status": row[3],
                        "type_id": row[4],
                        "project_path": row[5]
                    })
            
            return projects
    except Exception as e:
        logger.error(f"Failed to get user projects: {e}")
        return []


# ============================================================================
# App Item Builder
# ============================================================================

def build_app_item(
    project: Dict[str, Any],
    pm2_processes: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Build an app item for the response.
    
    Args:
        project: Project dict from database
        pm2_processes: PM2 process map
    
    Returns:
        App item dict
    """
    project_name = project.get("name", "")
    project_domain = project.get("domain")
    raw_status = project.get("status")
    type_id = project.get("type_id")
    
    # Map status
    ui_status = map_status(raw_status)
    
    # Get PM2 data
    pm2_data = get_pm2_process_for_project(project_name, pm2_processes)
    
    # Calculate uptime
    uptime_seconds = 0
    if pm2_data and pm2_data.get("status") == "online":
        uptime_seconds = calculate_uptime_seconds(pm2_data.get("pm_uptime"))
    
    # Build domain URL
    domain_url = None
    if project_domain:
        domain_url = f"https://{project_domain}" if not project_domain.startswith("http") else project_domain
    
    return {
        "project_id": project["id"],
        "name": project_name,
        "type": map_type(type_id),
        "status": ui_status,
        "uptime": uptime_seconds,
        "uptime_label": format_uptime(uptime_seconds),
        "domain": domain_url,
        "actions": get_actions(ui_status)
    }


# ============================================================================
# Main API Function
# ============================================================================

def get_apps_list(user_id: int) -> Dict[str, List[Dict[str, Any]]]:
    """
    Get apps list split into running and others.
    
    Args:
        user_id: User ID
    
    Returns:
        Dict with "running" and "others" arrays
    """
    # Get all PM2 processes (cached)
    pm2_processes = get_pm2_processes()
    
    # Get user projects
    projects = get_user_projects(user_id)
    
    # Split into running and others
    running = []
    others = []
    
    for project in projects:
        app_item = build_app_item(project, pm2_processes)
        
        if app_item["status"] == "running":
            running.append(app_item)
        elif app_item["status"] in ["needs_fix", "stopped"]:
            others.append(app_item)
        # Skip "creating" and "unknown" from this view
    
    # Sort running by uptime (longest first)
    running.sort(key=lambda x: x["uptime"], reverse=True)
    
    # Sort others by status (needs_fix first) then name
    others.sort(key=lambda x: (0 if x["status"] == "needs_fix" else 1, x["name"]))
    
    return {
        "running": running,
        "others": others
    }


# ============================================================================
# PM2 Control Actions
# ============================================================================

def pm2_action(project_name: str, action: str) -> Dict[str, Any]:
    """
    Execute a PM2 action on a project.
    
    Args:
        project_name: Project name
        action: Action to perform (start, stop, restart)
    
    Returns:
        Dict with success status and message
    """
    # Map action to PM2 command
    action_map = {
        "start": "start",
        "stop": "stop", 
        "restart": "restart",
        "pause": "stop"  # pause = stop
    }
    
    pm2_cmd = action_map.get(action)
    if not pm2_cmd:
        return {"success": False, "error": f"Unknown action: {action}"}
    
    # Try frontend first, then backend
    process_names = [
        f"{project_name}-frontend",
        f"{project_name}-backend"
    ]
    
    results = []
    for proc_name in process_names:
        try:
            result = subprocess.run(
                ["pm2", pm2_cmd, proc_name],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                results.append({"process": proc_name, "success": True})
            else:
                results.append({"process": proc_name, "success": False, "error": result.stderr})
                
        except subprocess.TimeoutExpired:
            results.append({"process": proc_name, "success": False, "error": "Timeout"})
        except Exception as e:
            results.append({"process": proc_name, "success": False, "error": str(e)})
    
    # Check if any succeeded
    successes = [r for r in results if r.get("success")]
    
    if successes:
        # Clear PM2 cache to force refresh
        global _pm2_cache
        _pm2_cache = {"data": None, "timestamp": 0}
        
        return {
            "success": True,
            "message": f"{action.capitalize()} successful for {len(successes)} process(es)",
            "details": results
        }
    else:
        return {
            "success": False,
            "error": f"Failed to {action} any processes",
            "details": results
        }


# ============================================================================
# Response Models (for FastAPI)
# ============================================================================

from pydantic import BaseModel, Field


class AppItem(BaseModel):
    """Single app item in the apps list."""
    project_id: int = Field(..., description="Project ID")
    name: str = Field(..., description="Project name")
    type: str = Field(..., description="Project type (website, telegrambot, etc.)")
    status: str = Field(..., description="UI status (running, needs_fix, stopped)")
    uptime: int = Field(0, description="Uptime in seconds")
    uptime_label: str = Field(..., description="Human-readable uptime")
    domain: Optional[str] = Field(None, description="Project URL")
    actions: list[str] = Field(default_factory=list, description="Available actions")


class AppsListResponse(BaseModel):
    """Response for apps list endpoint."""
    running: list[AppItem] = Field(default_factory=list, description="Running apps")
    others: list[AppItem] = Field(default_factory=list, description="Other apps (needs_fix, stopped)")


class Pm2ActionResponse(BaseModel):
    """Response for PM2 action endpoint."""
    success: bool = Field(..., description="Whether action succeeded")
    message: Optional[str] = Field(None, description="Success message")
    error: Optional[str] = Field(None, description="Error message")
    details: Optional[list] = Field(None, description="Details per process")
