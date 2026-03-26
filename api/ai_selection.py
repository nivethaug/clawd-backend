"""
AI Selection API
Handle user selection from project options
"""

import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.ai.glm_client import get_glm_client
from services.ai.tool_registry import get_all_tools
from services.ai.tool_executor import get_tool_executor
from utils.ai_response_formatter import execution_response, text_response, error_response
from utils.ai_session_manager import get_session_manager


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles datetime objects."""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


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
    3. Send result to LLM for natural language summarization
    4. Return formatted response
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
        
        # Update session's active project (store domain, not numeric ID)
        session_manager = get_session_manager()
        await session_manager.set_active_project(request.session_id, request.selection)
        
        # Execute tool
        executor = get_tool_executor()
        result = await executor.execute(tool_name, args, session_key=request.session_id)
        
        # Send result to LLM for natural language summarization
        glm_client = get_glm_client()
        tools = get_all_tools()
        
        # Build messages for LLM
        messages = [
            {
                "role": "system",
                "content": "You are a helpful AI assistant. Summarize the tool execution result in natural language. Be concise and friendly."
            },
            {
                "role": "user",
                "content": f"I selected a project and executed the {tool_name} tool."
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_selection",
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(args, cls=DateTimeEncoder)
                    }
                }]
            },
            {
                "role": "tool",
                "tool_call_id": "call_selection",
                "name": tool_name,
                "content": json.dumps(result, cls=DateTimeEncoder)
            }
        ]
        
        try:
            logger.info(f"[AI-SELECTION] Calling LLM for summarization")
            llm_response = await glm_client.chat_with_tools(
                messages=messages,
                tools=tools,
                tool_choice="none",  # Force text response
                temperature=0.3,
                max_tokens=300
            )
            
            final_text = glm_client.get_text_response(llm_response)
            logger.info(f"[AI-SELECTION] LLM summarized: {final_text[:100]}")
            
        except Exception as e:
            logger.error(f"[AI-SELECTION] LLM summarization failed: {e}")
            final_text = result.get("message", "Operation completed")
        
        # Return result with natural language text
        if result["status"] == "success":
            # Determine response type based on tool
            action_tools = ["start_project", "stop_project", "restart_project", "delete_project"]
            
            if tool_name in action_tools:
                return {
                    "type": "execution",
                    "text": final_text,
                    "progress": [result],
                    "message": final_text,
                    "details": None
                }
            else:
                # Context/info tools
                return {
                    "type": "text",
                    "text": final_text,
                    "progress": None,
                    "message": None,
                    "details": None
                }
        else:
            return error_response(result.get("message", "Execution failed"), result)
    
    except Exception as e:
        logger.error(f"[AI-SELECTION] Error: {e}", exc_info=True)
        return error_response(f"Internal error: {str(e)}")
