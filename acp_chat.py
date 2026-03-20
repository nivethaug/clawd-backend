#!/usr/bin/env python3
"""
ACP Chat Handler - Chat with ACP-Claude for frontend editing.

This module provides chat functionality that routes messages through
ACPX (ACP eXecutor) which allows Claude to edit frontend files.
"""

import os
import subprocess
import asyncio
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


async def handle_acp_chat(
    session_key: str,
    user_content: str,
    project_path: Optional[str] = None
) -> str:
    """
    Handle chat request using ACP-Claude (frontend editing agent).
    
    This runs ACPX with the user's message, allowing Claude to edit
    frontend files using its tools.
    
    Args:
        session_key: Session key for tracking
        user_content: User's message/prompt
        project_path: Optional project path (will be inferred if not provided)
    
    Returns:
        Assistant response content string
    """
    logger.info(f"[ACP-CHAT] Starting ACP chat for session {session_key}")
    logger.info(f"[ACP-CHAT] User message: {user_content[:100]}...")
    
    # Get project path from session if not provided
    if not project_path:
        project_path = await _get_project_path_from_session(session_key)
        if not project_path:
            return "Error: Could not determine project path for ACP chat. Please ensure you have an active project."
    
    # Construct frontend src path
    frontend_src_path = os.path.join(project_path, "frontend", "src")
    
    if not os.path.exists(frontend_src_path):
        logger.error(f"[ACP-CHAT] Frontend src path not found: {frontend_src_path}")
        return f"Error: Frontend source directory not found at {frontend_src_path}"
    
    logger.info(f"[ACP-CHAT] Using frontend path: {frontend_src_path}")
    
    # Build ACPX command
    # acpx --format quiet claude exec "<prompt>"
    prompt = _build_acp_prompt(user_content)
    
    cmd = [
        "acpx",
        "--format", "quiet",
        "claude",
        "exec",
        prompt
    ]
    
    logger.info(f"[ACP-CHAT] Running ACPX command...")
    logger.info(f"[ACP-CHAT] Working directory: {frontend_src_path}")
    
    try:
        # Run ACPX with timeout
        result = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=frontend_src_path
        )
        
        stdout, stderr = await asyncio.wait_for(
            result.communicate(),
            timeout=300  # 5 minute timeout
        )
        
        stdout_text = stdout.decode('utf-8') if stdout else ''
        stderr_text = stderr.decode('utf-8') if stderr else ''
        
        logger.info(f"[ACP-CHAT] ACPX exit code: {result.returncode}")
        
        if result.returncode == 0 and stdout_text:
            # Clean up the response
            response = stdout_text.strip()
            
            # Log truncated response
            if len(response) > 200:
                logger.info(f"[ACP-CHAT] Response: {response[:200]}... ({len(response)} chars)")
            else:
                logger.info(f"[ACP-CHAT] Response: {response}")
            
            return response
        else:
            error_msg = stderr_text or stdout_text or "Unknown error"
            logger.error(f"[ACP-CHAT] ACPX failed: {error_msg}")
            return f"Error: ACP chat failed - {error_msg[:500]}"
            
    except asyncio.TimeoutError:
        logger.error(f"[ACP-CHAT] ACPX timeout after 300 seconds")
        return "Error: ACP chat timed out. The request took too long to process."
    except Exception as e:
        logger.error(f"[ACP-CHAT] Exception: {e}")
        return f"Error: ACP chat failed - {str(e)}"


async def handle_acp_chat_stream(
    session_key: str,
    user_content: str,
    project_path: Optional[str] = None
):
    """
    Handle streaming chat request using ACP-Claude.
    
    Yields SSE-formatted chunks as they are received.
    
    Args:
        session_key: Session key for tracking
        user_content: User's message/prompt
        project_path: Optional project path
    
    Yields:
        SSE-formatted strings
    """
    import json
    
    logger.info(f"[ACP-CHAT-STREAM] Starting ACP streaming chat for session {session_key}")
    
    # Get full response first (ACPX doesn't support true streaming)
    response = await handle_acp_chat(session_key, user_content, project_path)
    
    # Yield as single SSE event
    event_data = json.dumps({'choices': [{'delta': {'content': response}}]})
    yield f"data: {event_data}\n\n"
    yield "data: [DONE]\n\n"


def _build_acp_prompt(user_content: str) -> str:
    """
    Build ACPX prompt from user content.
    
    Args:
        user_content: User's message
    
    Returns:
        Formatted prompt string for ACPX
    """
    # Add context about the editing task
    prompt = f"""The user wants to make changes to the frontend. Please help them by editing the appropriate files.

User request: {user_content}

Please make the necessary file edits to fulfill this request. After making changes, verify the build works correctly."""
    
    return prompt


async def _get_project_path_from_session(session_key: str) -> Optional[str]:
    """
    Get project path from session key.
    
    Args:
        session_key: Session key
    
    Returns:
        Project path or None if not found
    """
    try:
        from database_adapter import get_db
        
        with get_db() as conn:
            # Get session and project info
            result = conn.execute(
                """
                SELECT p.project_path 
                FROM sessions s 
                JOIN projects p ON s.project_id = p.id 
                WHERE s.session_key = ?
                """,
                (session_key,)
            ).fetchone()
            
            if result:
                return result['project_path'] if isinstance(result, dict) else result[0]
            
        return None
    except Exception as e:
        logger.error(f"[ACP-CHAT] Failed to get project path: {e}")
        return None


# Synchronous wrapper for use in non-async contexts
def handle_acp_chat_sync(session_key: str, user_content: str, project_path: Optional[str] = None) -> str:
    """
    Synchronous wrapper for ACP chat handler.
    
    Args:
        session_key: Session key for tracking
        user_content: User's message/prompt
        project_path: Optional project path
    
    Returns:
        Assistant response content string
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(handle_acp_chat(session_key, user_content, project_path))
    finally:
        loop.close()
