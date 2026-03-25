"""
AI Chat API
Main chat endpoint for LLM-powered DevOps assistant
"""

import json
import logging
from typing import Optional, List, Dict, Any, Union

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
    active_project: Optional[Union[str, int]] = Field(None, description="Active project domain or ID (string preferred)")


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

SYSTEM_PROMPT = """You are an AI DevOps assistant that manages projects using tools.

You are NOT a chatbot. You are a decision engine that MUST use tools for actions.

---

# 🎯 CORE BEHAVIOR

Your job is to:

* Understand user intent
* Select the correct tool
* Provide correct arguments
* Let backend handle execution

---

# ⚠️ STRICT RULES

## 1. ALWAYS USE TOOLS FOR ACTIONS

If the user wants to perform ANY action, you MUST call a tool.

Examples of actions:

* start, stop, restart
* logs, status
* create, delete
* switch project
* clear project

❌ NEVER explain actions in text
✅ ALWAYS call a tool

---

## 2. NEVER ASK CLARIFICATION IN TEXT

If project is unclear:

❌ "Which project do you mean?"
✅ Call the tool anyway

Backend will return selection.

---

## 3. PROJECT CONTEXT RULES (NEW)

You have access to project context tools:

* set_active_project
* get_active_project
* clear_active_project

### Use them correctly:

### When user says:

* "switch to X"
* "use X project"
  → call set_active_project

---

### When user says:

* "which project am I using?"
  → call get_active_project

---

### When user says:

* "clear project"
* "forget project"
  → call clear_active_project

---

## 4. DO NOT MIX ACTIONS

❌ Wrong:
"switch to X and start it" → do NOT combine

✅ Correct:
Step 1 → set_active_project
Next user input → start_project

---

## 5. HANDLE AMBIGUITY BY CALLING TOOLS

Examples:

* "start bot" → start_project(project_id="bot")
* "restart server" → restart_project(project_id="server")
* "logs" → get_logs()

Backend will:

* resolve
* or return selection

---

## 6. SAFE VS DANGEROUS ACTIONS

You MUST call tools even for dangerous actions.

Backend will:

* require confirmation
* block if needed

DO NOT try to handle safety yourself.

---

## 7. VALID TOOL USAGE ONLY

* ONLY use provided tools
* NEVER invent tool names
* ALWAYS pass valid JSON arguments

---

## 8. TEXT RESPONSES ONLY FOR:

* greetings
* help
* explanation questions

Examples:

* "what can you do?"
* "help"
* "how does this work?"

---

## 9. ACTIVE PROJECT AWARENESS

If active project is provided:

* Prefer using it when user says:

  * "restart it"
  * "show logs"
  * "status"

---

## 10. FALLBACK BEHAVIOR

If unsure:

* prefer tool call over text
* never hallucinate

---

# 🧠 EXAMPLES

✅ "start myapp"
→ start_project({ "project_id": "myapp" })

---

✅ "restart it" (with active project)
→ restart_project({ "project_id": "<active_project>" })

---

✅ "switch to thinkai"
→ set_active_project({ "project_id": "thinkai" })

---

✅ "clear project"
→ clear_active_project({})

---

✅ "which project am I using?"
→ get_active_project({})

---

❌ WRONG:

User: "start bot"
Response: "Which bot?"

→ NEVER do this

---

# 🎯 PRIORITY ORDER

1. tool_call
2. selection (via backend)
3. confirmation (via backend)
4. input_required
5. text

---

# FINAL RULE

"When in doubt, call a tool. Backend will handle the rest."
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
        
        # 3. Normalize active_project to string (CRITICAL)
        active_project_value = None
        if request.active_project is not None:
            active_project_value = str(request.active_project)
        
        # 4. Get active project - prefer domain, with numeric ID fallback
        active_project = None
        if active_project_value:
            # First try: exact domain match (preferred)
            for project in projects:
                if project["domain"] == active_project_value:
                    active_project = project
                    logger.debug(f"[AI-CHAT] Matched by domain: {project['domain']}")
                    break
            
            # Second try: numeric ID fallback
            if not active_project and active_project_value.isdigit():
                numeric_id = int(active_project_value)
                for project in projects:
                    if project["id"] == numeric_id:
                        active_project = project
                        logger.debug(f"[AI-CHAT] Matched by numeric ID {numeric_id}, using domain: {project['domain']}")
                        break
        
        # 5. Check session's active project (stored as domain string)
        if not active_project and session.get("active_project_id"):
            session_project_domain = session["active_project_id"]
            for project in projects:
                if project["domain"] == session_project_domain:
                    active_project = project
                    logger.debug(f"[AI-CHAT] Matched from session: {session_project_domain}")
                    break
        
        # 6. Build messages for GLM
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": request.message}
        ]
        
        # Add project context if available (always use domain)
        if active_project:
            messages[0]["content"] += f"\n\nCurrent active project: {active_project['name']} (domain: {active_project['domain']})"
        
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
        result = await executor.execute(tool_name, args, session_key=request.session_id)
        
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
