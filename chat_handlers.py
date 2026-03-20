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
    print(f"[SSE] Starting text-based stream for session {session_id}")
    try:
        # CRITICAL: Use "user" field to maintain session continuity in OpenClaw
        # Format: "adapter-session-{session_key}"
        user_field = f"adapter-session-{request.session_key}"

        # Inject system context (project path + rules)
        user_messages = [{"role": "user", "content": user_content}]
        messages_with_context = context_injector.inject_system_context(
            request.session_key,
            user_messages
        )

        request_body = {
            "model": "agent:main",
            "user": user_field,
            "messages": messages_with_context,
            "stream": True
        }

        headers = {
            "Authorization": f"Bearer {CLAWDBOT_TOKEN}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        print(f"[SSE] Opening stream connection to {CLAWDBOT_BASE_URL}/v1/chat/completions")
        print(f"[SSE] Request body: {json.dumps(request_body, indent=2)[:500]}")
        
        # First, try a NON-streaming request to verify OpenClaw responds
        print(f"[SSE] Testing non-streaming request first to verify OpenClaw responds...")
        async with AsyncClient(timeout=60) as test_client:
            test_body = request_body.copy()
            test_body["stream"] = False
            test_response = await test_client.post(
                f"{CLAWDBOT_BASE_URL}/v1/chat/completions",
                content=json.dumps(test_body),
                headers=headers
            )
            print(f"[SSE] Non-streaming test status: {test_response.status_code}")
            print(f"[SSE] Non-streaming test response length: {len(test_response.content)} bytes")
            print(f"[SSE] Non-streaming test response: {test_response.text[:500]}...")
            
            # If non-streaming works, use that content directly
            if test_response.status_code == 200 and test_response.content:
                print(f"[SSE] Non-streaming works! Using non-streaming response.")
                result = test_response.json()
                assistant_content = result.get('choices', [{}])[0].get('message', {}).get('content', 'No response')
                # Yield as single SSE event
                event_data = json.dumps({'choices': [{'delta': {'content': assistant_content}}]})
                yield f"data: {event_data}\n\n"
                yield "data: [DONE]\n\n"
                return
        
        # If non-streaming also fails, try streaming with aread() to see if there's ANY data
        print(f"[SSE] Non-streaming failed or empty. Trying streaming with aread()...")
        async with AsyncClient(timeout=60) as client:
            async with client.stream(
                'POST',
                f"{CLAWDBOT_BASE_URL}/v1/chat/completions",
                content=json.dumps(request_body),
                headers=headers
            ) as stream_response:
                print(f"[SSE] Stream response status: {stream_response.status_code}")
                print(f"[SSE] Response headers: {dict(stream_response.headers)}")
                
                # Try reading all content at once
                print(f"[SSE] Attempting to read all stream content with aread()...")
                all_content = await stream_response.aread()
                print(f"[SSE] Total content received: {len(all_content)} bytes")
                print(f"[SSE] Content preview: {repr(all_content[:500])}")
                
                if all_content:
                    # Process the content
                    text = all_content.decode('utf-8')
                    for line in text.split('\n'):
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
                            except json.JSONDecodeError:
                                pass
                else:
                    print(f"[SSE] No content received from stream!")
                    yield f"data: {json.dumps({'error': 'No response from AI service'})}\n\n"
                    yield "data: [DONE]\n\n"

    except Exception as e:
        print(f"[SSE] Stream error: {e}")
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


class StreamState:
    """Shared state for streaming response - survives client disconnect."""
    def __init__(self):
        self.content = ""
        self.session_id = None
        self.saved = False


def save_stream_to_db(state: StreamState):
    """Save accumulated stream content to database. Called as background task."""
    from database_adapter import get_db

    print(f"[STREAM] Background save called - saved={state.saved}, content_len={len(state.content)}, session={state.session_id}")

    if state.saved or not state.content:
        print(f"[STREAM] Skipping save - already saved or no content")
        return

    state.saved = True
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                (state.session_id, 'assistant', state.content)
            )
            conn.commit()
        print(f"[STREAM] ✓ Saved {len(state.content)} chars to session {state.session_id}")
    except Exception as db_error:
        print(f"CRITICAL: Failed to save assistant message to database: {db_error}")
        print(f"  Session ID: {state.session_id}")
        print(f"  Content length: {len(state.content)} chars")


async def generate_sse_stream_with_db_save(request, session_id, user_content, state: StreamState = None):
    """
    Generate SSE stream and save assistant message to database after completion.
    GUARANTEED to save message even if network disconnects or stream fails.

    Args:
        request: ChatRequest
        session_id: Session ID for database
        user_content: User message content
        state: Shared StreamState object (created if None)

    Yields:
        SSE formatted strings

    Returns:
        None (saves to database automatically via background task)
    """
    # Create or use shared state
    if state is None:
        state = StreamState()
    state.session_id = session_id

    print(f"[STREAM] Starting stream for session {session_id}")

    try:
        chunk_count = 0
        async for chunk in generate_sse_stream(request, session_id, user_content):
            chunk_count += 1
            print(f"[STREAM] Chunk #{chunk_count}: {repr(chunk[:100])}...")  # Debug: show first 100 chars
            
            # Extract content from SSE chunks
            if chunk.startswith('data: '):
                data = chunk[6:].strip()  # Strip whitespace/newlines
                if data and data != '[DONE]':
                    try:
                        parsed = json.loads(data)
                        if parsed.get('choices') and parsed['choices']:
                            delta = parsed['choices'][0].get('delta', {})
                            content = delta.get('content', '')
                            if content:
                                state.content += content
                                print(f"[STREAM] Accumulated content, total: {len(state.content)} chars")
                    except json.JSONDecodeError as je:
                        print(f"[STREAM] JSON decode error: {je}")
            # Yield chunk
            yield chunk

        print(f"[STREAM] Completed {chunk_count} chunks, accumulated {len(state.content)} chars")

    except Exception as e:
        print(f"[STREAM] Error: {e}")
        # CRITICAL: Network failure or stream error - save partial content + error
        error_msg = f"\n\n[Network Error: Stream interrupted. Partial response saved.]"

        if state.content:
            state.content += error_msg
        else:
            state.content = f"Error: Unable to complete response due to network issue. Please try again."

        # Yield error to client
        event_data = json.dumps({'choices': [{'delta': {'content': error_msg}}]})
        yield f"data: {event_data}\n\n"
        yield "data: [DONE]\n\n"

    # Save to DB (also called as background task for guaranteed save)
    save_stream_to_db(state)

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
