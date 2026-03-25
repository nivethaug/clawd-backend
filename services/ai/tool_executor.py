"""
Tool Executor
Execute tools via direct Python function calls to PM2 and database
"""

import json
import logging
import subprocess
from typing import Dict, Any, Optional

from database_postgres import get_db
from apps_service import pm2_action, get_pm2_processes
from services.ai.tool_registry import is_safe_tool, requires_confirmation, is_disabled

logger = logging.getLogger(__name__)


class ToolExecutor:
    """
    Execute DevOps tools via direct Python function calls.
    
    Integrates with:
    - apps_service: PM2 control functions
    - database_postgres: Project queries
    """
    
    async def execute(
        self,
        tool_name: str,
        args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute a tool with given arguments.
        
        Args:
            tool_name: Name of tool to execute
            args: Tool arguments
            
        Returns:
            {
                "status": "success" | "error" | "confirmation_required" | "disabled",
                "result": {...},
                "message": str
            }
        """
        logger.info(f"[TOOL-EXECUTOR] Executing tool: {tool_name} with args: {args}")
        
        # 1. Check if disabled
        if is_disabled(tool_name):
            logger.warning(f"[TOOL-EXECUTOR] Tool is disabled: {tool_name}")
            return {
                "status": "disabled",
                "message": f"Tool '{tool_name}' is disabled and cannot be executed"
            }
        
        # 2. Check if confirmation required
        if requires_confirmation(tool_name):
            logger.info(f"[TOOL-EXECUTOR] Tool requires confirmation: {tool_name}")
            return {
                "status": "confirmation_required",
                "message": f"Tool '{tool_name}' requires user confirmation",
                "intent": {
                    "tool": tool_name,
                    "args": args
                }
            }
        
        # 3. Validate tool is safe to execute
        if not is_safe_tool(tool_name):
            logger.error(f"[TOOL-EXECUTOR] Unknown tool: {tool_name}")
            return {
                "status": "error",
                "message": f"Unknown tool: {tool_name}"
            }
        
        # 4. Execute safe tool
        try:
            if tool_name == "start_project":
                return await self._execute_start_project(args)
            elif tool_name == "stop_project":
                return await self._execute_stop_project(args)
            elif tool_name == "restart_project":
                return await self._execute_restart_project(args)
            elif tool_name == "list_projects":
                return await self._execute_list_projects(args)
            elif tool_name == "project_status":
                return await self._execute_project_status(args)
            elif tool_name == "get_logs":
                return await self._execute_get_logs(args)
            else:
                return {
                    "status": "error",
                    "message": f"Tool implementation not found: {tool_name}"
                }
        except Exception as e:
            logger.error(f"[TOOL-EXECUTOR] Error executing {tool_name}: {e}")
            return {
                "status": "error",
                "message": f"Error executing tool: {str(e)}"
            }
    
    async def _execute_start_project(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Start PM2 services for a project."""
        project_id = args.get("project_id")
        if not project_id:
            return {"status": "error", "message": "Missing project_id"}
        
        # Extract domain (remove full domain if provided)
        domain = project_id.split(".")[0] if "." in project_id else project_id
        
        result = pm2_action(domain, "start")
        
        if result.get("success"):
            return {
                "status": "success",
                "message": f"Started project services for {domain}",
                "result": result
            }
        else:
            return {
                "status": "error",
                "message": result.get("error", "Failed to start project"),
                "result": result
            }
    
    async def _execute_stop_project(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Stop PM2 services for a project."""
        project_id = args.get("project_id")
        if not project_id:
            return {"status": "error", "message": "Missing project_id"}
        
        domain = project_id.split(".")[0] if "." in project_id else project_id
        
        result = pm2_action(domain, "stop")
        
        if result.get("success"):
            return {
                "status": "success",
                "message": f"Stopped project services for {domain}",
                "result": result
            }
        else:
            return {
                "status": "error",
                "message": result.get("error", "Failed to stop project"),
                "result": result
            }
    
    async def _execute_restart_project(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Restart PM2 services for a project."""
        project_id = args.get("project_id")
        if not project_id:
            return {"status": "error", "message": "Missing project_id"}
        
        domain = project_id.split(".")[0] if "." in project_id else project_id
        
        result = pm2_action(domain, "restart")
        
        if result.get("success"):
            return {
                "status": "success",
                "message": f"Restarted project services for {domain}",
                "result": result
            }
        else:
            return {
                "status": "error",
                "message": result.get("error", "Failed to restart project"),
                "result": result
            }
    
    async def _execute_list_projects(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List all active projects."""
        with get_db() as conn:
            result = conn.execute("""
                SELECT p.id, p.name, p.domain, p.status, p.created_at,
                       pt.display_name as type_name
                FROM projects p
                LEFT JOIN project_types pt ON p.type_id = pt.id
                WHERE p.status != %s
                ORDER BY p.created_at DESC
            """, ("deleted",)).fetchall()
            
            projects = [dict(row) for row in result]
            
            return {
                "status": "success",
                "message": f"Found {len(projects)} active projects",
                "result": {"projects": projects}
            }
    
    async def _execute_project_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get detailed status of a project."""
        project_id = args.get("project_id")
        if not project_id:
            return {"status": "error", "message": "Missing project_id"}
        
        with get_db() as conn:
            # Get project from DB
            result = conn.execute("""
                SELECT p.*, pt.display_name as type_name
                FROM projects p
                LEFT JOIN project_types pt ON p.type_id = pt.id
                WHERE p.domain = %s OR p.id = %s
                LIMIT 1
            """, (project_id, project_id)).fetchone()
            
            if not result:
                return {
                    "status": "error",
                    "message": f"Project '{project_id}' not found"
                }
            
            project = dict(result)
            domain = project["domain"]
            
            # Get PM2 status
            pm2_processes = get_pm2_processes()
            running = pm2_processes.get("running", [])
            
            frontend_status = "stopped"
            backend_status = "stopped"
            
            for proc in running:
                if proc.get("name") == f"{domain}-frontend":
                    frontend_status = "running"
                elif proc.get("name") == f"{domain}-backend":
                    backend_status = "running"
            
            return {
                "status": "success",
                "message": f"Status for project: {project['name']}",
                "result": {
                    "project": project,
                    "services": {
                        "frontend": frontend_status,
                        "backend": backend_status
                    }
                }
            }
    
    async def _execute_get_logs(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get PM2 logs for a project."""
        project_id = args.get("project_id")
        lines = args.get("lines", 50)
        
        if not project_id:
            return {"status": "error", "message": "Missing project_id"}
        
        domain = project_id.split(".")[0] if "." in project_id else project_id
        
        logs = {"frontend": "", "backend": ""}
        
        # Get frontend logs
        try:
            result = subprocess.run(
                ["pm2", "logs", f"{domain}-frontend", "--lines", str(lines), "--nostream"],
                capture_output=True,
                text=True,
                timeout=10
            )
            logs["frontend"] = result.stdout[-5000:]  # Limit size
        except Exception as e:
            logs["frontend"] = f"Error retrieving logs: {e}"
        
        # Get backend logs
        try:
            result = subprocess.run(
                ["pm2", "logs", f"{domain}-backend", "--lines", str(lines), "--nostream"],
                capture_output=True,
                text=True,
                timeout=10
            )
            logs["backend"] = result.stdout[-5000:]  # Limit size
        except Exception as e:
            logs["backend"] = f"Error retrieving logs: {e}"
        
        return {
            "status": "success",
            "message": f"Logs for project: {domain}",
            "result": {"logs": logs}
        }


# Singleton instance
_executor: Optional[ToolExecutor] = None


def get_tool_executor() -> ToolExecutor:
    """Get or create tool executor singleton."""
    global _executor
    if _executor is None:
        _executor = ToolExecutor()
    return _executor
