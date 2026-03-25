"""
AI Selection API
Handle user selection from project options
"""

import logging
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.ai.tool_executor import get_tool_executor
from utils.ai_response_formatter import execution_response, error_response
from utils.ai_session_manager import get_session_manager

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================

class AISelectionRequest(BaseModel):
    """Selection request model."""
    session_id: str = Field(..., description="Session identifier")
    selection: str = Field(..., description="Selected option value (project domain)")
    intent: Dict[str, Any] = Field(..., description="Original intent with tool and args")


class AISelectionResponse(BaseModel):
    """Selection response model."""
    type: str = Field(..., description="Response type")
    text: Optional[str] = Field(None)
    progress: Optional[List[Dict[str, Any]]] = Field(None)
    message: Optional[str] = Field(None)
    details: Optional[Dict[str, Any]] = Field(None)


# ============================================================================
# Selection Endpoint
# ============================================================================

@router.post("/selection", response_model=AISelectionResponse)
async def ai_selection(request: AISelectionRequest):
    """
    Handle user selection from options.
    
    Flow:
    1. Update intent args with selected project_id
    2. Execute tool
    3. Return execution response
    """
    try:
        logger.info(f"[AI-SELECTION] Session {request.session_id} selected: {request.selection}")
        
        # Get intent
        intent = request.intent
        tool_name = intent.get("tool")
        args = intent.get("args", {})
        
        if not tool_name:
            return error_response("Invalid intent: missing tool name")
        
        # Update args with selected project
        args["project_id"] = request.selection
        
        logger.info(f"[AI-SELECTION] Executing {tool_name} with project_id={request.selection}")
        
        # Update session's active project
        session_manager = get_session_manager()
        
        # Find project ID from domain
        from database_postgres import get_db
        with get_db() as conn:
            result = conn.execute(
                "SELECT id FROM projects WHERE domain = %s",
                (request.selection,)
            ).fetchone()
            
            if result:
                await session_manager.set_active_project(request.session_id, result["id"])
        
        # Execute tool
        executor = get_tool_executor()
        result = await executor.execute(tool_name, args, session_key=request.session_id)
        
        # Return result
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
    
    except Exception as e:
        logger.error(f"[AI-SELECTION] Error: {e}", exc_info=True)
        return error_response(f"Internal error: {str(e)}")
