"""
Image handling utilities for clawd backend.

Saves base64 images to public directory and workspace for agent access.
"""
import os
import base64
import httpx
from datetime import datetime

# Configuration
IMAGES_DIR = "/root/clawd/public/images"
WORKSPACE_IMAGES_DIR = "/root/.openclaw/workspace/clawd-images"
IMAGES_BASE_URL = "http://195.200.14.37:8002/images"
CHAT_COMPLETION_API_URL = "http://localhost:18789"
CHAT_COMPLETION_TOKEN = "355fc5e1f0d6078a8a9a56f684d551d803f92decf956d11ca7494f0f461b470a"

def save_base64_image(base64_data: str, session_id: int) -> tuple:
    """
    Save base64 image data to both public directory and workspace.

    Args:
        base64_data: Base64 encoded image string
        session_id: Session ID for tracking

    Returns:
        Tuple of (public_filepath, workspace_path, http_url)
    """
    # Ensure both directories exist
    os.makedirs(IMAGES_DIR, exist_ok=True)
    os.makedirs(WORKSPACE_IMAGES_DIR, exist_ok=True)

    # Generate unique filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"session_{session_id}_{timestamp}.jpg"

    # Save to public directory (for HTTP serving)
    public_filepath = os.path.join(IMAGES_DIR, filename)

    # Save to workspace (for agent access)
    workspace_path = os.path.join(WORKSPACE_IMAGES_DIR, filename)

    # Decode and save image to both locations
    try:
        # Extract base64 data (remove data URL prefix if present)
        if base64_data.startswith('data:'):
            base64_data = base64_data.split(',')[1]  # Get data part after prefix

        image_data = base64.b64decode(base64_data)

        # Save to public directory
        with open(public_filepath, 'wb') as f:
            f.write(image_data)

        # Save to workspace directory
        with open(workspace_path, 'wb') as f:
            f.write(image_data)

        http_url = f"{IMAGES_BASE_URL}/{filename}"
        print(f"Image saved to public: {public_filepath}")
        print(f"Image saved to workspace: {workspace_path}")
        print(f"Accessible at: {http_url}")
        return (public_filepath, workspace_path, http_url)
    except Exception as e:
        print(f"Error saving image: {e}")
        raise

def delete_image(filepath: str) -> bool:
    """
    Delete image file from public directory.

    Args:
        filepath: Path to image file

    Returns:
        True if deleted, False otherwise
    """
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
            print(f"Image deleted from public: {filepath}")
            return True
        return False
    except Exception as e:
        print(f"Error deleting image: {e}")
        return False

async def call_chat_completion_with_image(workspace_image_path: str, session_key: str, prompt: str) -> dict:
    """
    Call OpenClaw chat completion API with an image workspace path.

    Args:
        workspace_image_path: Workspace path to image file
        session_key: Session key
        prompt: User's text prompt

    Returns:
        API response with assistant message
    """
    # Get just filename for workspace path reference
    image_filename = os.path.basename(workspace_image_path)

    # CRITICAL: Use "user" field to maintain session continuity in OpenClaw
    # Format: "adapter-session-{session_key}"
    user_field = f"adapter-session-{session_key}"

    # Send text with workspace path - agent will find and analyze the image
    request_body = {
        "model": "agent:main",
        "user": user_field,
        "messages": [
            {
                "role": "user",
                "content": f"{prompt}\n\n[Image: {image_filename}]"
            }
        ]
    }

    headers = {
        "Authorization": f"Bearer {CHAT_COMPLETION_TOKEN}",
    }

    print(f"[DEBUG] Sending request to completion API:")
    print(f"[DEBUG]   URL: {CHAT_COMPLETION_API_URL}/v1/chat/completions")
    print(f"[DEBUG]   Original session_key: {session_key}")
    print(f"[DEBUG]   Sending to OpenClaw with 'user' field: {user_field}")
    print(f"[DEBUG]   Workspace image path: {workspace_image_path}")
    print(f"[DEBUG]   Image filename: {image_filename}")

    try:
        # Use httpx module-level import from app.py
        client = httpx.AsyncClient(timeout=300)
        response = await client.post(
            f"{CHAT_COMPLETION_API_URL}/v1/chat/completions",
            json=request_body,
            headers=headers
        )
        print(f"[DEBUG] Response status: {response.status_code}")
        response.raise_for_status()
        result = response.json()
        print(f"[DEBUG] Response content: {result.get('choices', [{}])[0].get('message', {}).get('content', '')[:200]}...")
        print(f"Chat completion API called successfully with workspace image: {workspace_image_path}")
        return result
    except Exception as e:
        print(f"Error calling chat completion API: {e}")
        raise
