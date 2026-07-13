"""
AI Chat API
Main chat endpoint for LLM-powered DevOps assistant
"""

import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Union

from fastapi import APIRouter, HTTPException, Header, Query
from pydantic import BaseModel, Field


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles datetime objects."""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

# Import AI services
from services.ai.glm_client import get_glm_client
from services.ai.openrouter_client import get_openrouter_client
from services.ai.tool_registry import get_all_tools, get_tools_for_project, get_tools_without_project, is_disabled, validate_tool_args
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
from utils.auth_helpers import get_user_id_from_token
from utils.devops_session_context import get_devops_session_context
from utils.project_chat_repo import ProjectChatRepository
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

SYSTEM_PROMPT = """You are a helpful AI DevOps assistant that manages projects using tools.

You are both a conversational assistant and a tool-driven executor.

# CORE BEHAVIOR
1. Understand user intent
2. Decide: conversation (no tool), information (read-only tool), or action (tool)
3. Respond clearly and naturally

# INTENT TYPES

## CONVERSATION (NO TOOL)
General questions, exploring, "what can you do" → Respond in natural language. DO NOT call tools.

## INFORMATION (READ-ONLY TOOL)
"what is X", "tell me about my project", "project details" → Use `get_project_info`.
- Use domain as project_id. If not provided → use active project.
- Convert result into natural explanation. DO NOT show raw JSON.

## ACTION (MUST USE TOOL)
start/stop/restart/logs/status → MUST call the corresponding tool.
- "start" → start_project, "stop" → stop_project, "restart" → restart_project
- "logs" → get_logs, "status" → project_status
Single-word actions ("start", "stop", "restart", "logs", "status") ALWAYS map to action tools, NEVER to context tools.

## SCHEDULER ACTIONS (scheduler projects only)
- "show/list jobs" → scheduler_list_jobs, "add/create/schedule job" → scheduler_create_job
- "edit/update job" → scheduler_update_job, "pause job" → scheduler_pause_job, "resume job" → scheduler_resume_job
- "test/run now" → scheduler_run_job, "job logs/history" → scheduler_job_logs
- "delete job" → scheduler_delete_job (requires confirmation), "delete all jobs" → scheduler_clear_jobs (requires confirmation)

# CONTEXT TOOLS (use ONLY when explicitly requested)
- set_active_project: "switch to X", "use X", "change project"
- get_active_project: "which project am I using", "current project"
- clear_active_project: "clear project", "forget project"
NEVER misuse context tools for actions or info requests.

# ACTIVE PROJECT
- If active project exists, use it silently in tool arguments. DO NOT mention it unless asked.
- All projects identified by domain. Always use domain as project_id.

# TOOL OUTPUT
- NEVER return raw tool output. ALWAYS convert into natural language.
- Be concise and human-like.

# PRIORITY ORDER
1. Detect intent correctly → 2. Action tools → 3. Info tool → 4. Context tools → 5. Natural response

Be natural first. Use tools only when needed.
"""

# ============================================================================
# Project-Type-Specific Capability Descriptions
# Used to tailor "what can you do" answers to the active project type.
# ============================================================================

PROJECT_TYPE_CAPABILITIES = {
    "website": """
# 🔧 YOUR CAPABILITIES FOR THIS WEBSITE PROJECT

When asked "what can you do", ONLY list these website-specific capabilities:
- Start / Stop / Restart the website services
- Check project status — see if frontend and backend are running
- View frontend and backend logs
- Get project details and configuration
- Create / Delete projects

DO NOT mention telegram bots, discord bots, trading bots, schedulers, or job management.
This is a WEBSITE project — tailor your answers accordingly.
""",
    "telegrambot": """
# 🔧 YOUR CAPABILITIES FOR THIS TELEGRAM BOT PROJECT

When asked "what can you do", ONLY list these telegram-bot-specific capabilities:
- Start / Stop / Restart the bot
- Check bot status and health
- View bot logs to debug issues
- Get project details and configuration
- Create / Delete projects

DO NOT mention websites, discord bots, trading bots, or schedulers.
This is a TELEGRAM BOT project — tailor your answers accordingly.
""",
    "discordbot": """
# 🔧 YOUR CAPABILITIES FOR THIS DISCORD BOT PROJECT

When asked "what can you do", ONLY list these discord-bot-specific capabilities:
- Start / Stop / Restart the bot
- Check bot status and health
- View bot logs to debug issues
- Get project details and configuration
- Create / Delete projects

DO NOT mention websites, telegram bots, trading bots, or schedulers.
This is a DISCORD BOT project — tailor your answers accordingly.
""",
    "tradingbot": """
# 🔧 YOUR CAPABILITIES FOR THIS TRADING BOT PROJECT

When asked "what can you do", ONLY list these trading-bot-specific capabilities:
- Start / Stop / Restart the trading bot
- Check bot status and health
- View bot logs to debug issues
- Get project details and configuration
- Create / Delete projects

DO NOT mention websites, telegram, discord, or scheduler jobs.
This is a TRADING BOT project — tailor your answers accordingly.
""",
    "scheduler": """
# 🔧 YOUR CAPABILITIES FOR THIS SCHEDULER PROJECT

When asked "what can you do", ONLY list these scheduler-specific capabilities:
- View scheduled jobs and execution history
- Create / Edit / Delete scheduled jobs
- Pause / Resume jobs
- Run a job immediately (test)
- View job logs
- Start / Stop / Restart the scheduler service
- Check scheduler status
- Get project details and configuration
- Create / Delete projects

DO NOT mention websites, telegram bots, discord bots, or trading bots.
This is a SCHEDULER project — tailor your answers accordingly.
""",
    "custom": """
# 🔧 YOUR CAPABILITIES FOR THIS CUSTOM PROJECT

When asked "what can you do", ONLY list these capabilities:
- Start / Stop / Restart the project services
- Check project status
- View logs
- Get project details and configuration
- Create / Delete projects

This is a CUSTOM project — tailor your answers accordingly.
""",
    "default": """
# 🔧 YOUR CAPABILITIES FOR THIS PROJECT

When asked "what can you do", list these capabilities:
- Start / Stop / Restart the project services
- Check project status
- View logs
- Get project details and configuration
- Create / Delete projects

Tailor your answers to the active project type only.
""",
}


# ============================================================================
# Main Chat Endpoint
# ============================================================================

# ============================================================================
# Core Chat Engine — shared by HTTP, Telegram, Discord
# ============================================================================

async def process_message(
    user_id: int,
    message: str,
    session_id: str,
    active_project_override: Optional[str] = None,
    source: str = "web",
) -> dict:
    """
    Core AI chat logic — callable from HTTP endpoint, Telegram webhook, etc.

    Args:
        user_id: Authenticated user ID
        message: User's text message
        session_id: Session identifier (UUID for web, tg_{chat_id} for Telegram)
        active_project_override: Project domain from request (web only)
        source: "web" | "telegram" — for logging

    Returns:
        Response dict: {type: "text"|"execution"|"selection"|"confirmation"|"error", ...}
    """
    try:
        _src_tag = f"[AI-CHAT:{source.upper()}]" if source != "web" else "[AI-CHAT]"
        
        logger.info(f"{_src_tag} Message from session {session_id} (user={user_id}): {message[:100]}")
        
        # 1. Get or create session
        session_manager = get_session_manager()
        session = await session_manager.get_or_create_session(session_id)
        
        # 2. Load all projects from DB
        with get_db() as conn:
            result = conn.execute("""
                SELECT p.*, pt.display_name as type_name, pt.type as type_slug
                FROM projects p
                LEFT JOIN project_types pt ON p.type_id = pt.id
                WHERE p.status != %s
                ORDER BY p.created_at DESC
            """, ("deleted",)).fetchall()
            
            projects = [dict(row) for row in result]
        
        logger.debug(f"[AI-CHAT] Loaded {len(projects)} projects")
        
        # 3. Normalize active_project to string (CRITICAL)
        active_project_value = active_project_override
        
        logger.info(f"[AI-CHAT] Resolving active_project: request={active_project_value}, "
                    f"session={session.get('active_project_id')}, projects_count={len(projects)}")
        if projects:
            logger.info(f"[AI-CHAT] Available project domains: {[p['domain'] for p in projects]}")
        
        # 4. Get active project - prefer domain, with numeric ID fallback
        active_project = None
        if active_project_value:
            # First try: exact domain match (preferred)
            for project in projects:
                if project["domain"] == active_project_value:
                    active_project = project
                    logger.info(f"[AI-CHAT] ✓ Matched by domain: {project['domain']}")
                    break
            
            if not active_project:
                logger.warning(f"[AI-CHAT] ✗ Domain '{active_project_value}' not found in {len(projects)} projects")
            
            # Second try: numeric ID fallback
            if not active_project and active_project_value.isdigit():
                numeric_id = int(active_project_value)
                for project in projects:
                    if project["id"] == numeric_id:
                        active_project = project
                        logger.info(f"[AI-CHAT] ✓ Matched by numeric ID {numeric_id}, using domain: {project['domain']}")
                        break
        
        chat_repo = ProjectChatRepository()

        # Telegram shares project selection across web and bot, so prefer
        # users.active_project over this Telegram chat's cached ai_session row.
        if not active_project and source == "telegram":
            user_active = chat_repo.get_active_project(user_id)
            if user_active:
                logger.info(f"[AI-CHAT:TELEGRAM] users.active_project = {user_active}")
                for project in projects:
                    if project["domain"] == user_active:
                        active_project = project
                        logger.info(f"[AI-CHAT] ✓ Matched from users.active_project: {user_active}")
                        break
                if not active_project:
                    logger.warning(f"[AI-CHAT] ✗ users.active_project '{user_active}' not found in projects list")

        # 5. Check session's active project (stored as domain string)
        if not active_project and session.get("active_project_id"):
            session_project_domain = session["active_project_id"]
            for project in projects:
                if project["domain"] == session_project_domain:
                    active_project = project
                    logger.info(f"[AI-CHAT] ✓ Matched from session: {session_project_domain}")
                    break
        
        # 5b. Check users.active_project as third source (priority: request > session > users table)
        if not active_project:
            user_active = chat_repo.get_active_project(user_id)
            if user_active:
                logger.info(f"[AI-CHAT] users.active_project = {user_active}")
                for project in projects:
                    if project["domain"] == user_active:
                        active_project = project
                        logger.info(f"[AI-CHAT] ✓ Matched from users.active_project: {user_active}")
                        break
                if not active_project:
                    logger.warning(f"[AI-CHAT] ✗ users.active_project '{user_active}' not found in projects list")
        
        if not active_project:
            logger.warning(f"[AI-CHAT] ✗ No active project resolved from any source")

        devops_context = get_devops_session_context()
        active_project_session = None
        if active_project:
            active_project_session = devops_context.get_active_session(
                user_id=user_id,
                active_project=active_project,
                session_active_id=session.get("active_project_session_id"),
                user_active_id=devops_context.get_user_active_session_id(user_id),
            )
        
        # 6. Build messages for GLM (with conversation history: last 4 messages)
        system_content = SYSTEM_PROMPT
        
        # ── Tool filtering based on project state ────────────────────
        # No project selected → only context tools (set_active_project, list, etc.)
        # Project selected → all tools filtered by project type (scheduler tools
        # only for scheduler-type projects)
        
        # For Telegram: project management is handled by slash commands and
        # inline buttons — remove set_active_project / clear_active_project /
        # list_projects from the LLM tool list so the AI can't attempt
        # project switching through tool calls.
        _telegram_no_select_tools = {
            "set_active_project", "clear_active_project", "list_projects",
        }
        
        if not active_project:
            if source == "telegram":
                # Telegram with no project: DON'T send to LLM at all.
                # Return instant "select a project" with inline buttons.
                _options = [
                    {"label": f"{p['name']} ({p['domain']})", "value": p["domain"]}
                    for p in projects
                ] if projects else []
                logger.info(f"[AI-CHAT:TELEGRAM] ⚡ No project → instant selection (no LLM)")
                await session_manager.update_last_used(session_id)
                return selection_response(
                    message="📌 Please select a project first:",
                    options=_options,
                    intent={"tool": "set_active_project", "args": {}},
                )
            
            tools = get_tools_without_project()
            system_content += (
                "\n\n⚠️ NO ACTIVE PROJECT SELECTED.\n"
                "You MUST tell the user to select a project first using 'switch project'.\n"
                "DO NOT attempt any project actions (start, stop, restart, logs, status) until a project is selected.\n"
                "DO NOT list what you can do — instead ask the user to select a project."
            )
            logger.info(f"[AI-CHAT] No active project → {len(tools)} context-only tools")
        else:
            _project_type = active_project.get("type_slug") or active_project.get("type_name", "")
            tools = get_tools_for_project(_project_type)
            
            # Strip project-selection tools for Telegram — handled by UI
            if source == "telegram":
                tools = [
                    t for t in tools
                    if t["function"]["name"] not in _telegram_no_select_tools
                ]
            
            system_content += (
                f"\n\nCurrent active project: {active_project['name']} "
                f"(domain: {active_project['domain']}, type: {_project_type or 'unknown'})"
            )
            if active_project_session:
                _lock = devops_context.get_project_lock(int(active_project["id"]))
                _lock_owner = _lock.get("session_name") or _lock.get("active_session_id") or "none"
                system_content += (
                    f"\nCurrent active project session: {active_project_session.get('label') or 'Untitled Session'} "
                    f"(id: {active_project_session['id']}, channel: {active_project_session.get('channel') or 'webchat'}, "
                    f"last used: {active_project_session.get('last_used_at') or 'never'}). "
                    f"Lock owner: {_lock_owner}."
                )
            # ── Inject project-type-specific capabilities ────────────
            # GLM must tailor 'what can you do' answers to the ACTIVE
            # project type only — not list every possible project type.
            _type_capabilities = PROJECT_TYPE_CAPABILITIES.get(
                (_project_type or "").lower(),
                PROJECT_TYPE_CAPABILITIES["default"],
            )
            system_content += "\n" + _type_capabilities
            logger.info(f"[AI-CHAT] Active project type='{_project_type}' → {len(tools)} tools")
        
        messages = [{"role": "system", "content": system_content}]
        
        # Inject last 4 persisted messages as conversation context
        if active_project:
            recent = chat_repo.get_recent_messages(
                user_id,
                active_project["domain"],
                limit=4,
                project_session_id=active_project_session.get("id") if active_project_session else None,
            )
            for msg in recent:
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
                logger.debug(f"[AI-CHAT] History context: {msg['role']} = {msg['content'][:60]}...")
        
        # Finally, add the current user message
        messages.append({"role": "user", "content": message})
        
        logger.debug(f"{_src_tag} Sending {len(messages)} messages to GLM (system + {len(messages)-2} history + current)")
        
        # 5. Call GLM with tools
        glm_client = get_glm_client()

        async def _chat_with_tools_primary_then_openrouter(
            call_messages: List[Dict[str, Any]],
            call_tools: List[Dict[str, Any]],
            tool_choice: str,
            temperature: float,
            max_tokens: int,
            purpose: str,
        ) -> Dict[str, Any]:
            try:
                return await glm_client.chat_with_tools(
                    messages=call_messages,
                    tools=call_tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as glm_error:
                logger.warning(
                    "[AI-CHAT] GLM failed for %s; falling back to OpenRouter once: %s",
                    purpose,
                    glm_error,
                )
                openrouter_client = get_openrouter_client()
                return await openrouter_client.chat_completion(
                    messages=call_messages,
                    tools=call_tools,
                    tool_choice=tool_choice,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    max_retries=1,
                )
        
        # ── Persist user message ─────────────────────────────────────
        # Store the user's message now (before LLM call) if we have a project context
        _active_domain = active_project["domain"] if active_project else None
        _active_session_id = active_project_session.get("id") if active_project_session else None
        _normalized_message = message.strip().lower()
        _is_telegram_greeting = source == "telegram" and _normalized_message in {"hi", "hello", "hey"}
        # Messages about switching/clearing projects should NOT be persisted
        # — they are flow-control noise, not project-specific conversation.
        _switch_keywords = ["switch project", "change project", "select project",
                           "clear project", "switch to", "change to", "use project",
                           "clear active project", "clear active", "sessions",
                           "show sessions", "list sessions", "switch session",
                           "select session", "new session", "create session",
                           "start session", "clear session", "clear active session",
                           "forget session", "current session", "which session",
                           "complete session", "release session", "finish session"]
        _is_switch_msg = _is_telegram_greeting or any(kw in _normalized_message for kw in _switch_keywords)
        
        if _active_domain and not _is_switch_msg:
            chat_repo.add_message(
                user_id=user_id,
                project_domain=_active_domain,
                role="user",
                content=message,
                project_session_id=_active_session_id,
            )
        
        # ── Helper: persist assistant response then return ────────────
        def _finalize(resp: dict) -> dict:
            """Persist assistant message to projectchat and return response.
            Skips: errors, selection/confirmation prompts, and switch commands."""
            _skip_types = {"selection", "confirmation", "error"}
            
            if _active_domain and resp.get("type") not in _skip_types and not _is_switch_msg:
                chat_repo.add_message(
                    user_id=user_id,
                    project_domain=_active_domain,
                    role="assistant",
                    content=resp.get("text") or resp.get("message") or "",
                    project_session_id=_active_session_id,
                    response_type=resp.get("type"),
                    metadata=resp,
                )
            return resp
        
        # ── PRE-LLM FAST PATH ───────────────────────────────────────
        # Intercept deterministic commands and execute directly, skipping
        # the LLM entirely. Saves ~3-20s per request for the most common
        # chat operations (switch, clear, current project).
        import re
        _msg_lower = _normalized_message

        if _is_telegram_greeting:
            await session_manager.update_last_used(session_id)
            if active_project:
                return _finalize(text_response(
                    f"Hi! You are connected to **{active_project['name']}**. "
                    "Send `/current` to see the active project/session, `/sessions` to choose a session, "
                    "or ask for `status`, `logs`, `start`, `stop`, or `restart`."
                ))
            return _finalize(text_response(
                "Hi! Send `/switch` to choose a project, then I can help with status, logs, start, stop, restart, and sessions."
            ))

        def _result_to_response(result: dict) -> dict:
            if result.get("type") == "selection" or result.get("status") == "selection":
                return result
            if result.get("status") == "error":
                return error_response(result.get("message", "Operation failed"), result)
            return text_response(result.get("message", "Done."))

        if _msg_lower in ("sessions", "show sessions", "list sessions", "switch session", "select session"):
            _executor = get_tool_executor()
            result = await _executor.execute(
                "list_project_sessions",
                {},
                session_key=session_id,
                user_id=user_id,
            )
            await session_manager.update_last_used(session_id)
            return _finalize(_result_to_response(result))

        _new_session_match = re.match(r'^(?:new session|create session|start session)(?:\s+(.+))?$', message.strip(), re.I)
        if _new_session_match:
            label = (_new_session_match.group(1) or "DevOps session").strip()
            _executor = get_tool_executor()
            result = await _executor.execute(
                "create_project_session",
                {"label": label, "channel": source},
                session_key=session_id,
                user_id=user_id,
            )
            await session_manager.update_last_used(session_id)
            return _finalize(_result_to_response(result))

        _select_session_match = re.match(r'^(?:select session|use session|switch session to)\s+#?(\d+)$', _msg_lower)
        if _select_session_match:
            _executor = get_tool_executor()
            result = await _executor.execute(
                "set_active_project_session",
                {"session_id": int(_select_session_match.group(1))},
                session_key=session_id,
                user_id=user_id,
            )
            await session_manager.update_last_used(session_id)
            return _finalize(_result_to_response(result))

        if _msg_lower in ("clear session", "clear active session", "forget session"):
            _executor = get_tool_executor()
            result = await _executor.execute(
                "clear_active_project_session",
                {},
                session_key=session_id,
                user_id=user_id,
            )
            await session_manager.update_last_used(session_id)
            return _finalize(_result_to_response(result))

        if _msg_lower in ("current session", "which session", "what session am i using"):
            _executor = get_tool_executor()
            result = await _executor.execute(
                "get_active_project_session",
                {},
                session_key=session_id,
                user_id=user_id,
            )
            await session_manager.update_last_used(session_id)
            return _finalize(_result_to_response(result))

        if _msg_lower in ("complete session", "release session", "finish session"):
            _executor = get_tool_executor()
            result = await _executor.execute(
                "release_active_project_session",
                {},
                session_key=session_id,
                user_id=user_id,
            )
            await session_manager.update_last_used(session_id)
            return _finalize(_result_to_response(result))
        
        # "switch to {domain}" → set_active_project directly
        _switch_match = re.match(r'^(?:switch to|use|change to|set active project(?: to)?)\s+(.+)$', _msg_lower)
        if _switch_match:
            _target = _switch_match.group(1).strip()
            _matched_project = None
            for p in projects:
                if p["domain"] == _target or p["domain"].startswith(_target + "-") or _target in p["domain"]:
                    _matched_project = p
                    break
            if _matched_project:
                logger.info(f"[AI-CHAT] ⚡ Fast-path: switching to {_matched_project['domain']} (no LLM call)")
                _executor = get_tool_executor()
                result = await _executor.execute(
                    "set_active_project",
                    {"project_id": _matched_project["domain"]},
                    session_key=session_id,
                    user_id=user_id,
                )
                await session_manager.update_last_used(session_id)
                return _finalize(text_response(
                    result.get("message", f"Switched to {_matched_project['name']} ✅")
                ))
        
        # ── "switch project" (bare, no target) → selection response ──
        # Show project picker WITHOUT calling LLM. This returns type="selection"
        # which the Telegram webhook converts to inline keyboard buttons.
        _bare_switch_patterns = {
            "switch project", "switch", "change project", "select project",
            "change", "pick project", "choose project",
            "switch to project", "change to project", "use project",
        }
        if _msg_lower in _bare_switch_patterns:
            if projects:
                _options = [
                    {"label": f"{p['name']} ({p['domain']})", "value": p["domain"]}
                    for p in projects
                ]
                logger.info(f"[AI-CHAT] ⚡ Fast-path: project selection ({len(_options)} projects, no LLM call)")
                await session_manager.update_last_used(session_id)
                return _finalize(selection_response(
                    message="Which project would you like to switch to?",
                    options=_options,
                    intent={"tool": "set_active_project", "args": {}},
                ))
        
        # ── Selection reply detection ─────────────────────────────
        # When no active project is set and user sends a short message
        # that matches a project name/domain, treat it as a selection
        # reply. This handles the common flow:
        #   AI: "Pick a project: 1. telebot 2. discord..."
        #   User: "telebot"  ← needs to switch, not go through LLM
        if not active_project and len(message.split()) <= 3:
            _reply_lower = _msg_lower
            for p in projects:
                _pname = p["name"].lower()
                _pdomain = p["domain"].lower()
                # Match: exact name, name substring, or domain match
                if (_reply_lower == _pname
                    or _reply_lower == _pdomain
                    or _pname.startswith(_reply_lower)
                    or _pdomain.startswith(_reply_lower)
                    or _reply_lower in _pname):
                    logger.info(f"[AI-CHAT] ⚡ Fast-path: project selection reply → '{p['name']}' (no LLM call)")
                    _executor = get_tool_executor()
                    result = await _executor.execute(
                        "set_active_project",
                        {"project_id": p["domain"]},
                        session_key=session_id,
                        user_id=user_id,
                    )
                    await session_manager.update_last_used(session_id)
                    return _finalize(text_response(
                        result.get("message", f"Switched to {p['name']} ✅ Now what would you like to do?")
                    ))
        
        # "clear project" / "forget project" → clear_active_project directly
        if _msg_lower in ("clear project", "forget project", "clear active project", "clear active"):
            logger.info(f"{_src_tag} ⚡ Fast-path: clearing active project (no LLM call)")
            _executor = get_tool_executor()
            result = await _executor.execute(
                "clear_active_project",
                {},
                session_key=session_id,
                user_id=user_id,
            )
            await session_manager.update_last_used(session_id)
            return _finalize(text_response(
                result.get("message", "Cleared active project. ✅")
            ))
        
        # "which project am I using" / "current project" → get_active_project directly
        if _msg_lower in ("which project am i using", "current project", "which project", "what project am i using"):
            if active_project:
                logger.info(f"{_src_tag} ⚡ Fast-path: returning active project info (no LLM call)")
                await session_manager.update_last_used(session_id)
                return _finalize(text_response(
                    f"You are currently working with **{active_project['name']}** "
                    f"(domain: `{active_project['domain']}`)."
                ))
        
        # ── No active project + action keyword → instant selection ──
        # When user sends an action command (status, stop, start, restart,
        # logs, etc.) without an active project, return a selection prompt
        # immediately. Without this, the request goes to the LLM, which
        # calls a tool, which triggers the resolver to return "selection"
        # — a 3-20s wasted round-trip just to show a project picker.
        if not active_project and projects:
            _action_patterns = {
                "status", "start", "stop", "restart", "logs", "log",
                "start project", "stop project", "restart project",
                "project status", "get logs", "get status",
                "what's the status", "check status",
            }
            # Also match "start X", "stop X" where X isn't a project name
            _action_verbs = {"start", "stop", "restart", "status", "logs", "log"}
            _is_action = (
                _msg_lower in _action_patterns
                or any(_msg_lower.startswith(v + " ") for v in _action_verbs)
            )
            
            if _is_action:
                _options = [
                    {"label": f"{p['name']} ({p['domain']})", "value": p["domain"]}
                    for p in projects
                ]
                logger.info(f"[AI-CHAT] ⚡ Fast-path: action without project → instant selection ({len(_options)} projects, no LLM call)")
                await session_manager.update_last_used(session_id)
                return _finalize(selection_response(
                    message="Which project would you like to use?",
                    options=_options,
                    intent={"tool": "action", "args": {"original_message": message}},
                ))
        
        try:
            response = await _chat_with_tools_primary_then_openrouter(
                call_messages=messages,
                call_tools=tools,
                tool_choice="auto",
                temperature=0.1,
                max_tokens=1000,
                purpose="tool selection",
            )
        except Exception as e:
            logger.error(f"[AI-CHAT] Primary and fallback LLM failed: {e}")
            return _finalize(error_response(f"AI service error: {str(e)}"))
        
        # 6. Parse response
        tool_calls = glm_client.parse_tool_calls(response)
        
        if not tool_calls:
            # No tool calls - return text response
            text = glm_client.get_text_response(response)
            logger.info(f"[AI-CHAT] Text response: {text[:100]}")
            await session_manager.update_last_used(session_id)
            return _finalize(text_response(text))
        
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
            await session_manager.update_last_used(session_id)
            return _finalize(error_response(f"Tool '{tool_name}' is disabled and cannot be executed"))
        
        # 9. Validate args
        is_valid, error_msg = validate_tool_args(tool_name, args)
        if not is_valid:
            logger.warning(f"[AI-CHAT] Invalid args: {error_msg}")
            await session_manager.update_last_used(session_id)
            return _finalize(error_response(error_msg))
        
        # 10. Resolve project if needed
        tools_needing_project = [
            "start_project", "stop_project", "restart_project",
            "project_status", "get_logs", "set_active_project",
            "delete_project",
            "scheduler_list_jobs", "scheduler_create_job", "scheduler_clear_jobs"
        ]
        
        if tool_name in tools_needing_project:
            project_id = args.get("project_id")
            
            # For set_active_project, don't use active project as fallback
            # User wants to SWITCH projects, not use current one
            use_active_as_fallback = tool_name != "set_active_project"
            
            resolver = get_project_resolver()
            resolution = resolver.resolve(
                user_text=message,
                projects=projects,
                active_project=active_project if use_active_as_fallback else None,
                explicit_project_id=project_id
            )
            
            if resolution.status == "selection":
                # Return selection response
                # Ensure candidates exist and have at least one item
                if not resolution.candidates or len(resolution.candidates) == 0:
                    logger.warning(f"[AI-CHAT] Selection status but no candidates provided")
                    await session_manager.update_last_used(session_id)
                    return _finalize(error_response("No projects available for selection"))
                
                options = [
                    {"label": f"{p['name']} ({p['domain']})", "value": p["domain"]}
                    for p in resolution.candidates
                ]
                
                logger.info(f"[AI-CHAT] Returning selection with {len(options)} options")
                
                await session_manager.update_last_used(session_id)
                return _finalize(selection_response(
                    message=resolution.message,
                    options=options,
                    intent={"tool": tool_name, "args": args}
                ))
            
            elif resolution.status == "not_found":
                await session_manager.update_last_used(session_id)
                return _finalize(error_response(resolution.message))
            
            # Resolved - update args
            args["project_id"] = resolution.project["domain"]
        
        # 11. Execute tool
        executor = get_tool_executor()
        result = await executor.execute(tool_name, args, session_key=session_id, user_id=user_id)
        
        # 12. Handle result
        # SELECTION RESPONSE: Return immediately, bypass LLM summarization
        if result.get("type") == "selection" or result.get("status") == "selection":
            logger.info(f"[AI-CHAT] Selection response, returning structured data")
            await session_manager.update_last_used(session_id)
            return _finalize(result)
        
        if result["status"] == "confirmation_required":
            # Store pending intent in session
            await session_manager.set_pending_intent(session_id, result["intent"])
            await session_manager.update_last_used(session_id)
            return _finalize(confirmation_response(
                message=f"Do you want to {tool_name.replace('_', ' ')}?",
                intent=result["intent"]
            ))
        
        elif result["status"] == "success":
            # 13. Fast-path: return tool result directly without 2nd LLM call.
            # These tools already produce human-readable messages; calling the
            # LLM again just to rephrase adds ~1-20s latency for zero value.
            # Tools that return RAW data (get_logs, project_status) still need
            # the LLM to summarize, so they stay on the normal path.
            
            # Context tools → simple text_response
            _fast_text_tools = {
                "set_active_project",
                "clear_active_project",
                "get_active_project",
                "get_project_info",
            }
            
            # Action tools → execution_response with progress
            _fast_action_tools = {
                "start_project",
                "stop_project",
                "restart_project",
            }
            
            if tool_name in _fast_text_tools:
                logger.info(f"[AI-CHAT] ⚡ Fast-path: returning {tool_name} result without LLM summarization")
                await session_manager.update_last_used(session_id)
                return _finalize(text_response(
                    result.get("message", "Done.")
                ))
            
            if tool_name in _fast_action_tools:
                logger.info(f"[AI-CHAT] ⚡ Fast-path: returning {tool_name} result without LLM summarization")
                await session_manager.update_last_used(session_id)
                return _finalize(execution_response(
                    progress=[result],
                    text=result.get("message", f"{tool_name} completed."),
                ))
            
            # For action/info tools: send tool result back to LLM for natural language summarization
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
                final_response = await _chat_with_tools_primary_then_openrouter(
                    call_messages=messages,
                    call_tools=tools,
                    tool_choice="none",  # Force text response, no more tools
                    temperature=0.3,
                    max_tokens=500,
                    purpose=f"{tool_name} success summarization",
                )
                
                # Extract final text response
                final_text = glm_client.get_text_response(final_response)
                logger.info(f"[AI-CHAT] LLM summarized response: {final_text[:100]}")
                
                await session_manager.update_last_used(session_id)
                
                # Determine response type based on tool category
                action_tools = ["start_project", "stop_project", "restart_project", "delete_project", "clear_active_project"]
                
                if tool_name in action_tools:
                    # Action tools: return execution response with progress
                    return _finalize(execution_response(
                        progress=[result],
                        text=final_text
                    ))
                else:
                    # Info/context tools: return text response
                    return _finalize(text_response(final_text))
                    
            except Exception as e:
                logger.error(f"[AI-CHAT] LLM summarization failed: {e}")
                # Fallback: return tool message directly (should not happen)
                await session_manager.update_last_used(session_id)
                return _finalize(text_response(result.get("message", "Operation completed successfully")))
        
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
                final_response = await _chat_with_tools_primary_then_openrouter(
                    call_messages=messages,
                    call_tools=tools,
                    tool_choice="none",
                    temperature=0.3,
                    max_tokens=300,
                    purpose=f"{tool_name} error summarization",
                )
                
                final_text = glm_client.get_text_response(final_response)
                await session_manager.update_last_used(session_id)
                return _finalize(text_response(final_text))
                
            except Exception as e:
                logger.error(f"[AI-CHAT] Error summarization failed: {e}")
                await session_manager.update_last_used(session_id)
                return _finalize(error_response(result.get("message", "Tool execution failed"), result))
    
    except Exception as e:
        logger.error(f"[AI-CHAT] Unexpected error: {e}", exc_info=True)
        return error_response(f"Internal error: {str(e)}")


# ============================================================================
# HTTP Endpoint — thin wrapper around process_message()
# ============================================================================

@router.post("/chat", response_model=AIChatResponse)
async def ai_chat(request: AIChatRequest, authorization: Optional[str] = Header(None)):
    """
    Main AI chat endpoint (HTTP).
    Delegates to process_message() so web and Telegram share the same engine.
    """
    user_id = get_user_id_from_token(authorization)
    return await process_message(
        user_id=user_id,
        message=request.message,
        session_id=request.session_id,
        active_project_override=str(request.active_project) if request.active_project is not None else None,
        source="web",
    )


# ============================================================================
# Message History & Active Project Endpoints
# ============================================================================

@router.get("/messages")
async def get_chat_messages(
    project: str = Query(..., description="Project domain"),
    authorization: Optional[str] = Header(None),
):
    """
    Get persisted chat messages for a project (max 10, oldest→newest).
    Used by frontend to load conversation history on mount / project switch.
    """
    user_id = get_user_id_from_token(authorization)
    repo = ProjectChatRepository()
    messages = repo.get_messages(user_id, project)
    return {"messages": messages}


@router.get("/active-project")
async def get_active_project(
    authorization: Optional[str] = Header(None),
):
    """
    Get the user's active project domain + type from the users table.
    Returns {"project": "<domain>", "type": "<type_slug>"} or {"project": null, "type": null}.
    """
    user_id = get_user_id_from_token(authorization)
    repo = ProjectChatRepository()
    project = repo.get_active_project(user_id)

    project_type = None
    if project:
        with get_db() as conn:
            row = conn.execute("""
                SELECT pt.type as type_slug
                FROM projects p
                LEFT JOIN project_types pt ON p.type_id = pt.id
                WHERE p.domain = %s
            """, (project,)).fetchone()
            if row:
                project_type = row["type_slug"]

    return {"project": project, "type": project_type}


@router.delete("/messages")
async def clear_chat_history(
    project: str = Query(..., description="Project domain"),
    authorization: Optional[str] = Header(None),
):
    """
    Delete all persisted chat messages for a project.
    Used by frontend 'Clear History' button.
    """
    user_id = get_user_id_from_token(authorization)
    repo = ProjectChatRepository()
    deleted = repo.clear_messages(user_id, project)
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to clear chat history")
    logger.info(f"[AI-CHAT] Cleared chat history for project={project}, user={user_id}")
    return {"success": True}

