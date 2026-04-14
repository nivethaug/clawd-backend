"""
Tool Registry
Define all tool schemas for GLM function calling
"""

from typing import List, Dict, Any

# Tool categories
TOOLS_AUTO = [
    {
        "type": "function",
        "function": {
            "name": "start_project",
            "description": "Start PM2 services for a project (frontend and backend)",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project domain or ID"
                    }
                },
                "required": ["project_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "stop_project",
            "description": "Stop PM2 services for a project (frontend and backend)",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project domain or ID"
                    }
                },
                "required": ["project_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "restart_project",
            "description": "Restart PM2 services for a project (frontend and backend)",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project domain or ID"
                    }
                },
                "required": ["project_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_projects",
            "description": "List all active projects with their status",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "project_status",
            "description": "Get detailed status of a specific project (DB + PM2 services)",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project domain or ID"
                    }
                },
                "required": ["project_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_logs",
            "description": "Get PM2 logs for a project (frontend and backend)",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project domain or ID"
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Number of log lines to retrieve (default: 50)",
                        "default": 50
                    }
                },
                "required": ["project_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_active_project",
            "description": "Set or switch the active project context for the conversation. Use when user says 'switch to X', 'use X project', 'switch project' (without X), or explicitly wants to change context. If project_id is not provided, will show selection UI.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project domain to set as active (optional - if not provided, will show selection)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clear_active_project",
            "description": "Clear the active project context. Use when user says 'clear project', 'forget project', or wants to reset context.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_active_project",
            "description": "Get the current active project context. Use when user asks 'which project am I using', 'what's the current project', or wants to check context.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_project_info",
            "description": "Get detailed information about a project. Use when user asks 'what is X', 'tell me about X', 'project details', or wants to know about a specific project. Returns natural language response.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project domain (e.g., thinkai-likrt6). Optional - uses active project if not provided."
                    }
                },
                "required": []
            }
        }
    },

    # ============================================================
    # Scheduler Job Tools
    # ============================================================
    {
        "type": "function",
        "function": {
            "name": "scheduler_list_jobs",
            "description": "List all scheduled jobs for a scheduler project. Shows job type, schedule, status, task type, and payload. Use when user asks 'show my jobs', 'list jobs', 'what jobs do I have', 'scheduler status'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project domain or ID (uses active project if not provided)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scheduler_get_job",
            "description": "Get details of a specific scheduler job by ID. Use when user asks about a specific job's configuration or payload.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "integer",
                        "description": "Job ID to retrieve"
                    }
                },
                "required": ["job_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scheduler_create_job",
            "description": "Create a new scheduled job for a scheduler project. Supports interval (recurring), daily (at specific time), or once (one-time) schedules. Use when user says 'add job', 'schedule', 'create alert', 'send every X minutes'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project domain or ID (uses active project if not provided)"
                    },
                    "job_type": {
                        "type": "string",
                        "enum": ["interval", "daily", "once"],
                        "description": "Job type: interval (recurring), daily (at specific time), or once"
                    },
                    "schedule_value": {
                        "type": "string",
                        "description": "Schedule: '30s', '5m', '10m', '1h', '6h', '1d' for interval; 'daily:09:00' for daily"
                    },
                    "task_type": {
                        "type": "string",
                        "description": "Task type identifier (e.g., 'btc_alert', 'weather_update', 'email', 'telegram')"
                    },
                    "payload": {
                        "type": "object",
                        "description": "Job payload: {\"text\": \"message template\", \"fetch\": [\"btc_price\"], \"to\": \"email@example.com\", \"subject\": \"subject\"}",
                        "properties": {},
                        "additionalProperties": True
                    }
                },
                "required": ["job_type", "schedule_value", "task_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scheduler_update_job",
            "description": "Update an existing scheduler job's schedule, payload, or status. Use when user says 'change schedule', 'update job', 'edit job', 'change to every 10min'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "integer",
                        "description": "Job ID to update"
                    },
                    "schedule_value": {
                        "type": "string",
                        "description": "New schedule value (e.g., '10m', '1h', 'daily:09:00')"
                    },
                    "payload": {
                        "type": "object",
                        "description": "New payload (partial updates supported)",
                        "properties": {},
                        "additionalProperties": True
                    },
                    "status": {
                        "type": "string",
                        "enum": ["active", "paused"],
                        "description": "New status"
                    }
                },
                "required": ["job_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scheduler_pause_job",
            "description": "Pause an active scheduler job. It will stop executing until resumed. Use when user says 'pause job', 'stop job temporarily'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "integer",
                        "description": "Job ID to pause"
                    }
                },
                "required": ["job_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scheduler_resume_job",
            "description": "Resume a paused scheduler job. Use when user says 'resume job', 'restart job', 'unpause job'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "integer",
                        "description": "Job ID to resume"
                    }
                },
                "required": ["job_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scheduler_run_job",
            "description": "Trigger a scheduler job to run immediately (test/force execution). Use when user says 'test job', 'run now', 'trigger job'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "integer",
                        "description": "Job ID to trigger"
                    }
                },
                "required": ["job_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scheduler_job_logs",
            "description": "Get execution logs for a scheduler job. Shows status and messages from recent executions. Use when user asks 'job logs', 'execution history', 'did the job run', 'check job status'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "integer",
                        "description": "Job ID to get logs for"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max log entries to return (default: 20)",
                        "default": 20
                    }
                },
                "required": ["job_id"]
            }
        }
    }
]

TOOLS_CONFIRM = [
    {
        "type": "function",
        "function": {
            "name": "create_project",
            "description": "Create a new project with specified type and configuration",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Project name (e.g., 'My Crypto Bot')"
                    },
                    "domain": {
                        "type": "string",
                        "description": "Project domain (e.g., 'crypto-bot', 'my-website')"
                    },
                    "description": {
                        "type": "string",
                        "description": "Project description"
                    },
                    "project_type": {
                        "type": "string",
                        "enum": ["website", "telegram_bot", "discord_bot", "trading_bot", "scheduler", "custom"],
                        "description": "Type of project to create"
                    }
                },
                "required": ["name", "project_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "start_all_projects",
            "description": "Start PM2 services for ALL projects (bulk operation - requires confirmation)",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "stop_all_projects",
            "description": "Stop PM2 services for ALL projects (bulk operation - requires confirmation)",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "restart_all_projects",
            "description": "Restart PM2 services for ALL projects (bulk operation - requires confirmation)",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_project",
            "description": "Delete a project permanently (destructive operation - requires confirmation)",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project domain or ID to delete"
                    }
                },
                "required": ["project_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "uninstall_project",
            "description": "Uninstall/remove a project (destructive operation - requires confirmation)",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project domain or ID to uninstall"
                    }
                },
                "required": ["project_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remove_all_projects",
            "description": "Remove/delete ALL projects (destructive bulk operation - requires confirmation)",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },

    # ============================================================
    # Scheduler Job Tools (require confirmation)
    # ============================================================
    {
        "type": "function",
        "function": {
            "name": "scheduler_delete_job",
            "description": "Delete a scheduler job permanently (destructive - requires confirmation). Use when user says 'delete job', 'remove job'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "integer",
                        "description": "Job ID to delete"
                    }
                },
                "required": ["job_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scheduler_clear_jobs",
            "description": "Delete ALL scheduler jobs for a project (destructive bulk operation - requires confirmation). Use when user says 'delete all jobs', 'clear scheduler', 'remove all jobs'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project domain or ID (uses active project if not provided)"
                    }
                },
                "required": []
            }
        }
    }
]

TOOLS_DISABLED = []  # Remove delete_project from disabled - now requires confirmation


def get_all_tools() -> List[Dict[str, Any]]:
    """
    Get all tool definitions for GLM API.
    
    Returns:
        Combined list of auto-execute and confirmation-required tools
    """
    return TOOLS_AUTO + TOOLS_CONFIRM


def is_safe_tool(tool_name: str) -> bool:
    """
    Check if tool can be executed without confirmation.
    
    Args:
        tool_name: Name of the tool
        
    Returns:
        True if tool is safe to auto-execute
    """
    return any(
        tool["function"]["name"] == tool_name
        for tool in TOOLS_AUTO
    )


def requires_confirmation(tool_name: str) -> bool:
    """
    Check if tool requires user confirmation before execution.
    
    Args:
        tool_name: Name of the tool
        
    Returns:
        True if tool requires confirmation
    """
    return any(
        tool["function"]["name"] == tool_name
        for tool in TOOLS_CONFIRM
    )


def is_disabled(tool_name: str) -> bool:
    """
    Check if tool is disabled and should never be executed.
    
    Args:
        tool_name: Name of the tool
        
    Returns:
        True if tool is disabled
    """
    return tool_name in TOOLS_DISABLED


def get_tool_description(tool_name: str) -> str:
    """
    Get description of a tool by name.
    
    Args:
        tool_name: Name of the tool
        
    Returns:
        Tool description or empty string if not found
    """
    for tool in TOOLS_AUTO + TOOLS_CONFIRM:
        if tool["function"]["name"] == tool_name:
            return tool["function"]["description"]
    return ""


def validate_tool_args(tool_name: str, args: Dict[str, Any]) -> tuple[bool, str]:
    """
    Validate tool arguments against schema.
    
    Args:
        tool_name: Name of the tool
        args: Arguments to validate
        
    Returns:
        (is_valid, error_message)
    """
    # Find tool definition
    tool_def = None
    for tool in TOOLS_AUTO + TOOLS_CONFIRM:
        if tool["function"]["name"] == tool_name:
            tool_def = tool["function"]
            break
    
    if not tool_def:
        return False, f"Unknown tool: {tool_name}"
    
    # Check required parameters
    params = tool_def["parameters"]
    required = params.get("required", [])
    properties = params.get("properties", {})
    
    for req_param in required:
        if req_param not in args:
            return False, f"Missing required parameter: {req_param}"
    
    # Check parameter types (basic validation)
    for key, value in args.items():
        if key in properties:
            expected_type = properties[key].get("type")
            if expected_type == "string" and not isinstance(value, str):
                return False, f"Parameter '{key}' must be a string"
            elif expected_type == "integer" and not isinstance(value, int):
                return False, f"Parameter '{key}' must be an integer"
            elif expected_type == "array" and not isinstance(value, list):
                return False, f"Parameter '{key}' must be an array"
    
    return True, ""
