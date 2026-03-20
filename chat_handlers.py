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
from context_injector import ContextInjector

# Configuration from app.py (will be imported)
CLAWDBOT_BASE_URL = os.getenv("CLAWDBOT_BASE_URL", "http://localhost:18789")
CLAWDBOT_TOKEN = os.getenv("CLAWDBOT_TOKEN", "355fc5e1f0d6078a8a9a56f684d551d803f92decf956d11ca7494f0f461b470a")

# Get singleton instance (no more duplicate ContextInjector instances)
context_injector = ContextInjector()


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
        # Clear image from both public and workspace directories
        delete_image(public_path, workspace_path)

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

        # Inject system context (project path + rules)
        user_messages = [{"role": "user", "content": user_content}]
        messages_with_context = context_injector.inject_system_context(
            request.session_key,
            user_messages
        )

        # Debug: Log the messages being sent
        for i, msg in enumerate(messages_with_context):
            role = msg.get("role", "unknown")
            content_preview = msg.get("content", "")[:100]

        request_body = {
            "model": "agent:main",
            "user": user_field,
            "messages": messages_with_context,
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
    public_path = None
    workspace_path = None
    try:
        public_path, workspace_path, http_url = save_base64_image(request.image, session_id)

        # Inject system context for image chat
        # Note: call_chat_completion_with_image handles the actual API call
        # System context injection for images will be handled there if needed
        result = await call_chat_completion_with_image(
            workspace_path,
            request.session_key,
            user_content
        )

        assistant_content = result.get('choices', [{}])[0].get('message', {}).get('content', 'No response from assistant')
        return assistant_content
    except Exception as e:
        return f"Error processing image: {str(e)}"
    finally:
        # ALWAYS clear image from both directories after assistant replies
        if public_path or workspace_path:
            delete_image(public_path, workspace_path)


async def generate_sse_stream_with_db_save(request, session_id, user_content):
    """
    Generate SSE stream and save assistant message to database after completion.
    GUARANTEED to save message even if network disconnects or stream fails.

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
    from database_adapter import get_db

    assistant_content = ""
    error_occurred = False

    try:
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

    except Exception as e:
        # CRITICAL: Network failure or stream error - save partial content + error
        error_occurred = True
        error_msg = f"\n\n[Network Error: Stream interrupted. Partial response saved.]"
        
        if assistant_content:
            assistant_content += error_msg
        else:
            assistant_content = f"Error: Unable to complete response due to network issue. Please try again."
        
        # Yield error to client
        event_data = json.dumps({'choices': [{'delta': {'content': error_msg}}]})
        yield f"data: {event_data}\n\n"
        yield "data: [DONE]\n\n"

    finally:
        # GUARANTEED: Save accumulated assistant message to database (even if partial or error)
        if assistant_content:
            try:
                with get_db() as conn:
                    conn.execute(
                        "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                        (session_id, 'assistant', assistant_content)
                    )
                    conn.commit()
            except Exception as db_error:
                # Last resort: log if database save fails
                print(f"CRITICAL: Failed to save assistant message to database: {db_error}")
                print(f"  Session ID: {session_id}")
                print(f"  Content length: {len(assistant_content)} chars")

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

        # Inject system context (project path + rules)
        user_messages = [{"role": "user", "content": user_content}]
        messages_with_context = context_injector.inject_system_context(
            request.session_key,
            user_messages
        )

        request_body = {
            "model": "agent:main",
            "user": user_field,
            "messages": messages_with_context
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
