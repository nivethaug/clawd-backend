"""
AI Confirm API
Handle user confirmation/cancel for dangerous operations
"""

import logging
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.ai.tool_executor import get_tool_executor
from services.ai.tool_registry import requires_confirmation
from utils.ai_response_formatter import text_response, execution_response, error_response
from utils.ai_session_manager import get_session_manager

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================

class AIConfirmRequest(BaseModel):
    """Confirmation request model."""
    session_id: str = Field(..., description="Session identifier")
    confirmed: bool = Field(..., description="True to confirm, False to cancel")


class AIConfirmResponse(BaseModel):
    """Confirmation response model."""
    type: str = Field(..., description="Response type")
    text: Optional[str] = Field(None)
    progress: Optional[List[Dict[str, Any]]] = Field(None)
    message: Optional[str] = Field(None)
    details: Optional[Dict[str, Any]] = Field(None)


# ============================================================================
# Confirmation Endpoint
# ============================================================================

@router.post("/confirm", response_model=AIConfirmResponse)
async def ai_confirm(request: AIConfirmRequest):
    """
    Handle user confirmation/cancel for dangerous operations.
    
    Flow:
    1. Retrieve pending intent from session
    2. If confirmed: execute tool
    3. If cancelled: clear intent, return cancellation message
    """
    try:
        logger.info(f"[AI-CONFIRM] Session {request.session_id}, confirmed={request.confirmed}")
        
        # Get pending intent from session
        session_manager = get_session_manager()
        intent = await session_manager.get_pending_intent(request.session_id)
        
        if not intent:
            return {
                "type": "error",
                "text": None,
                "progress": None,
                "message": "No pending operation to confirm",
                "details": None
            }
        
        tool_name = intent.get("tool")
        args = intent.get("args", {})
        
        logger.info(f"[AI-CONFIRM] Pending intent: {tool_name}")
        
        if request.confirmed:
            # User confirmed - execute tool
            logger.info(f"[AI-CONFIRM] Executing confirmed tool: {tool_name}")
            
            # Validate tool requires confirmation
            if not requires_confirmation(tool_name):
                await session_manager.clear_pending_intent(request.session_id)
                return error_response(f"Tool '{tool_name}' does not require confirmation")
            
            # Execute tool
            executor = get_tool_executor()
            
            # For tools that need special handling (create_project, start_all, stop_all)
            # We need to implement them differently since they're not in executor yet
            
            if tool_name == "create_project":
                # Create project - would need to call project_manager
                # For now, return message that this is not yet implemented
                await session_manager.clear_pending_intent(request.session_id)
                return {
                    "type": "execution",
                    "text": f"Creating project: {args.get('name')} (not yet implemented)",
                    "progress": [{"status": "success", "message": "Project creation initiated"}],
                    "message": "Project creation feature coming soon",
                    "details": args
                }
            
            elif tool_name == "start_all_projects":
                # Start all projects
                await session_manager.clear_pending_intent(request.session_id)
                
                from database_postgres import get_db
                from apps_service import pm2_action
                
                with get_db() as conn:
                    result = conn.execute(
                        "SELECT domain FROM projects WHERE status != %s",
                        ("deleted",)
                    ).fetchall()
                    
                    projects = [row["domain"] for row in result]
                
                successes = 0
                for domain in projects:
                    res = pm2_action(domain, "start")
                    if res.get("success"):
                        successes += 1
                
                return {
                    "type": "execution",
                    "text": f"Started {successes}/{len(projects)} projects",
                    "progress": [{"status": "success", "count": successes, "total": len(projects)}],
                    "message": f"Started {successes} out of {len(projects)} projects",
                    "details": None
                }
            
            elif tool_name == "stop_all_projects":
                # Stop all projects
                await session_manager.clear_pending_intent(request.session_id)
                
                from database_postgres import get_db
                from apps_service import pm2_action
                
                with get_db() as conn:
                    result = conn.execute(
                        "SELECT domain FROM projects WHERE status != %s",
                        ("deleted",)
                    ).fetchall()
                    
                    projects = [row["domain"] for row in result]
                
                successes = 0
                for domain in projects:
                    res = pm2_action(domain, "stop")
                    if res.get("success"):
                        successes += 1
                
                return {
                    "type": "execution",
                    "text": f"Stopped {successes}/{len(projects)} projects",
                    "progress": [{"status": "success", "count": successes, "total": len(projects)}],
                    "message": f"Stopped {successes} out of {len(projects)} projects",
                    "details": None
                }
            
            else:
                # Generic execution
                result = await executor.execute(tool_name, args, session_key=request.session_id)
                await session_manager.clear_pending_intent(request.session_id)
                
                if result["status"] == "success":
                    return {
                        "type": "execution",
                        "text": result["message"],
                        "progress": [result],
                        "message": result["message"],
                        "details": None
                    }
                else:
                    return error_response(result.get("message", "Execution failed"), result)
        
        else:
            # User cancelled
            logger.info(f"[AI-CONFIRM] Operation cancelled: {tool_name}")
            await session_manager.clear_pending_intent(request.session_id)
            
            return {
                "type": "text",
                "text": f"Operation cancelled: {tool_name.replace('_', ' ')}",
                "progress": None,
                "message": "Operation cancelled",
                "details": None
            }
    
    except Exception as e:
        logger.error(f"[AI-CONFIRM] Error: {e}", exc_info=True)
        return error_response(f"Internal error: {str(e)}")
