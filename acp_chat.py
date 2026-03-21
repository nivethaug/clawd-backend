#!/usr/bin/env python3
"""
ACP Chat Handler - Direct Claude API for frontend editing.

This module provides chat functionality using direct Claude API calls
with database-driven conversation history. Lighter and faster than OpenClaw.

Supports project types: website, telegrambot, discordbot, scheduler
"""

import os
import json
import logging
from typing import Optional, Dict, Any, List, AsyncGenerator

import anthropic

logger = logging.getLogger(__name__)

# Project type-specific system prompts
PROJECT_TYPE_PROMPTS = {
    "website": """You are an expert frontend developer assistant. Help the user build and modify their React/Vite website.

Focus areas:
- React components with TypeScript
- Tailwind CSS styling
- Vite configuration
- Modern web best practices

When the user asks for changes, provide clear explanations and code snippets.""",

    "telegrambot": """You are an expert Telegram bot developer assistant. Help the user build and modify their Telegram bot.

Focus areas:
- Telegram Bot API integration
- Node.js/Python bot frameworks
- Command handling and middleware
- Webhook configuration

When the user asks for changes, provide clear explanations and code snippets.""",

    "discordbot": """You are an expert Discord bot developer assistant. Help the user build and modify their Discord bot.

Focus areas:
- Discord.js / discord.py integration
- Slash commands and interactions
- Event handling
- Bot permissions and intents

When the user asks for changes, provide clear explanations and code snippets.""",

    "scheduler": """You are an expert scheduler/automation developer assistant. Help the user build and modify their scheduling application.

Focus areas:
- Cron jobs and scheduling logic
- Task queues and workers
- Timezone handling
- Job monitoring and logging

When the user asks for changes, provide clear explanations and code snippets.""",

    "default": """You are a helpful development assistant. Help the user with their project.

Provide clear explanations and code snippets when appropriate."""
}


async def handle_acp_chat(
    session_key: str,
    user_content: str,
    session_id: Optional[int] = None,
    project_type: str = "default"
) -> str:
    """
    Handle chat request using direct Claude API.
    
    Args:
        session_key: Session key for tracking
        user_content: User's message/prompt
        session_id: Session ID for fetching conversation history
        project_type: Project type for system prompt selection
    
    Returns:
        Assistant response content string
    """
    logger.info(f"[ACP-CHAT] Starting Claude direct chat for session {session_key}")
    logger.info(f"[ACP-CHAT] Project type: {project_type}")
    logger.info(f"[ACP-CHAT] User message: {user_content[:100]}...")
    
    # Get API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("[ACP-CHAT] ANTHROPIC_API_KEY not set")
        return "Error: Claude API key not configured. Please set ANTHROPIC_API_KEY environment variable."
    
    # Get conversation history from database
    history = await _get_conversation_history(session_id) if session_id else []
    logger.info(f"[ACP-CHAT] Loaded {len(history)} messages from history")
    
    # Get system prompt for project type
    system_prompt = PROJECT_TYPE_PROMPTS.get(project_type, PROJECT_TYPE_PROMPTS["default"])
    
    # Build messages array
    messages = history + [{"role": "user", "content": user_content}]
    
    try:
        # Create Anthropic client
        client = anthropic.Anthropic(api_key=api_key)
        
        # Call Claude API (non-streaming for simplicity)
        logger.info("[ACP-CHAT] Calling Claude API...")
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system_prompt,
            messages=messages
        )
        
        # Extract response text
        assistant_content = ""
        for block in response.content:
            if hasattr(block, 'text'):
                assistant_content += block.text
        
        logger.info(f"[ACP-CHAT] Response received: {len(assistant_content)} chars")
        
        return assistant_content
        
    except anthropic.APIError as e:
        logger.error(f"[ACP-CHAT] Claude API error: {e}")
        return f"Error: Claude API error - {str(e)}"
    except Exception as e:
        logger.error(f"[ACP-CHAT] Exception: {e}")
        return f"Error: Chat failed - {str(e)}"


async def handle_acp_chat_stream(
    session_key: str,
    user_content: str,
    session_id: Optional[int] = None,
    project_type: str = "default"
) -> AsyncGenerator[str, None]:
    """
    Handle streaming chat request using direct Claude API.
    
    Yields SSE-formatted chunks as they are received.
    
    Args:
        session_key: Session key for tracking
        user_content: User's message/prompt
        session_id: Session ID for conversation history
        project_type: Project type for system prompt
    
    Yields:
        SSE-formatted strings
    """
    logger.info(f"[ACP-CHAT-STREAM] Starting Claude streaming for session {session_key}")
    
    # Get API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        error_data = json.dumps({'choices': [{'delta': {'content': "Error: Claude API key not configured"}}]})
        yield f"data: {error_data}\n\n"
        yield "data: [DONE]\n\n"
        return
    
    # Get conversation history from database
    history = await _get_conversation_history(session_id) if session_id else []
    logger.info(f"[ACP-CHAT-STREAM] Loaded {len(history)} messages from history")
    
    # Get system prompt
    system_prompt = PROJECT_TYPE_PROMPTS.get(project_type, PROJECT_TYPE_PROMPTS["default"])
    
    # Build messages
    messages = history + [{"role": "user", "content": user_content}]
    
    try:
        client = anthropic.Anthropic(api_key=api_key)
        
        # Stream from Claude API
        logger.info("[ACP-CHAT-STREAM] Starting Claude stream...")
        with client.messages.stream(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system_prompt,
            messages=messages
        ) as stream:
            for text in stream.text_stream:
                # Format as SSE
                event_data = json.dumps({'choices': [{'delta': {'content': text}}]})
                yield f"data: {event_data}\n\n"
        
        yield "data: [DONE]\n\n"
        logger.info("[ACP-CHAT-STREAM] Stream completed")
        
    except anthropic.APIError as e:
        logger.error(f"[ACP-CHAT-STREAM] Claude API error: {e}")
        error_data = json.dumps({'choices': [{'delta': {'content': f"Error: {str(e)}"}}]})
        yield f"data: {error_data}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as e:
        logger.error(f"[ACP-CHAT-STREAM] Exception: {e}")
        error_data = json.dumps({'choices': [{'delta': {'content': f"Error: {str(e)}"}}]})
        yield f"data: {error_data}\n\n"
        yield "data: [DONE]\n\n"


async def _get_conversation_history(session_id: int) -> List[Dict[str, str]]:
    """
    Fetch conversation history from database.
    
    Only returns the last 2 sets of messages (4 messages total: 2 user + 2 assistant)
    to keep context focused and avoid token bloat.
    
    Args:
        session_id: Session ID to fetch messages for
    
    Returns:
        List of message dicts with 'role' and 'content' keys (max 4 messages)
    """
    history = []
    
    try:
        from database_adapter import get_db
        
        with get_db() as conn:
            # Fetch last 4 messages (2 sets of user+assistant exchanges)
            # Order DESC to get most recent, then reverse for chronological order
            rows = conn.execute(
                """
                SELECT role, content 
                FROM messages 
                WHERE session_id = ? 
                ORDER BY created_at DESC
                LIMIT 4
                """,
                (session_id,)
            ).fetchall()
            
            # Reverse to get chronological order (oldest first)
            rows = list(reversed(rows))
            
            for row in rows:
                # Handle both dict and tuple results
                if isinstance(row, dict):
                    role = row['role']
                    content = row['content']
                else:
                    role, content = row[0], row[1]
                
                # Map database roles to Claude format
                if role in ('user', 'assistant'):
                    history.append({"role": role, "content": content})
                    
        logger.info(f"[ACP-CHAT] Retrieved {len(history)} messages from database (last 2 sets)")
        
    except Exception as e:
        logger.error(f"[ACP-CHAT] Failed to get conversation history: {e}")
    
    return history


async def get_project_info_from_session(session_key: str) -> Dict[str, Any]:
    """
    Get project path and type from session key.
    
    Args:
        session_key: Session key
    
    Returns:
        Dict with 'project_path', 'project_type', 'session_id' or empty dict
    """
    try:
        from database_adapter import get_db
        
        with get_db() as conn:
            result = conn.execute(
                """
                SELECT s.id as session_id, p.project_path, p.project_type
                FROM sessions s 
                JOIN projects p ON s.project_id = p.id 
                WHERE s.session_key = ?
                """,
                (session_key,)
            ).fetchone()
            
            if result:
                if isinstance(result, dict):
                    return {
                        'session_id': result['session_id'],
                        'project_path': result['project_path'],
                        'project_type': result.get('project_type', 'default')
                    }
                else:
                    return {
                        'session_id': result[0],
                        'project_path': result[1],
                        'project_type': result[2] if len(result) > 2 else 'default'
                    }
        
        return {}
    except Exception as e:
        logger.error(f"[ACP-CHAT] Failed to get project info: {e}")
        return {}


# Synchronous wrapper for non-async contexts
def handle_acp_chat_sync(
    session_key: str,
    user_content: str,
    session_id: Optional[int] = None,
    project_type: str = "default"
) -> str:
    """
    Synchronous wrapper for ACP chat handler.
    
    Args:
        session_key: Session key
        user_content: User's message
        session_id: Session ID for history
        project_type: Project type
    
    Returns:
        Assistant response string
    """
    import asyncio
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(
            handle_acp_chat(session_key, user_content, session_id, project_type)
        )
    finally:
        loop.close()
