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
from domain_config import BASE_DOMAIN, frontend_url as _frontend_url

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
        # Try pm2 jlist first (JSON output)
        result = subprocess.run(
            ["pm2", "jlist"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0 or not result.stdout.strip():
            logger.warning(f"PM2 jlist failed, trying prettylist: {result.stderr[:100]}")
            # Fallback to pm2 prettylist
            result = subprocess.run(
                ["pm2", "prettylist"],
                capture_output=True,
                text=True,
                timeout=5
            )
        
        if result.returncode != 0:
            logger.warning(f"PM2 command failed: {result.stderr[:100]}")
            return {}
        
        # Parse JSON
        processes = json.loads(result.stdout)
        
        # Build lookup dict by name
        process_map = {}
        for proc in processes:
            name = proc.get("name", "")
            pm2_env = proc.get("pm2_env", {})
            
            # pm_uptime can be under pm2_env or at root level
            pm_uptime = pm2_env.get("pm_uptime") or proc.get("pm_uptime", 0)
            
            process_map[name] = {
                "status": pm2_env.get("status", "unknown"),
                "pm_uptime": pm_uptime,
                "cpu": proc.get("monit", {}).get("cpu", 0),
                "memory": proc.get("monit", {}).get("memory", 0),
                "restarts": pm2_env.get("restart_time", 0)
            }
            
            # Debug log first few processes
            if len(process_map) <= 3:
                logger.info(f"[PM2] Process: {name}, status: {pm2_env.get('status')}, pm_uptime: {pm_uptime}")
        
        # Update cache
        _pm2_cache["data"] = process_map
        _pm2_cache["timestamp"] = time.time()
        
        logger.info(f"PM2 data refreshed: {len(process_map)} processes found")
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


def get_pm2_process_for_project(project_domain: str, pm2_processes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Get PM2 process data for a project.
    
    Convention: {project_domain}-frontend or {project_domain}-backend
    
    Args:
        project_domain: Project domain (e.g., "crypto" from "crypto.{BASE_DOMAIN}")
        pm2_processes: PM2 process map from get_pm2_processes()
    
    Returns:
        Process data dict or None
    """
    # Extract subdomain from full domain if needed
    if project_domain and "." in project_domain:
        # Extract subdomain (e.g., "crypto" from "crypto.{BASE_DOMAIN}")
        project_domain = project_domain.split(".")[0]
    
    if not project_domain:
        return None
    
    # Try frontend first (for UI apps)
    frontend_name = f"{project_domain}-frontend"
    if frontend_name in pm2_processes:
        return pm2_processes[frontend_name]
    
    # Try backend
    backend_name = f"{project_domain}-backend"
    if backend_name in pm2_processes:
        return pm2_processes[backend_name]
    
    # Try exact name match
    if project_domain in pm2_processes:
        return pm2_processes[project_domain]
    
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
    "scaffolded": "creating",
    "initializing": "creating",
    "building": "creating",
    "deploying": "creating",
    "verifying": "creating",
    "provisioning": "creating",
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
    7: "agent",
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
    
    # Get PM2 data using domain (PM2 services are named by domain, not project name)
    pm2_data = get_pm2_process_for_project(project_domain, pm2_processes)
    
    # Calculate uptime
    uptime_seconds = 0
    if pm2_data and pm2_data.get("status") == "online":
        uptime_seconds = calculate_uptime_seconds(pm2_data.get("pm_uptime"))
    
    # Build domain URL - add .{BASE_DOMAIN} suffix if not already present
    domain_url = None
    if project_domain:
        if project_domain.startswith("http"):
            domain_url = project_domain
        elif "." not in project_domain:
            # Domain is just subdomain (e.g., "thinkai-likrt6") - add full suffix
            domain_url = _frontend_url(project_domain)
        else:
            # Already has a dot but no http - add https
            domain_url = f"https://{project_domain}"
    
    # Debug logging for PM2 data
    logger.info(f"[APPS] Project: {project_name}, Domain: {project_domain}")
    logger.info(f"[APPS] PM2 data: {pm2_data}")
    if pm2_data:
        logger.info(f"[APPS] pm_uptime raw: {pm2_data.get('pm_uptime')}")

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

def _normalize_domain(project_domain: str) -> str:
    """Return the subdomain used in PM2 process names."""
    if project_domain and "." in project_domain:
        return project_domain.split(".")[0]
    return project_domain or ""


def _get_project_for_runtime_action(project_domain: str) -> Optional[Dict[str, Any]]:
    """Resolve a project by domain/name for backwards-compatible app actions."""
    normalized = _normalize_domain(project_domain)
    if not normalized:
        return None

    try:
        with get_db() as cur:
            cur.execute("""
                SELECT id, name, domain, type_id, project_path
                FROM projects
                WHERE domain = %s OR name = %s
                ORDER BY id DESC
                LIMIT 1
            """, (normalized, normalized))
            row = cur.fetchone()
            return dict(row) if row and not isinstance(row, dict) else row
    except Exception as e:
        logger.warning(f"Failed to resolve project for runtime action: {e}")
        return None


def _update_project_runtime_status(project_id: int, status: str) -> None:
    """Persist the project lifecycle status after a runtime action."""
    with get_db() as cur:
        cur.execute("UPDATE projects SET status = %s WHERE id = %s", (status, project_id))
        conn = cur._connection
        conn.commit()


def _run_pm2_action(process_names: List[str], action: str) -> Dict[str, Any]:
    """Execute a PM2 lifecycle command against one or more process names."""
    action_map = {
        "start": "start",
        "stop": "stop",
        "restart": "restart",
        "pause": "stop",
    }

    pm2_cmd = action_map.get(action)
    if not pm2_cmd:
        return {"success": False, "error": f"Unknown action: {action}"}

    results = []
    for proc_name in dict.fromkeys([name for name in process_names if name]):
        try:
            result = subprocess.run(
                ["pm2", pm2_cmd, proc_name],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                results.append({"process": proc_name, "success": True})
            else:
                results.append({
                    "process": proc_name,
                    "success": False,
                    "error": result.stderr or result.stdout
                })
        except subprocess.TimeoutExpired:
            results.append({"process": proc_name, "success": False, "error": "Timeout"})
        except Exception as e:
            results.append({"process": proc_name, "success": False, "error": str(e)})

    successes = [r for r in results if r.get("success")]
    if successes:
        global _pm2_cache
        _pm2_cache = {"data": None, "timestamp": 0}

        return {
            "success": True,
            "message": f"{action.capitalize()} successful for {len(successes)} process(es)",
            "details": results
        }

    return {
        "success": False,
        "error": f"Failed to {action} any processes",
        "details": results
    }


def _get_process_names_for_project(project: Dict[str, Any], fallback_domain: str) -> List[str]:
    """Return the PM2 process names for a project type."""
    project_id = project.get("id")
    type_id = project.get("type_id")
    domain = _normalize_domain(project.get("domain") or fallback_domain)

    if type_id == 1:
        # Website: only backend PM2 (frontend served by nginx static)
        return [f"{domain}-backend"]
    if type_id == 2:
        return [f"{domain}-bot", f"tg-bot-{project_id}"]
    if type_id == 3:
        return [f"dc-bot-{project_id}"]
    if type_id == 4:
        return [f"tg-bot-{project_id}"]
    if type_id == 6:
        return [f"{domain}-backend"]

    if domain:
        return [f"{domain}-frontend", f"{domain}-backend", f"{domain}-bot", f"{domain}-backend"]
    return [f"tg-bot-{project_id}"]


def _scheduler_project_action(project_id: int, action: str) -> Dict[str, Any]:
    """
    Pause/resume a scheduler project without stopping the shared clawd-scheduler PM2 process.

    Scheduler projects are served by one centralized worker, so pausing the project
    means pausing that project's jobs in the database.
    """
    try:
        if action in ("pause", "stop"):
            with get_db() as cur:
                cur.execute("""
                    UPDATE scheduler_jobs
                    SET status = 'paused'
                    WHERE project_id = %s AND status = 'active'
                """, (project_id,))
                paused_count = cur._cursor.rowcount
                conn = cur._connection
                conn.commit()

            _update_project_runtime_status(project_id, "stopped")
            return {
                "success": True,
                "message": f"Paused {paused_count} scheduler job(s)",
                "details": [{"project_id": project_id, "paused_jobs": paused_count}]
            }

        if action in ("start", "restart"):
            from services.scheduler.jobs import list_jobs, resume_job

            resumed_count = 0
            for job in list_jobs(project_id):
                if job.get("status") == "paused":
                    resume_job(int(job["id"]))
                    resumed_count += 1

            _update_project_runtime_status(project_id, "ready")
            return {
                "success": True,
                "message": f"Resumed {resumed_count} scheduler job(s)",
                "details": [{"project_id": project_id, "resumed_jobs": resumed_count}]
            }

        return {"success": False, "error": f"Unsupported scheduler action: {action}"}
    except Exception as e:
        logger.error(f"Scheduler project action failed: {e}")
        return {"success": False, "error": str(e)}


def _is_scheduler_family(type_id) -> bool:
    """Scheduler + agent projects share the central scheduler runtime —
    start/stop map to job pause/resume, never per-project PM2."""
    if type_id == 5:
        return True
    try:
        from database_postgres import get_db
        with get_db() as conn:
            row = conn.execute(
                "SELECT type FROM project_types WHERE id = %s", (type_id,)
            ).fetchone()
        d = (dict(row) if row and not isinstance(row, dict) else row) if row else {}
        return d.get("type") == "agent"
    except Exception:
        return False


def pm2_action(project_domain: str, action: str) -> Dict[str, Any]:
    """
    Execute a PM2 action on a project.
    
    Args:
        project_domain: Project domain (e.g., "crypto" or "crypto.{BASE_DOMAIN}")
        action: Action to perform (start, stop, restart)
    
    Returns:
        Dict with success status and message
    """
    project = _get_project_for_runtime_action(project_domain)

    if project and _is_scheduler_family(project.get("type_id")):
        return _scheduler_project_action(int(project["id"]), action)

    if project:
        process_names = _get_process_names_for_project(project, project_domain)
    else:
        normalized = _normalize_domain(project_domain)
        process_names = [f"{normalized}-frontend", f"{normalized}-backend"]

    result = _run_pm2_action(process_names, action)

    if result.get("success") and project:
        next_status = "stopped" if action in ("pause", "stop") else "ready"
        try:
            _update_project_runtime_status(int(project["id"]), next_status)
        except Exception as e:
            logger.warning(f"PM2 action succeeded but status update failed: {e}")
            result["status_warning"] = str(e)

    return result


# ============================================================================
# Response Models (for FastAPI)
# ============================================================================

from pydantic import BaseModel, Field


class AppItem(BaseModel):
    """Single app item in the apps list."""
    project_id: int = Field(..., description="Project ID")
    name: str = Field(..., description="Project name")
    type: str = Field(..., description="Project type (website, telegrambot, etc.)")
    status: str = Field(..., description="UI status (running, needs_fix, stopped, creating)")
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
