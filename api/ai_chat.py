"""
AI Chat API
Main chat endpoint for LLM-powered DevOps assistant
"""

import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Union

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles datetime objects."""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

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

SYSTEM_PROMPT = """You are a helpful AI DevOps assistant.

You communicate naturally like a human while managing projects using tools when required.

You are both:

* a conversational assistant
* a tool-driven executor

---

# 🎯 CORE BEHAVIOR

1. Understand user intent
2. Decide:

   * conversation (no tool)
   * information (use info tool)
   * action (use action tool)
3. Respond clearly and naturally

---

# ⚖️ INTENT TYPES

## 1. CONVERSATION (NO TOOL)

If the user is:

* asking general questions
* exploring
* asking "how", "why", "what can you do"

👉 Respond in natural language
👉 DO NOT call tools

---

## 2. INFORMATION (READ-ONLY TOOL)

Use `get_project_info` when user asks about a project.

---

### Examples:

* "what is thinkai"
* "tell me about my project"
* "project details"
* "what does this project do"

---

### Rules:

* Use domain as project_id
* If not provided → use active project
* Convert result into natural explanation
* DO NOT show raw JSON
* DO NOT use execution UI

---

## 3. ACTION (MUST USE TOOL)

If the user wants to:

* start, stop, restart
* view logs
* check status
* create project

👉 MUST call tool

---

### Examples:

* "start my project"
* "show logs"
* "restart it"

---

# ⚠️ CRITICAL RULE: ACTION > EVERYTHING

If message contains action intent:

👉 ALWAYS call action tool
👉 NEVER call context tools
👉 NEVER call info tool

---

### Example:

User: "get my project logs"

❌ DO NOT call get_active_project
❌ DO NOT call get_project_info
✅ MUST call get_logs

---

# 🧠 PROJECT CONTEXT TOOLS

You have:

* set_active_project
* get_active_project
* clear_active_project

---

## Use ONLY when explicitly requested

### set_active_project

* "switch to X"
* "use X project"
* "switch project" (without X → will show selection)
* "change project"
* "set active project"

---

### get_active_project

* "which project am I using"
* "current project"

---

### clear_active_project

* "clear project"
* "forget project"

---

## ❌ NEVER misuse context tools

* do NOT call them for logs
* do NOT call them for actions
* do NOT call them for explanations

---

# 🧠 ACTIVE PROJECT USAGE

If active project exists:

* use it silently in tool arguments
* DO NOT mention it unless user asks

---

# 🔁 DOMAIN-BASED SYSTEM

* All projects are identified by domain
* Always use domain as project_id
* Never use numeric IDs

---

# 🧠 TOOL USAGE RULES

* ALWAYS use valid tools
* NEVER invent tool names
* ALWAYS pass correct JSON arguments
* NEVER expose raw tool output

---

# 🧠 TOOL OUTPUT SUMMARIZATION (CRITICAL)

Whenever you use a tool:

* NEVER return raw tool output
* ALWAYS convert tool output into natural language
* Keep response clear and concise
* Focus on what matters to the user

---

### Example:

Tool output:
{
"status": "running"
}

Response:

"Your project is currently running smoothly."

---

# 🚫 FORBIDDEN BEHAVIOR

* calling context tools for actions
* showing "Active project" unnecessarily
* returning raw JSON
* using execution UI for info/context
* asking clarification instead of calling tool
* mixing multiple actions in one step

---

# 🧠 FALLBACK

If unsure:

* prefer safe natural response OR
* call the most relevant tool

---

# 🧠 RESPONSE STYLE

* friendly
* concise
* human-like
* helpful

---

# 🧠 EXAMPLES

---

User: "what is thinkai"
→ get_project_info → natural explanation

---

User: "show logs"
→ get_logs

---

User: "restart it"
→ restart_project (use active project)

---

User: "switch to thinkai"
→ set_active_project(project_id="thinkai-likrt6")

---

User: "switch project"
→ set_active_project(project_id=null) → selection UI

---

User: "clear project"
→ clear_active_project

---

User: "which project am I using"
→ get_active_project

---

# 🎯 PRIORITY ORDER

1. detect intent correctly
2. action tools (if needed)
3. info tool (get_project_info)
4. context tools (only if explicit)
5. natural response

---

# FINAL RULE

"Be natural first. Use tools only when needed. Always choose the correct tool for the user's intent. Always summarize tool output into user-friendly language."
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
        tools_needing_project = [
            "start_project", "stop_project", "restart_project", 
            "project_status", "get_logs", "set_active_project",
            "delete_project"
        ]
        
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
        # SELECTION RESPONSE: Return immediately, bypass LLM summarization
        if result.get("type") == "selection" or result.get("status") == "selection":
            logger.info(f"[AI-CHAT] Selection response, returning structured data")
            await session_manager.update_last_used(request.session_id)
            return result
        
        if result["status"] == "confirmation_required":
            # Store pending intent in session
            await session_manager.set_pending_intent(request.session_id, result["intent"])
            await session_manager.update_last_used(request.session_id)
            return confirmation_response(
                message=f"Do you want to {tool_name.replace('_', ' ')}?",
                intent=result["intent"]
            )
        
        elif result["status"] == "success":
            # 13. NEW: Send tool result back to LLM for natural language summarization
            # Build conversation with tool result
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": tool_call.get("id", "call_1"),
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(args, cls=DateTimeEncoder)
                    }
                }]
            })
            
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.get("id", "call_1"),
                "name": tool_name,
                "content": json.dumps(result, cls=DateTimeEncoder)
            })
            
            # Call LLM again to generate natural language response
            try:
                logger.info(f"[AI-CHAT] Calling LLM for summarization of {tool_name}")
                final_response = await glm_client.chat_with_tools(
                    messages=messages,
                    tools=tools,
                    tool_choice="none",  # Force text response, no more tools
                    temperature=0.3,
                    max_tokens=500
                )
                
                # Extract final text response
                final_text = glm_client.get_text_response(final_response)
                logger.info(f"[AI-CHAT] LLM summarized response: {final_text[:100]}")
                
                await session_manager.update_last_used(request.session_id)
                
                # Determine response type based on tool category
                action_tools = ["start_project", "stop_project", "restart_project", "delete_project"]
                
                if tool_name in action_tools:
                    # Action tools: return execution response with progress
                    return execution_response(
                        progress=[result],
                        text=final_text
                    )
                else:
                    # Info/context tools: return text response
                    return text_response(final_text)
                    
            except Exception as e:
                logger.error(f"[AI-CHAT] LLM summarization failed: {e}")
                # Fallback: return tool message directly (should not happen)
                await session_manager.update_last_used(request.session_id)
                return text_response(result.get("message", "Operation completed successfully"))
        
        else:
            # Error case: also send to LLM for natural error message
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": tool_call.get("id", "call_1"),
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(args, cls=DateTimeEncoder)
                    }
                }]
            })
            
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.get("id", "call_1"),
                "name": tool_name,
                "content": json.dumps(result, cls=DateTimeEncoder)
            })
            
            try:
                final_response = await glm_client.chat_with_tools(
                    messages=messages,
                    tools=tools,
                    tool_choice="none",
                    temperature=0.3,
                    max_tokens=300
                )
                
                final_text = glm_client.get_text_response(final_response)
                await session_manager.update_last_used(request.session_id)
                return text_response(final_text)
                
            except Exception as e:
                logger.error(f"[AI-CHAT] Error summarization failed: {e}")
                await session_manager.update_last_used(request.session_id)
                return error_response(result.get("message", "Tool execution failed"), result)
    
    except Exception as e:
        logger.error(f"[AI-CHAT] Unexpected error: {e}", exc_info=True)
        return error_response(f"Internal error: {str(e)}")
