"""
AI Chat API
Main chat endpoint for LLM-powered DevOps assistant
"""

import json
import logging
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# Import AI services
from services.ai.glm_client import get_glm_client
from services.ai.tool_registry import get_all_tools, is_disabled, validate_tool_args
from services.ai.tool_executor import get_tool_executor
from services.ai.project_resolver import get_project_resolver
from utils.ai_response_formatter import (
    text_response,
    execution_response,
    selection_response,
    confirmation_response,
    error_response
)
from utils.ai_session_manager import get_session_manager
from database_postgres import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================

class AIChatRequest(BaseModel):
    """Chat request model."""
    message: str = Field(..., description="User message")
    session_id: str = Field(..., description="Session identifier (UUID)")
    active_project: Optional[str] = Field(None, description="Active project domain or ID")


class AIChatResponse(BaseModel):
    """Chat response model."""
    type: str = Field(..., description="Response type: text, execution, selection, confirmation, error")
    text: Optional[str] = Field(None, description="Text content (for type='text')")
    progress: Optional[List[Dict[str, Any]]] = Field(None, description="Execution progress")
    message: Optional[str] = Field(None, description="Message (for selection/confirmation)")
    options: Optional[List[Dict[str, Any]]] = Field(None, description="Selection options")
    intent: Optional[Dict[str, Any]] = Field(None, description="Intent to execute")
    fields: Optional[List[Dict[str, Any]]] = Field(None, description="Required input fields")
    details: Optional[Dict[str, Any]] = Field(None, description="Error details")


# ============================================================================
# System Prompt
# ============================================================================

SYSTEM_PROMPT = """You are an AI DevOps assistant for managing web projects.

You help users manage their projects through natural language commands. You can:
- Start, stop, and restart project services (PM2)
- List all projects and check their status
- View logs for troubleshooting
- Create new projects (with confirmation)
- Manage multiple projects at once (with confirmation)

# CRITICAL TOOL CALLING RULES

1. **ALWAYS CALL TOOLS FOR ACTIONS**: When the user wants to perform an action, you MUST call the appropriate tool.
   - Do NOT return text responses for action requests
   - Do NOT assume which project the user means
   - Call the tool and let the backend handle ambiguity

2. **AMBIGUOUS COMMANDS**: If the user mentions a project type or partial name without specifying exactly which one:
   - CALL THE TOOL with whatever information you have
   - Example: "start bot" → call start_project with project_id="bot" (backend will return selection if multiple bots exist)
   - Example: "restart server" → call restart_project with project_id="server" (backend will handle it)
   - Example: "show logs" → call get_logs with no project_id (backend will ask for clarification)

3. **NEVER ASK FOR CLARIFICATION IN TEXT**: Do not respond with text asking "which project?". Instead, call the tool and let the backend return a selection response.

4. **DESTRUCTIVE OPERATIONS**: For delete/uninstall/remove operations, call the tool. The backend will handle confirmation.

# TOOL USAGE EXAMPLES

✅ CORRECT - Always call tools for actions:
- "start bot" → start_project(project_id="bot")
- "restart server" → restart_project(project_id="server")
- "show logs" → get_logs() or get_logs(project_id="logs")
- "stop everything" → stop_all_projects()
- "delete project" → delete_project(project_id="project")
- "list projects" → list_projects()
- "status" → project_status()

✅ CORRECT - Text responses for questions:
- "what can you do?" → text response explaining capabilities
- "help" → text response with help information
- "how do I create a project?" → text response with instructions

❌ WRONG - Do not do this:
- "start bot" → "Which bot would you like to start?" (NO! Call the tool instead)
- "restart server" → "I need to know which server" (NO! Call the tool instead)

# GUIDELINES

1. Be helpful and concise in your responses
2. ALWAYS use tools when the user wants to perform an action
3. Let the backend handle project resolution and selection
4. Never delete projects (this tool is disabled)
5. For questions, respond with helpful text

Remember: When in doubt, CALL THE TOOL. The backend is smart enough to handle ambiguity and ask for clarification through selection responses.
"""


# ============================================================================
# Main Chat Endpoint
# ============================================================================

@router.post("/chat", response_model=AIChatResponse)
async def ai_chat(request: AIChatRequest):
    """
    Main AI chat endpoint.
    
    Flow:
    1. Load session and projects
    2. Call GLM with tools
    3. If tool_call:
       - Resolve project if needed
       - Handle selection if needed
       - Execute or return confirmation
    4. Return formatted response
    """
    try:
        logger.info(f"[AI-CHAT] Message from session {request.session_id}: {request.message[:100]}")
        
        # 1. Get or create session
        session_manager = get_session_manager()
        session = await session_manager.get_or_create_session(request.session_id)
        
        # 2. Load all projects from DB
        with get_db() as conn:
            result = conn.execute("""
                SELECT p.*, pt.display_name as type_name
                FROM projects p
                LEFT JOIN project_types pt ON p.type_id = pt.id
                WHERE p.status != %s
                ORDER BY p.created_at DESC
            """, ("deleted",)).fetchall()
            
            projects = [dict(row) for row in result]
        
        logger.debug(f"[AI-CHAT] Loaded {len(projects)} projects")
        
        # 3. Get active project
        active_project = None
        if request.active_project:
            # Use explicitly provided active project
            for project in projects:
                if project["domain"] == request.active_project or str(project["id"]) == request.active_project:
                    active_project = project
                    break
        elif session.get("active_project_id"):
            # Use session's active project
            for project in projects:
                if project["id"] == session["active_project_id"]:
                    active_project = project
                    break
        
        # 4. Build messages for GLM
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": request.message}
        ]
        
        # Add project context if available
        if active_project:
            messages[0]["content"] += f"\n\nCurrent active project: {active_project['name']} ({active_project['domain']})"
        
        # 5. Call GLM with tools
        glm_client = get_glm_client()
        tools = get_all_tools()
        
        try:
            response = await glm_client.chat_with_tools(
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.1,
                max_tokens=1000
            )
        except Exception as e:
            logger.error(f"[AI-CHAT] GLM API error: {e}")
            return error_response(f"AI service error: {str(e)}")
        
        # 6. Parse response
        tool_calls = glm_client.parse_tool_calls(response)
        
        if not tool_calls:
            # No tool calls - return text response
            text = glm_client.get_text_response(response)
            logger.info(f"[AI-CHAT] Text response: {text[:100]}")
            await session_manager.update_last_used(request.session_id)
            return text_response(text)
        
        # 7. Process tool calls
        # For now, handle first tool call only (can extend to multiple)
        tool_call = tool_calls[0]
        tool_name = tool_call["name"]
        
        # Parse arguments
        try:
            args = json.loads(tool_call["arguments"]) if isinstance(tool_call["arguments"], str) else tool_call["arguments"]
        except:
            args = {}
        
        logger.info(f"[AI-CHAT] Tool call: {tool_name} with args: {args}")
        
        # 8. Check if disabled
        if is_disabled(tool_name):
            logger.warning(f"[AI-CHAT] Tool is disabled: {tool_name}")
            await session_manager.update_last_used(request.session_id)
            return error_response(f"Tool '{tool_name}' is disabled and cannot be executed")
        
        # 9. Validate args
        is_valid, error_msg = validate_tool_args(tool_name, args)
        if not is_valid:
            logger.warning(f"[AI-CHAT] Invalid args: {error_msg}")
            await session_manager.update_last_used(request.session_id)
            return error_response(error_msg)
        
        # 10. Resolve project if needed
        tools_needing_project = ["start_project", "stop_project", "restart_project", "project_status", "get_logs"]
        
        if tool_name in tools_needing_project:
            project_id = args.get("project_id")
            
            resolver = get_project_resolver()
            resolution = resolver.resolve(
                user_text=request.message,
                projects=projects,
                active_project=active_project,
                explicit_project_id=project_id
            )
            
            if resolution.status == "selection":
                # Return selection response
                # Ensure candidates exist and have at least one item
                if not resolution.candidates or len(resolution.candidates) == 0:
                    logger.warning(f"[AI-CHAT] Selection status but no candidates provided")
                    await session_manager.update_last_used(request.session_id)
                    return error_response("No projects available for selection")
                
                options = [
                    {"label": f"{p['name']} ({p['domain']})", "value": p["domain"]}
                    for p in resolution.candidates
                ]
                
                logger.info(f"[AI-CHAT] Returning selection with {len(options)} options")
                
                await session_manager.update_last_used(request.session_id)
                return selection_response(
                    message=resolution.message,
                    options=options,
                    intent={"tool": tool_name, "args": args}
                )
            
            elif resolution.status == "not_found":
                await session_manager.update_last_used(request.session_id)
                return error_response(resolution.message)
            
            # Resolved - update args
            args["project_id"] = resolution.project["domain"]
        
        # 11. Execute tool
        executor = get_tool_executor()
        result = await executor.execute(tool_name, args)
        
        # 12. Handle result
        if result["status"] == "confirmation_required":
            # Store pending intent in session
            await session_manager.set_pending_intent(request.session_id, result["intent"])
            await session_manager.update_last_used(request.session_id)
            return confirmation_response(
                message=f"Do you want to {tool_name.replace('_', ' ')}?",
                intent=result["intent"]
            )
        
        elif result["status"] == "success":
            await session_manager.update_last_used(request.session_id)
            return execution_response(
                progress=[result],
                text=result["message"]
            )
        
        else:
            await session_manager.update_last_used(request.session_id)
            return error_response(result.get("message", "Tool execution failed"), result)
    
    except Exception as e:
        logger.error(f"[AI-CHAT] Unexpected error: {e}", exc_info=True)
        return error_response(f"Internal error: {str(e)}")
