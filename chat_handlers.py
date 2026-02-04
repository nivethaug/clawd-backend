"""
Chat handlers module for Clawd Backend.
Handles streaming and non-streaming chat requests.
"""

import os
import json
from typing import AsyncGenerator
from httpx import AsyncClient

from fastapi import HTTPException
from image_handler import save_base64_image, call_chat_completion_with_image, delete_image

# Configuration from app.py (will be imported)
CLAWDBOT_BASE_URL = os.getenv("CLAWDBOT_BASE_URL", "http://localhost:18789")
CLAWDBOT_TOKEN = os.getenv("CLAWDBOT_TOKEN", "355fc5e1f0d6078a8a9a56f684d551d803f92decf956d11ca7494f0f461b470a")


async def generate_sse_stream(request, session_id, user_content):
    """
    Generate SSE stream for chat responses.
    
    Args:
        request: ChatRequest with image
        session_id: Session ID for image storage
        user_content: User message content
        
    Yields:
        SSE formatted strings
    """
    if request.image:
        # Handle image-based chat (non-streaming but wrapped in SSE)
        public_path, workspace_path, http_url = save_base64_image(request.image, session_id)

        result = await call_chat_completion_with_image(
            workspace_path,
            request.session_key,
            user_content
        )

        assistant_content = result.get('choices', [{}])[0].get('message', {}).get('content', 'No response from assistant')
        delete_image(public_path)

        event_data = json.dumps({
            'choices': [{'message': {'content': assistant_content}}]
        })
        yield f"data: {event_data}\n\n"
        yield "data: [DONE]\n\n"
        return

    # Handle text-based streaming chat
    try:
        # CRITICAL: Use "user" field to maintain session continuity in OpenClaw
        # Format: "adapter-session-{session_key}"
        user_field = f"adapter-session-{request.session_key}"
        
        # Debug logging to verify correct format
        print(f"[CHAT] Original session_key: {request.session_key}")
        print(f"[CHAT] Sending to OpenClaw with 'user' field: {user_field}")
        
        request_body = {
            "model": "agent:main",
            "user": user_field,
            "messages": [{"role": "user", "content": user_content}],
            "stream": True
        }

        headers = {
            "Authorization": f"Bearer {CLAWDBOT_TOKEN}",
        }

        async with AsyncClient(timeout=300) as client:
            async with client.stream(
                'POST',
                f"{CLAWDBOT_BASE_URL}/v1/chat/completions",
                json=request_body,
                headers=headers
            ) as stream_response:
                async for line in stream_response.aiter_lines():
                    if not line.strip():
                        continue

                    if line.startswith('data: '):
                        data = line[6:]

                        if data.strip() == '[DONE]':
                            yield "data: [DONE]\n\n"
                            break

                        try:
                            parsed = json.loads(data)

                            if parsed.get('choices') and parsed['choices']:
                                delta = parsed['choices'][0].get('delta', {})

                                if delta.get('content'):
                                    event_data = json.dumps({'choices': [{'delta': {'content': delta['content']}}]})
                                    yield f"data: {event_data}\n\n"
                        except:
                            continue

    except Exception as e:
        error_msg = f"Error: {str(e)}"
        event_data = json.dumps({'choices': [{'message': error_msg}]})
        yield f"data: {event_data}\n\n"
        yield "data: [DONE]\n\n"


async def handle_chat_with_image(request, session_id, user_content):
    """
    Handle chat request with image attachment.
    
    Args:
        request: ChatRequest with image data
        session_id: Session ID for image storage
        user_content: User message content
        
    Returns:
        Assistant response content string
    """
    try:
        public_path, workspace_path, http_url = save_base64_image(request.image, session_id)

        result = await call_chat_completion_with_image(
            workspace_path,
            request.session_key,
            user_content
        )

        assistant_content = result.get('choices', [{}])[0].get('message', {}).get('content', 'No response from assistant')
        delete_image(public_path)

        return assistant_content
    except Exception as e:
        return f"Error processing image: {str(e)}"


async def generate_sse_stream_with_db_save(request, session_id, user_content):
    """
    Generate SSE stream and save assistant message to database after completion.

    Args:
        request: ChatRequest
        session_id: Session ID for database
        user_content: User message content

    Yields:
        SSE formatted strings

    Returns:
        None (saves to database automatically)
    """
    # Import database here to avoid circular import
    from database import get_db

    assistant_content = ""

    async for chunk in generate_sse_stream(request, session_id, user_content):
        # Extract content from SSE chunks
        if chunk.startswith('data: {'):
            data = chunk[6:]
            if data.strip() != '[DONE]':
                try:
                    parsed = json.loads(data)
                    if parsed.get('choices') and parsed['choices']:
                        delta = parsed['choices'][0].get('delta', {})
                        content = delta.get('content', '')
                        if content:
                            assistant_content += content
                except:
                    pass
        # Yield chunk
        yield chunk

    # Save accumulated assistant message to database
    if assistant_content:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, 'assistant', assistant_content)
            )
            conn.commit()

async def handle_chat_text_only(request, user_content):
    """
    Handle text-only chat request (no image).
    
    Args:
        request: ChatRequest
        user_content: User message content
        
    Returns:
        Assistant response content string
    """
    try:
        # CRITICAL: Use "user" field to maintain session continuity in OpenClaw
        # Format: "adapter-session-{session_key}"
        user_field = f"adapter-session-{request.session_key}"
        
        # Debug logging to verify correct format
        print(f"[CHAT] Original session_key: {request.session_key}")
        print(f"[CHAT] Sending to OpenClaw with 'user' field: {user_field}")
        
        request_body = {
            "model": "agent:main",
            "user": user_field,
            "messages": [{"role": "user", "content": user_content}]
        }

        headers = {
            "Authorization": f"Bearer {CLAWDBOT_TOKEN}",
        }

        async with AsyncClient(timeout=300) as client:
            response = await client.post(
                f"{CLAWDBOT_BASE_URL}/v1/chat/completions",
                json=request_body,
                headers=headers
            )
            response.raise_for_status()
            result = response.json()
            return result.get('choices', [{}])[0].get('message', {}).get('content', 'No response from assistant')
    except Exception as e:
        return f"Error: {str(e)}"
