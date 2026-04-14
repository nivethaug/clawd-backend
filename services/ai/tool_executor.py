"""
Tool Executor
Execute tools via direct Python function calls to PM2 and database
"""

import json
import logging
import os
import subprocess
from typing import Dict, Any, Optional

from database_postgres import get_db
from apps_service import pm2_action, get_pm2_processes
from services.ai.tool_registry import is_safe_tool, requires_confirmation, is_disabled
from utils.ai_session_manager import get_session_manager

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
        args: Dict[str, Any],
        session_key: str = None
    ) -> Dict[str, Any]:
        """
        Execute a tool with given arguments.
        
        Args:
            tool_name: Name of tool to execute
            args: Tool arguments
            session_key: Session identifier (required for context management tools)
            
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
            elif tool_name == "delete_project":
                return await self._execute_delete_project(args)
            elif tool_name == "start_all_projects":
                return await self._execute_start_all_projects(args)
            elif tool_name == "stop_all_projects":
                return await self._execute_stop_all_projects(args)
            elif tool_name == "remove_all_projects":
                return await self._execute_remove_all_projects(args)
            elif tool_name == "set_active_project":
                return await self._execute_set_active_project(args, session_key)
            elif tool_name == "clear_active_project":
                return await self._execute_clear_active_project(args, session_key)
            elif tool_name == "get_active_project":
                return await self._execute_get_active_project(args, session_key)
            elif tool_name == "get_project_info":
                return await self._execute_get_project_info(args, session_key)
            elif tool_name == "scheduler_list_jobs":
                return await self._execute_scheduler_list_jobs(args, session_key)
            elif tool_name == "scheduler_get_job":
                return await self._execute_scheduler_get_job(args)
            elif tool_name == "scheduler_create_job":
                return await self._execute_scheduler_create_job(args, session_key)
            elif tool_name == "scheduler_update_job":
                return await self._execute_scheduler_update_job(args)
            elif tool_name == "scheduler_pause_job":
                return await self._execute_scheduler_pause_job(args)
            elif tool_name == "scheduler_resume_job":
                return await self._execute_scheduler_resume_job(args)
            elif tool_name == "scheduler_run_job":
                return await self._execute_scheduler_run_job(args)
            elif tool_name == "scheduler_job_logs":
                return await self._execute_scheduler_job_logs(args)
            elif tool_name == "scheduler_delete_job":
                return await self._execute_scheduler_delete_job(args)
            elif tool_name == "scheduler_clear_jobs":
                return await self._execute_scheduler_clear_jobs(args, session_key)
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
        """Start PM2 services for a project (uses restart for robustness)."""
        project_id = args.get("project_id")
        if not project_id:
            return {"status": "error", "message": "Missing project_id"}
        
        # Extract domain (remove full domain if provided)
        domain = project_id.split(".")[0] if "." in project_id else project_id
        
        # Use restart instead of start - works whether process is running or stopped
        result = pm2_action(domain, "restart")
        
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
            # Get project from DB - try domain first, then numeric ID if applicable
            result = conn.execute("""
                SELECT p.*, pt.display_name as type_name
                FROM projects p
                LEFT JOIN project_types pt ON p.type_id = pt.id
                WHERE p.domain = %s
                LIMIT 1
            """, (project_id,)).fetchone()
            
            # Fallback: try numeric ID if domain not found and input is numeric
            if not result and project_id.isdigit():
                result = conn.execute("""
                    SELECT p.*, pt.display_name as type_name
                    FROM projects p
                    LEFT JOIN project_types pt ON p.type_id = pt.id
                    WHERE p.id = %s
                    LIMIT 1
                """, (int(project_id),)).fetchone()
            
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
        """Get PM2 logs for a project by reading log files directly."""
        project_id = args.get("project_id")
        lines = args.get("lines", 50)
        
        if not project_id:
            return {"status": "error", "message": "Missing project_id"}
        
        domain = project_id.split(".")[0] if "." in project_id else project_id
        
        logs = {"frontend": {"out": "", "error": ""}, "backend": {"out": "", "error": ""}}
        
        # Read log files directly from PM2 log directory
        log_dir = "/root/.pm2/logs"
        
        # Frontend logs
        try:
            # Frontend out log
            frontend_out_file = f"{log_dir}/{domain}-frontend-out.log"
            result = subprocess.run(
                ["tail", f"-n{lines}", frontend_out_file],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                logs["frontend"]["out"] = result.stdout.strip()
            
            # Frontend error log
            frontend_err_file = f"{log_dir}/{domain}-frontend-error.log"
            result = subprocess.run(
                ["tail", f"-n{lines}", frontend_err_file],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                logs["frontend"]["error"] = result.stdout.strip()
                
        except Exception as e:
            logger.error(f"Error reading frontend logs: {e}")
            logs["frontend"]["error"] = f"Error reading logs: {e}"
        
        # Backend logs
        try:
            # Find backend log file (may have a number suffix)
            backend_out_files = []
            backend_err_files = []
            
            # List all log files to find backend logs
            try:
                all_files = os.listdir(log_dir)
                for f in all_files:
                    if f.startswith(f"{domain}-backend-out"):
                        backend_out_files.append(f)
                    elif f.startswith(f"{domain}-backend-error"):
                        backend_err_files.append(f)
            except Exception as e:
                logger.error(f"Error listing log directory: {e}")
            
            # Read the most recent backend out log
            if backend_out_files:
                backend_out_files.sort(reverse=True)  # Most recent first
                latest_out = backend_out_files[0]
                result = subprocess.run(
                    ["tail", f"-n{lines}", f"{log_dir}/{latest_out}"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    logs["backend"]["out"] = result.stdout.strip()
            
            # Read the most recent backend error log
            if backend_err_files:
                backend_err_files.sort(reverse=True)  # Most recent first
                latest_err = backend_err_files[0]
                result = subprocess.run(
                    ["tail", f"-n{lines}", f"{log_dir}/{latest_err}"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    logs["backend"]["error"] = result.stdout.strip()
                
        except Exception as e:
            logger.error(f"Error reading backend logs: {e}")
            logs["backend"]["error"] = f"Error reading logs: {e}"
        
        # Format log summary
        log_summary = []
        if logs["frontend"]["out"]:
            log_summary.append(f"Frontend (stdout):\n{logs['frontend']['out']}")
        if logs["frontend"]["error"]:
            log_summary.append(f"Frontend (stderr):\n{logs['frontend']['error']}")
        if logs["backend"]["out"]:
            log_summary.append(f"Backend (stdout):\n{logs['backend']['out']}")
        if logs["backend"]["error"]:
            log_summary.append(f"Backend (stderr):\n{logs['backend']['error']}")
        
        if not log_summary:
            log_summary = ["No logs found"]
        
        return {
            "status": "success",
            "message": f"Logs for {domain} (last {lines} lines)",
            "result": {
                "logs": "\n\n".join(log_summary),
                "lines_requested": lines,
                "domain": domain
            }
        }
    
    async def _execute_delete_project(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Delete a project (soft delete)."""
        project_id = args.get("project_id")
        if not project_id:
            return {"status": "error", "message": "Missing project_id"}
        
        domain = project_id.split(".")[0] if "." in project_id else project_id
        
        with get_db() as conn:
            # Check if project exists - try domain first
            result = conn.execute(
                "SELECT id, name, domain FROM projects WHERE domain = %s",
                (domain,)
            ).fetchone()
            
            # Fallback: try numeric ID if domain not found and input is numeric
            if not result and domain.isdigit():
                result = conn.execute(
                    "SELECT id, name, domain FROM projects WHERE id = %s",
                    (int(domain),)
                ).fetchone()
            
            if not result:
                return {
                    "status": "error",
                    "message": f"Project '{project_id}' not found"
                }
            
            # Soft delete
            conn.execute(
                "UPDATE projects SET status = 'deleted' WHERE id = %s",
                (result["id"],)
            )
            
            # Stop PM2 services if running
            pm2_action(domain, "delete")
            
            return {
                "status": "success",
                "message": f"Deleted project: {result['name']}",
                "result": {"project_id": result["id"]}
            }
    
    async def _execute_start_all_projects(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Start all projects."""
        with get_db() as conn:
            result = conn.execute(
                "SELECT domain FROM projects WHERE status != 'deleted'"
            ).fetchall()
            
            domains = [row["domain"] for row in result]
            started = []
            failed = []
            
            for domain in domains:
                try:
                    pm2_result = pm2_action(domain, "start")
                    if pm2_result.get("success"):
                        started.append(domain)
                    else:
                        failed.append(domain)
                except Exception as e:
                    logger.error(f"Failed to start {domain}: {e}")
                    failed.append(domain)
            
            return {
                "status": "success",
                "message": f"Started {len(started)} projects. Failed: {len(failed)}",
                "result": {
                    "started": started,
                    "failed": failed
                }
            }
    
    async def _execute_stop_all_projects(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Stop all projects."""
        with get_db() as conn:
            result = conn.execute(
                "SELECT domain FROM projects WHERE status != 'deleted'"
            ).fetchall()
            
            domains = [row["domain"] for row in result]
            stopped = []
            failed = []
            
            for domain in domains:
                try:
                    pm2_result = pm2_action(domain, "stop")
                    if pm2_result.get("success"):
                        stopped.append(domain)
                    else:
                        failed.append(domain)
                except Exception as e:
                    logger.error(f"Failed to stop {domain}: {e}")
                    failed.append(domain)
            
            return {
                "status": "success",
                "message": f"Stopped {len(stopped)} projects. Failed: {len(failed)}",
                "result": {
                    "stopped": stopped,
                    "failed": failed
                }
            }
    
    async def _execute_remove_all_projects(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Remove all projects (soft delete)."""
        with get_db() as conn:
            result = conn.execute(
                "SELECT id, domain FROM projects WHERE status != 'deleted'"
            ).fetchall()
            
            removed = []
            failed = []
            
            for row in result:
                try:
                    # Soft delete
                    conn.execute(
                        "UPDATE projects SET status = 'deleted' WHERE id = %s",
                        (row["id"],)
                    )
                    
                    # Stop PM2
                    pm2_action(row["domain"], "delete")
                    
                    removed.append(row["domain"])
                except Exception as e:
                    logger.error(f"Failed to remove {row['domain']}: {e}")
                    failed.append(row["domain"])
            
            return {
                "status": "success",
                "message": f"Removed {len(removed)} projects. Failed: {len(failed)}",
                "result": {
                    "removed": removed,
                    "failed": failed
                }
            }
    
    async def _execute_set_active_project(
        self,
        args: Dict[str, Any],
        session_key: str = None
    ) -> Dict[str, Any]:
        """
        Set active project for session.
        
        Args:
            args: Must contain project_id
            session_key: Session identifier (injected by caller)
        """
        project_id = args.get("project_id")
        if not project_id:
            return {"status": "error", "message": "Missing project_id"}
        
        if not session_key:
            return {"status": "error", "message": "Missing session context"}
        
        # Resolve project from DB
        domain = project_id.split(".")[0] if "." in project_id else project_id
        
        # Try domain first, then numeric ID if applicable
        with get_db() as conn:
            result = conn.execute(
                "SELECT id, name, domain FROM projects WHERE domain = %s",
                (domain,)
            ).fetchone()
            
            # Fallback: try numeric ID if domain not found and input is numeric
            if not result and domain.isdigit():
                result = conn.execute(
                    "SELECT id, name, domain FROM projects WHERE id = %s",
                    (int(domain),)
                ).fetchone()
            
            if not result:
                return {
                    "status": "error",
                    "message": f"Project '{project_id}' not found"
                }
            
            project = dict(result)
        
        # Update session (store domain, not numeric ID)
        session_manager = get_session_manager()
        await session_manager.set_active_project(session_key, project["domain"])
        
        return {
            "status": "success",
            "message": f"Switched to {project['name']} project ✅",
            "result": {
                "project_id": project["domain"],
                "project_name": project["name"],
                "project_domain": project["domain"]
            }
        }
    
    async def _execute_clear_active_project(
        self,
        args: Dict[str, Any],
        session_key: str = None
    ) -> Dict[str, Any]:
        """
        Clear active project for session.
        
        Args:
            args: No parameters required
            session_key: Session identifier (injected by caller)
        """
        if not session_key:
            return {"status": "error", "message": "Missing session context"}
        
        session_manager = get_session_manager()
        await session_manager.clear_active_project(session_key)
        
        return {
            "status": "success",
            "message": "Cleared active project. I'll ask when needed.",
            "result": {"active_project_id": None}
        }
    
    async def _execute_get_active_project(
        self,
        args: Dict[str, Any],
        session_key: str = None
    ) -> Dict[str, Any]:
        """
        Get active project for session.
        
        Args:
            args: No parameters required
            session_key: Session identifier (injected by caller)
        """
        if not session_key:
            return {"status": "error", "message": "Missing session context"}
        
        session_manager = get_session_manager()
        project = await session_manager.get_active_project(session_key)
        
        if not project:
            return {
                "status": "success",
                "message": "No active project set. Please select a project first.",
                "result": {"active_project": None}
            }
        
        return {
            "status": "success",
            "message": f"Active project: {project['name']}",
            "result": {
                "active_project": {
                    "id": project.get("id"),
                    "name": project.get("name"),
                    "domain": project.get("domain")
                }
            }
        }
    
    async def _execute_get_project_info(
        self,
        args: Dict[str, Any],
        session_key: str = None
    ) -> Dict[str, Any]:
        """
        Get detailed information about a project.
        
        Uses domain-only identification and returns natural language response.
        
        Args:
            args: Optional project_id (domain string)
            session_key: Session identifier for active project fallback
        """
        project_id = args.get("project_id")
        
        # Fallback to active project if not provided
        if not project_id and session_key:
            session_manager = get_session_manager()
            active_project = await session_manager.get_active_project(session_key)
            if active_project:
                project_id = active_project.get("domain")
        
        if not project_id:
            return {
                "status": "error",
                "message": "No project selected. Please specify a project or set an active project first."
            }
        
        # Extract domain (remove full domain if provided)
        domain = project_id.split(".")[0] if "." in project_id else project_id
        
        # Query project by domain ONLY (no numeric ID support)
        with get_db() as conn:
            result = conn.execute("""
                SELECT p.*, pt.display_name as type_name, pt.type as type_slug
                FROM projects p
                LEFT JOIN project_types pt ON p.type_id = pt.id
                WHERE p.domain = %s
                LIMIT 1
            """, (domain,)).fetchone()
            
            if not result:
                return {
                    "status": "error",
                    "message": f"Project '{domain}' not found"
                }
            
            project = dict(result)
        
        # Get PM2 status for additional context
        pm2_processes = get_pm2_processes()
        running = pm2_processes.get("running", [])
        
        frontend_running = any(proc.get("name") == f"{domain}-frontend" for proc in running)
        backend_running = any(proc.get("name") == f"{domain}-backend" for proc in running)
        
        # Determine overall status
        if frontend_running and backend_running:
            service_status = "running"
        elif frontend_running or backend_running:
            service_status = "partially running"
        else:
            service_status = "stopped"
        
        # Build natural language response
        project_name = project.get("name", domain)
        project_type = project.get("type_name", "project")
        description = project.get("description", "")
        status = project.get("status", service_status)
        
        # Generate human-friendly text
        text_parts = [f"{project_name} is a {project_type} project"]
        
        # Add status
        if status == "running":
            text_parts.append("that is currently running")
        elif status == "stopped":
            text_parts.append("that is currently stopped")
        elif status == "creating":
            text_parts.append("that is currently being created")
        else:
            text_parts.append(f"with status: {status}")
        
        # Add frontend URL if available
        frontend_url = f"https://{domain}.dreambigwithai.com"  # Adjust based on your domain
        text_parts.append(f"Access it at {frontend_url}")
        
        # Add description if available
        if description:
            text_parts.append(description)
        
        # Add services info
        if frontend_running and backend_running:
            text_parts.append("Both frontend and backend services are running")
        elif frontend_running:
            text_parts.append("Frontend is running, backend is stopped")
        elif backend_running:
            text_parts.append("Backend is running, frontend is stopped")
        
        text = ". ".join(text_parts) + "."
        
        return {
            "status": "success",
            "type": "text",  # Important: return text, not execution
            "message": text,
            "result": {
                "project": {
                    "name": project_name,
                    "domain": domain,
                    "type": project_type,
                    "description": description,
                    "status": status,
                    "frontend_url": frontend_url,
                    "services": {
                        "frontend": "running" if frontend_running else "stopped",
                        "backend": "running" if backend_running else "stopped"
                    }
                }
            }
        }

    # ================================================================
    # Scheduler Job Tools
    # ================================================================

    def _resolve_project_to_id(self, project_id: str, session_key: str = None) -> Optional[int]:
        """Resolve project domain or string ID to numeric database ID."""
        domain = project_id.split(".")[0] if "." in project_id else project_id

        with get_db() as conn:
            # Try domain first
            result = conn.execute(
                "SELECT id FROM projects WHERE domain = %s",
                (domain,)
            ).fetchone()

            if result:
                return result["id"] if isinstance(result, dict) else result[0]

            # Try numeric ID
            if domain.isdigit():
                result = conn.execute(
                    "SELECT id FROM projects WHERE id = %s",
                    (int(domain),)
                ).fetchone()
                if result:
                    return result["id"] if isinstance(result, dict) else result[0]

        return None

    async def _execute_scheduler_list_jobs(
        self, args: Dict[str, Any], session_key: str = None
    ) -> Dict[str, Any]:
        """List all scheduled jobs for a project."""
        project_id = args.get("project_id")

        # Fallback to active project
        if not project_id and session_key:
            session_manager = get_session_manager()
            active_project = await session_manager.get_active_project(session_key)
            if active_project:
                project_id = active_project.get("domain")

        if not project_id:
            return {"status": "error", "message": "No project specified. Please specify a project or set an active project."}

        numeric_id = self._resolve_project_to_id(project_id, session_key)
        if not numeric_id:
            return {"status": "error", "message": f"Project '{project_id}' not found"}

        try:
            from services.scheduler import list_jobs as scheduler_list_jobs
            jobs = scheduler_list_jobs(numeric_id)

            if not jobs:
                return {
                    "status": "success",
                    "message": f"No scheduled jobs found for project {project_id}",
                    "result": {"jobs": [], "count": 0}
                }

            # Summarize jobs for readability
            job_summaries = []
            for job in jobs:
                job_summaries.append({
                    "id": job.get("id"),
                    "task_type": job.get("task_type"),
                    "job_type": job.get("job_type"),
                    "schedule": job.get("schedule_value"),
                    "status": job.get("status"),
                    "payload": job.get("payload"),
                    "last_run": job.get("last_run_at"),
                    "next_run": job.get("next_run_at"),
                })

            return {
                "status": "success",
                "message": f"Found {len(jobs)} job(s) for project {project_id}",
                "result": {"jobs": job_summaries, "count": len(jobs)}
            }
        except Exception as e:
            logger.error(f"Error listing scheduler jobs: {e}")
            return {"status": "error", "message": f"Failed to list jobs: {str(e)}"}

    async def _execute_scheduler_get_job(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get details of a specific scheduler job."""
        job_id = args.get("job_id")
        if not job_id:
            return {"status": "error", "message": "Missing job_id"}

        try:
            from services.scheduler import get_job as scheduler_get_job
            job = scheduler_get_job(int(job_id))

            if not job:
                return {"status": "error", "message": f"Job {job_id} not found"}

            return {
                "status": "success",
                "message": f"Job {job_id} details",
                "result": {"job": job}
            }
        except Exception as e:
            logger.error(f"Error getting scheduler job: {e}")
            return {"status": "error", "message": f"Failed to get job: {str(e)}"}

    async def _execute_scheduler_create_job(
        self, args: Dict[str, Any], session_key: str = None
    ) -> Dict[str, Any]:
        """Create a new scheduled job."""
        project_id = args.get("project_id")
        job_type = args.get("job_type")
        schedule_value = args.get("schedule_value")
        task_type = args.get("task_type")
        payload = args.get("payload", {})

        if not job_type or not schedule_value or not task_type:
            return {"status": "error", "message": "Missing required fields: job_type, schedule_value, task_type"}

        # Fallback to active project
        if not project_id and session_key:
            session_manager = get_session_manager()
            active_project = await session_manager.get_active_project(session_key)
            if active_project:
                project_id = active_project.get("domain")

        if not project_id:
            return {"status": "error", "message": "No project specified. Please specify a project or set an active project."}

        numeric_id = self._resolve_project_to_id(project_id, session_key)
        if not numeric_id:
            return {"status": "error", "message": f"Project '{project_id}' not found"}

        try:
            from services.scheduler import create_job as scheduler_create_job
            job = scheduler_create_job(project_id=numeric_id, job_data={
                "job_type": job_type,
                "schedule_value": schedule_value,
                "task_type": task_type,
                "payload": payload,
            })

            return {
                "status": "success",
                "message": f"Created {job_type} job '{task_type}' scheduled every {schedule_value}",
                "result": {"job": job}
            }
        except ValueError as e:
            return {"status": "error", "message": str(e)}
        except RuntimeError as e:
            return {"status": "error", "message": f"Rate limited: {str(e)}"}
        except Exception as e:
            logger.error(f"Error creating scheduler job: {e}")
            return {"status": "error", "message": f"Failed to create job: {str(e)}"}

    async def _execute_scheduler_update_job(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing scheduler job."""
        job_id = args.get("job_id")
        if not job_id:
            return {"status": "error", "message": "Missing job_id"}

        updates = {}
        if args.get("schedule_value"):
            updates["schedule_value"] = args["schedule_value"]
        if args.get("payload"):
            updates["payload"] = args["payload"]
        if args.get("status"):
            updates["status"] = args["status"]

        if not updates:
            return {"status": "error", "message": "No fields to update. Provide schedule_value, payload, or status."}

        try:
            from services.scheduler import update_job as scheduler_update_job
            job = scheduler_update_job(int(job_id), updates)

            return {
                "status": "success",
                "message": f"Updated job {job_id}: {', '.join(updates.keys())}",
                "result": {"job": job}
            }
        except ValueError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            logger.error(f"Error updating scheduler job: {e}")
            return {"status": "error", "message": f"Failed to update job: {str(e)}"}

    async def _execute_scheduler_pause_job(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Pause an active scheduler job."""
        job_id = args.get("job_id")
        if not job_id:
            return {"status": "error", "message": "Missing job_id"}

        try:
            from services.scheduler import pause_job as scheduler_pause_job, get_job as scheduler_get_job
            job = scheduler_get_job(int(job_id))
            if not job:
                return {"status": "error", "message": f"Job {job_id} not found"}
            if job.get("status") != "active":
                return {"status": "error", "message": f"Job {job_id} is already {job.get('status')}"}

            scheduler_pause_job(int(job_id))

            return {
                "status": "success",
                "message": f"Paused job {job_id} ({job.get('task_type', 'unknown')})",
                "result": {"job_id": int(job_id), "status": "paused"}
            }
        except Exception as e:
            logger.error(f"Error pausing scheduler job: {e}")
            return {"status": "error", "message": f"Failed to pause job: {str(e)}"}

    async def _execute_scheduler_resume_job(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Resume a paused scheduler job."""
        job_id = args.get("job_id")
        if not job_id:
            return {"status": "error", "message": "Missing job_id"}

        try:
            from services.scheduler import resume_job as scheduler_resume_job
            scheduler_resume_job(int(job_id))

            return {
                "status": "success",
                "message": f"Resumed job {job_id}",
                "result": {"job_id": int(job_id), "status": "active"}
            }
        except ValueError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            logger.error(f"Error resuming scheduler job: {e}")
            return {"status": "error", "message": f"Failed to resume job: {str(e)}"}

    async def _execute_scheduler_run_job(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Trigger a scheduler job to run immediately."""
        job_id = args.get("job_id")
        if not job_id:
            return {"status": "error", "message": "Missing job_id"}

        try:
            from services.scheduler import run_job_now as scheduler_run_job_now
            job = scheduler_run_job_now(int(job_id))

            return {
                "status": "success",
                "message": f"Triggered job {job_id} for immediate execution",
                "result": {"job": job}
            }
        except ValueError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            logger.error(f"Error running scheduler job: {e}")
            return {"status": "error", "message": f"Failed to trigger job: {str(e)}"}

    async def _execute_scheduler_job_logs(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get execution logs for a scheduler job."""
        job_id = args.get("job_id")
        limit = args.get("limit", 20)
        if not job_id:
            return {"status": "error", "message": "Missing job_id"}

        try:
            with get_db() as cur:
                cur.execute("""
                    SELECT id, job_id, status, message, created_at
                    FROM scheduler_logs
                    WHERE job_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (int(job_id), limit))
                rows = cur.fetchall()
                logs = [dict(r) for r in rows]

            if not logs:
                return {
                    "status": "success",
                    "message": f"No execution logs found for job {job_id}",
                    "result": {"logs": [], "count": 0}
                }

            return {
                "status": "success",
                "message": f"Found {len(logs)} log entries for job {job_id}",
                "result": {"logs": logs, "count": len(logs)}
            }
        except Exception as e:
            logger.error(f"Error getting scheduler job logs: {e}")
            return {"status": "error", "message": f"Failed to get logs: {str(e)}"}

    async def _execute_scheduler_delete_job(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Delete a scheduler job permanently."""
        job_id = args.get("job_id")
        if not job_id:
            return {"status": "error", "message": "Missing job_id"}

        try:
            from services.scheduler import delete_job as scheduler_delete_job
            deleted = scheduler_delete_job(int(job_id))

            if not deleted:
                return {"status": "error", "message": f"Job {job_id} not found"}

            return {
                "status": "success",
                "message": f"Deleted job {job_id}",
                "result": {"job_id": int(job_id)}
            }
        except Exception as e:
            logger.error(f"Error deleting scheduler job: {e}")
            return {"status": "error", "message": f"Failed to delete job: {str(e)}"}

    async def _execute_scheduler_clear_jobs(
        self, args: Dict[str, Any], session_key: str = None
    ) -> Dict[str, Any]:
        """Delete all jobs for a project."""
        project_id = args.get("project_id")

        # Fallback to active project
        if not project_id and session_key:
            session_manager = get_session_manager()
            active_project = await session_manager.get_active_project(session_key)
            if active_project:
                project_id = active_project.get("domain")

        if not project_id:
            return {"status": "error", "message": "No project specified."}

        numeric_id = self._resolve_project_to_id(project_id, session_key)
        if not numeric_id:
            return {"status": "error", "message": f"Project '{project_id}' not found"}

        try:
            from services.scheduler import clear_jobs as scheduler_clear_jobs
            count = scheduler_clear_jobs(numeric_id)

            return {
                "status": "success",
                "message": f"Deleted {count} job(s) for project {project_id}",
                "result": {"deleted_count": count}
            }
        except Exception as e:
            logger.error(f"Error clearing scheduler jobs: {e}")
            return {"status": "error", "message": f"Failed to clear jobs: {str(e)}"}


# Singleton instance
_executor: Optional[ToolExecutor] = None


def get_tool_executor() -> ToolExecutor:
    """Get or create tool executor singleton."""
    global _executor
    if _executor is None:
        _executor = ToolExecutor()
    return _executor
