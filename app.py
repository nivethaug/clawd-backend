import os
import uuid
import json
import shutil
import re
import logging
from datetime import datetime
from typing import AsyncGenerator, Any, Optional
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, Request, Body
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from httpx import AsyncClient

import image_handler
from database import get_db, init_schema
from project_manager import ProjectFileManager
from chat_handlers import generate_sse_stream, generate_sse_stream_with_db_save, handle_chat_with_image, handle_chat_text_only
from file_utils import FileUtils
from completion_service import CompletionService

# ============================================================================
# Logging
# ============================================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# Configuration
# ============================================================================

CLAWDBOT_BASE_URL = os.getenv("CLAWDBOT_BASE_URL", "http://localhost:18789")
CLAWDBOT_TIMEOUT = int(os.getenv("CLAWDBOT_TIMEOUT", "300"))
CLAWDBOT_TOKEN = os.getenv("CLAWDBOT_TOKEN", "355fc5e1f0d6078a8a9a56f684d551d803f92decf956d11ca7494f0f461b470a")

DB_PATH = os.getenv("DB_PATH", "/root/clawd/clawdbot_adapter.db")

DEFAULT_AGENT_ID = "main"
DEFAULT_CHANNEL = "webchat"

IMAGE_MODEL = "zai/glm-4.6v"
TEXT_MODEL = "agent:main"

CLAWDBOT_SESSIONS_PATH = os.path.expanduser("~/.clawdbot/agents/main/sessions/sessions.json")

IMAGES_DIR = "/root/clawd/public/images"
os.makedirs(IMAGES_DIR, exist_ok=True)

IMAGES_BASE_URL = "http://195.200.14.37:8002/images"

BASE_PROJECTS_DIR = "/var/lib/openclaw/projects"
os.makedirs(BASE_PROJECTS_DIR, exist_ok=True)

# ============================================================================
# Initialize Schema
# ============================================================================

init_schema()

# ============================================================================
# Pydantic Models
# ============================================================================

class Message(BaseModel):
    id: Optional[int] = None
    role: str
    content: str

class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    image: Optional[str] = None
    created_at: datetime

class ProjectResponse(BaseModel):
    id: int
    user_id: int
    name: str
    domain: str
    description: Optional[str] = None
    project_path: Optional[str] = None
    type_id: Optional[int] = None
    created_at: str

class ProjectTypeResponse(BaseModel):
    id: int
    type: str
    display_name: str

class SessionResponse(BaseModel):
    id: int
    project_id: int
    session_key: str
    label: str
    archived: int = 0
    scope: Optional[str] = None
    channel: str
    agent_id: str
    created_at: str
    last_used_at: Optional[str] = None

class CreateProjectRequest(BaseModel):
    name: str
    domain: str = Field(..., min_length=3, max_length=50)
    description: Optional[str] = None
    user_id: Optional[int] = None
    type_id: Optional[int] = Field(None, alias="typeId")

class CreateSessionRequest(BaseModel):
    label: str
    project_id: int = 1

class ChatRequest(BaseModel):
    session_key: str
    messages: list[Message]
    stream: bool = False
    image: Optional[str] = None

class ChatResponse(BaseModel):
    id: int
    role: str
    content: str
    created_at: str

# ============================================================================
# File API Models
# ============================================================================

class FileNode(BaseModel):
    type: str  # 'file' or 'folder'
    name: str
    path: str
    size: Optional[int] = None
    children: Optional[list['FileNode']] = None

class FileContent(BaseModel):
    content: str
    is_binary: bool
    size: Optional[int] = None

class SaveFileRequest(BaseModel):
    content: str

class SaveFileResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    size: Optional[int] = None

# ============================================================================
# AI Chat Completion Models
# ============================================================================

class ChatMessage(BaseModel):
    role: str = Field(..., description="Message role (user or assistant)")
    content: str = Field(..., description="Message content")

class CompletionRequest(BaseModel):
    projectType: str = Field(..., description="Type of project (website, telegrambot, discordbot, tradingbot, scheduler, custom)")
    mode: str = Field(..., description="Operation mode (create or modify)")
    messages: list[ChatMessage] = Field(..., description="Array of chat messages (conversation history)")

class CompletionResponse(BaseModel):
    success: bool
    message: Optional[dict] = None
    error: Optional[str] = None

# ============================================================================
# Subdomain Validation
# ============================================================================

def validate_subdomain(domain: str) -> bool:
    """
    Validate subdomain format.

    Rules:
    - Lowercase only
    - Only a-z, 0-9, hyphens
    - No dots, underscores, spaces, or special characters
    - Must start with a letter
    - Length: 3-50 characters

    Args:
        domain: Subdomain string to validate

    Returns:
        True if valid, False otherwise
    """
    # Check length
    if len(domain) < 3 or len(domain) > 50:
        return False

    # Check if lowercase
    if domain != domain.lower():
        return False

    # Check format: lowercase letters, numbers, hyphens only, must start with letter
    pattern = r'^[a-z][a-z0-9-]*$'
    return bool(re.match(pattern, domain))

# ============================================================================
# Initialize Completion Service
# ============================================================================

completion_service = CompletionService()

# ============================================================================
# API Routes
# ============================================================================

app = FastAPI(
    title="Clawdbot Adapter API",
    description="Session-isolated adapter API for Clawdbot",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/images", StaticFiles(directory=IMAGES_DIR), name="images")

@app.get("/projects", response_model=list[ProjectResponse])
async def get_projects():
    with get_db() as conn:
        projects = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    
    return [ProjectResponse(**dict(p)) for p in projects]

@app.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(request: CreateProjectRequest):
    # Validate subdomain format
    if not validate_subdomain(request.domain):
        raise HTTPException(
            status_code=400,
            detail="Invalid subdomain format. Must be 3-50 characters, lowercase letters, numbers, hyphens only, must start with a letter."
        )

    # Default to user_id=1 if not provided
    user_id = request.user_id if request.user_id is not None else 1

    # Check for duplicate domain
    with get_db() as conn:
        existing_domain = conn.execute(
            "SELECT id FROM projects WHERE domain = ?",
            (request.domain,)
        ).fetchone()
        if existing_domain:
            raise HTTPException(
                status_code=409,
                detail=f"Domain '{request.domain}' is already in use. Please choose a different subdomain."
            )

    # Handle type_id: default to Website (id=1) if not provided or invalid
    type_id = None
    if request.type_id is not None:
        # Validate that the type_id exists
        with get_db() as conn:
            type_exists = conn.execute(
                "SELECT id FROM project_types WHERE id = ?",
                (request.type_id,)
            ).fetchone()
            if type_exists:
                type_id = request.type_id
            else:
                # Reject if type_id is provided but invalid
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid type_id: {request.type_id}. Project type does not exist."
                )

    # If type_id is None (not provided), default to Website
    if type_id is None:
        with get_db() as conn:
            website_type = conn.execute(
                "SELECT id FROM project_types WHERE type = 'website'"
            ).fetchone()
            if website_type:
                type_id = website_type['id']

    # Step 1: Get project_id first to use in folder naming
    with get_db() as conn:
        conn.execute(
            "INSERT INTO projects (user_id, name, domain, description, project_path, type_id) VALUES (?, ?, ?, ?, '', ?)",
            (user_id, request.name, request.domain, request.description, type_id)
        )
        conn.commit()
        project_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Step 2: Create project folder with Git initialization
    project_manager = ProjectFileManager()
    project_folder_path, folder_success = project_manager.create_project_with_git(project_id, request.name)

    if not folder_success:
        # Rollback: Delete project from database
        with get_db() as conn:
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()

        # Abort: Raise error to client
        raise HTTPException(
            status_code=500,
            detail="Failed to create project folder, Git repository, and required files"
        )

    # Step 3: Update database with project_path
    with get_db() as conn:
        conn.execute(
            "UPDATE projects SET project_path = ? WHERE id = ?",
            (project_folder_path, project_id)
        )
        conn.commit()

    return ProjectResponse(
        id=project_id,
        user_id=user_id,
        name=request.name,
        domain=request.domain,
        description=request.description,
        project_path=project_folder_path,
        type_id=type_id,
        created_at=datetime.now().isoformat()
    )

@app.get("/project-types", response_model=list[ProjectTypeResponse])
async def get_project_types():
    """Get all available project types."""
    with get_db() as conn:
        types = conn.execute("SELECT id, type, display_name FROM project_types ORDER BY id").fetchall()
    
    return [ProjectTypeResponse(**dict(t)) for t in types]

@app.delete("/projects/{project_id}")
async def delete_project(project_id: int):
    # Step 1: Get all session_keys linked to this project before deletion
    with get_db() as conn:
        sessions_to_delete = conn.execute(
            "SELECT session_key FROM sessions WHERE project_id = ?",
            (project_id,)
        ).fetchall()
        session_keys = [row['session_key'] for row in sessions_to_delete]
        
        # Step 2: Delete messages first (foreign key dependency)
        conn.execute("DELETE FROM messages WHERE session_id IN (SELECT id FROM sessions WHERE project_id = ?)", (project_id,))
        
        # Step 3: Delete sessions from backend database
        conn.execute("DELETE FROM sessions WHERE project_id = ?", (project_id,))
        
        # Step 4: Delete project from database
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        
        conn.commit()
    
    # Step 5: Delete corresponding OpenClaw sessions
    # OpenClaw session key format: "agent:main:openai-user:adapter-session-{session_key}"
    # Note: The key prefix may vary, so we match by suffix
    sessions_json_path = os.path.expanduser("~/.openclaw/agents/main/sessions/sessions.json")
    
    if os.path.exists(sessions_json_path):
        try:
            with open(sessions_json_path, 'r') as f:
                sessions_data = json.load(f)
            
            # Find OpenClaw session keys to delete by matching suffix
            # The full format is: "agent:main:openai-user:adapter-session-{session_key}"
            openclaw_keys_to_delete = []
            for key in sessions_data.keys():
                for session_key in session_keys:
                    if key.endswith(f"adapter-session-{session_key}"):
                        openclaw_keys_to_delete.append(key)
                        break  # Each session key matches at most once
            
            # Delete entries from sessions.json
            deleted_count = 0
            for key in openclaw_keys_to_delete:
                if key in sessions_data:
                    # Get session_id before deleting the entry
                    session_id = sessions_data.get(key, {}).get('sessionId')
                    
                    # Delete the entry
                    del sessions_data[key]
                    deleted_count += 1
                    
                    # Optionally delete the corresponding JSONL transcript file
                    if session_id:
                        jsonl_path = os.path.join(os.path.dirname(sessions_json_path), f"{session_id}.jsonl")
                        if os.path.exists(jsonl_path):
                            os.remove(jsonl_path)
            
            # Write back the updated sessions.json
            with open(sessions_json_path, 'w') as f:
                json.dump(sessions_data, f, indent=2)
            
            print(f"Deleted {deleted_count} OpenClaw sessions for project {project_id}")
            
        except Exception as e:
            # Log error but don't fail the project deletion
            print(f"Warning: Failed to delete OpenClaw sessions: {e}")
    
    return {"status": "deleted", "message": "Project deleted"}

@app.get("/projects/{project_id}/sessions", response_model=list[SessionResponse])
async def get_sessions(project_id: int):
    with get_db() as conn:
        sessions = conn.execute(
            "SELECT * FROM sessions WHERE project_id = ? AND archived = 0 ORDER BY created_at DESC",
            (project_id,)
        ).fetchall()
    
    return [SessionResponse(**dict(s)) for s in sessions]

@app.post("/projects/{project_id}/sessions", response_model=SessionResponse, status_code=201)
async def create_session(project_id: int, request: CreateSessionRequest):
    session_key = str(uuid.uuid4())
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (project_id, session_key, label, channel, agent_id) VALUES (?, ?, ?, ?, ?)",
            (project_id, session_key, request.label, DEFAULT_CHANNEL, DEFAULT_AGENT_ID)
        )
        conn.commit()
        result = conn.execute(
            "SELECT * FROM sessions WHERE session_key = ?",
            (session_key,)
        ).fetchone()

        return SessionResponse(
            id=result[0],
            project_id=result[1],
            session_key=result[2],
            label=result[3],
            archived=result[4] or 0,
            scope=result[5],
            channel=result[6],
            agent_id=result[7],
            created_at=result[8],
            last_used_at=result[9]
        )

@app.delete("/sessions/{session_id}")
async def delete_session(session_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
    
    return {"status": "deleted", "message": "Session deleted"}

@app.delete("/projects/{project_id}/sessions/{session_id}")
async def delete_project_session(project_id: int, session_id: int):
    """Delete a specific session within a project."""
    # Step 1: Get session_key before deletion (needed for OpenClaw cleanup)
    with get_db() as conn:
        session_info = conn.execute(
            "SELECT session_key FROM sessions WHERE id = ? AND project_id = ?",
            (session_id, project_id)
        ).fetchone()

        if not session_info:
            raise HTTPException(status_code=404, detail="Session not found in this project")

        session_key = session_info['session_key']

        # Step 2: Delete messages and session from backend database
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id = ? AND project_id = ?", (session_id, project_id))
        conn.commit()

    # Step 3: Delete corresponding OpenClaw session
    # OpenClaw session key format: "agent:main:openai-user:adapter-session-{session_key}"
    sessions_json_path = os.path.expanduser("~/.openclaw/agents/main/sessions/sessions.json")

    if os.path.exists(sessions_json_path):
        try:
            with open(sessions_json_path, 'r') as f:
                sessions_data = json.load(f)

            # Find OpenClaw session key to delete by matching suffix
            openclaw_key_to_delete = None
            for key in sessions_data.keys():
                if key.endswith(f"adapter-session-{session_key}"):
                    openclaw_key_to_delete = key
                    break

            # Delete entry from sessions.json if found
            if openclaw_key_to_delete:
                # Get session_id before deleting entry
                oclaw_session_id = sessions_data.get(openclaw_key_to_delete, {}).get('sessionId')

                # Delete entry
                del sessions_data[openclaw_key_to_delete]

                # Optionally delete corresponding JSONL transcript file
                if oclaw_session_id:
                    jsonl_path = os.path.join(os.path.dirname(sessions_json_path), f"{oclaw_session_id}.jsonl")
                    if os.path.exists(jsonl_path):
                        os.remove(jsonl_path)

                # Write back updated sessions.json
                with open(sessions_json_path, 'w') as f:
                    json.dump(sessions_data, f, indent=2)

                print(f"Deleted OpenClaw session {openclaw_key_to_delete} for session {session_key}")

        except Exception as e:
            # Log error but don't fail session deletion
            print(f"Warning: Failed to delete OpenClaw session: {e}")

    return {"status": "deleted", "message": "Session deleted"}

@app.get("/sessions/{session_id}/messages", response_model=list[MessageResponse])
async def get_session_messages(session_id: int):
    with get_db() as conn:
        messages = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,)
        ).fetchall()
    
    return [MessageResponse(**dict(m)) for m in messages]

@app.post("/chat/stream")
async def chat_stream_endpoint(request: ChatRequest):
    """Handle streaming chat requests using extracted chat handlers."""
    with get_db() as conn:
        session = conn.execute(
            "SELECT * FROM sessions WHERE session_key = ? AND archived = 0",
            (request.session_key,)
        ).fetchone()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        session_id = session['id']

        user_messages = [msg for msg in request.messages if msg.role == 'user']

        if not user_messages:
            raise HTTPException(status_code=400, detail="No user message provided")

        last_user_message = user_messages[-1]
        user_content = last_user_message.content

        # Save user message to database and commit
        conn.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
            (session_id, 'user', user_content)
        )
        conn.commit()

    # Return SSE response directly with database save
    return StreamingResponse(
        generate_sse_stream_with_db_save(request, session_id, user_content),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        }
    )

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    """Handle both streaming and non-streaming chat requests."""

    # Handle streaming request by delegating to stream endpoint
    if request.stream:
        return await chat_stream_endpoint(request)

    # Handle non-streaming request
    with get_db() as conn:
        session = conn.execute(
            "SELECT * FROM sessions WHERE session_key = ? AND archived = 0",
            (request.session_key,)
        ).fetchone()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        session_id = session['id']

        user_messages = [msg for msg in request.messages if msg.role == 'user']

        if not user_messages:
            raise HTTPException(status_code=400, detail="No user message provided")

        last_user_message = user_messages[-1]
        user_content = last_user_message.content

        # Insert user message
        conn.execute(
            "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
            (session_id, 'user', user_content)
        )

        assistant_content = ""
        image_to_store = None

        if request.image:
            assistant_content = await handle_chat_with_image(request, session_id, user_content)
            image_to_store = request.image  # Store the base64 image data
        elif not request.image and not request.stream:
            assistant_content = await handle_chat_text_only(request, user_content)

        # Insert assistant message with image field
        if image_to_store:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, image) VALUES (?, ?, ?, ?)",
                (session_id, 'assistant', assistant_content, image_to_store)
            )
        else:
            conn.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, 'assistant', assistant_content)
            )

        conn.execute(
            "UPDATE sessions SET last_used_at = CURRENT_TIMESTAMP WHERE id = ?",
            (session_id,)
        )

        conn.commit()

        return ChatResponse(
            id=0,
            role="assistant",
            content=assistant_content,
            created_at=datetime.now().isoformat()
        )

# ============================================================================
# File API Routes
# ============================================================================

@app.get("/projects/{project_id}/files", response_model=list[FileNode])
async def get_project_files(project_id: int):
    """
    Get file tree for a project.

    Args:
        project_id: Project ID

    Returns:
        List of file nodes (files and folders)
    """
    # Get project path from database
    with get_db() as conn:
        project = conn.execute(
            "SELECT project_path FROM projects WHERE id = ?",
            (project_id,)
        ).fetchone()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project_path = project["project_path"]
    if not project_path:
        raise HTTPException(status_code=400, detail="Project has no file system path")

    # Build file tree
    try:
        file_tree = FileUtils.build_file_tree(project_path)
        return file_tree
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build file tree: {str(e)}")


@app.get("/projects/{project_id}/files/{file_path:path}", response_model=FileContent)
async def get_file_content(project_id: int, file_path: str):
    """
    Get file content for a specific file.

    Args:
        project_id: Project ID
        file_path: Relative path to file

    Returns:
        File content and metadata
    """
    # Get project path from database
    with get_db() as conn:
        project = conn.execute(
            "SELECT project_path FROM projects WHERE id = ?",
            (project_id,)
        ).fetchone()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project_path = project["project_path"]
    if not project_path:
        raise HTTPException(status_code=400, detail="Project has no file system path")

    # Read file
    try:
        file_data = FileUtils.read_file(project_path, file_path)
        return FileContent(**file_data)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {str(e)}")


@app.put("/projects/{project_id}/files/{file_path:path}")
async def save_file_content(
    project_id: int,
    file_path: str,
    request_data: SaveFileRequest
):
    """
    Save file content.

    Args:
        project_id: Project ID
        file_path: Relative path to file (from URL)
        request_data: Request body with 'content' field

    Returns:
        Save result
    """

    # Get project path from database
    with get_db() as conn:
        project = conn.execute(
            "SELECT project_path FROM projects WHERE id = ?",
            (project_id,)
        ).fetchone()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    project_path = project["project_path"]
    if not project_path:
        raise HTTPException(status_code=400, detail="Project has no file system path")

    # Write file
    try:
        result = FileUtils.write_file(project_path, file_path, request_data.content)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "clawdbot_url": CLAWDBOT_BASE_URL,
        "clawdbot_token": CLAWDBOT_TOKEN[:16] + "...",
        "images_dir": IMAGES_DIR,
        "images_base_url": IMAGES_BASE_URL,
        "image_handling": "workspace_and_text_reference",
    }

@app.post("/test")
async def test_endpoint(data: dict):
    return {"received": data}

# ============================================================================
# Session Details API - Calls OpenClaw Status Endpoint
# ============================================================================

class SessionDetailResponse(BaseModel):
    """Full session object from OpenClaw status endpoint"""
    session_key: str  # Database session_key (input)
    session_id: str  # OpenClaw sessionId
    agent_id: str
    kind: Optional[str] = None
    model: Optional[str] = None
    context_tokens: Optional[int] = None
    token_usage: Optional[dict] = None
    timestamps: Optional[dict] = None
    flags: Optional[list] = None
    # Include any other fields from the session object


@app.get("/sessions/details", response_model=SessionDetailResponse)
async def get_session_details(key: str):
    """
    Get full session details from OpenClaw by database session_key.

    This endpoint:
    1. Accepts a database session_key (UUID)
    2. Constructs the OpenClaw session key: agent:main:openai-user:adapter-session-{session_key}
    3. Looks up the session in OpenClaw's sessions.json
    4. Returns the full session object with all fields

    Args:
        key: The database session_key (UUID) to look up

    Returns:
        Full session object with all fields from OpenClaw including:
        - session_id (OpenClaw sessionId)
        - model, token usage, timestamps, flags, etc.

    Raises:
        400: If key is empty or invalid
        404: If session_key not found in OpenClaw
        500: If unable to read OpenClaw sessions file
    """
    # Validate session_key is not empty
    if not key or key.strip() == "":
        raise HTTPException(status_code=400, detail="session_key (key parameter) cannot be empty")

    # OpenClaw sessions file path
    sessions_json_path = os.path.expanduser("~/.openclaw/agents/main/sessions/sessions.json")

    # Read the sessions.json file
    if not os.path.exists(sessions_json_path):
        raise HTTPException(
            status_code=500,
            detail="OpenClaw sessions file not found - OpenClaw gateway may not be running"
        )

    try:
        with open(sessions_json_path, 'r') as f:
            sessions_data = json.load(f)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse OpenClaw sessions file: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read OpenClaw sessions file: {str(e)}"
        )

    # Construct the OpenClaw session key from the database session_key
    # Format: agent:main:openai-user:adapter-session-{session_key}
    openclaw_session_key = f"agent:main:openai-user:adapter-session-{key}"

    # Search for the matching OpenClaw session
    found_session = sessions_data.get(openclaw_session_key)

    # If not found, return 404
    if not found_session:
        raise HTTPException(
            status_code=404,
            detail=f"Session with key '{key}' not found in OpenClaw"
        )

    # Build the response object from the session data
    # Extract common fields; the full session object is returned
    response_data = {
        "session_key": key,  # Database session_key (input)
        "session_id": found_session.get("sessionId"),  # OpenClaw sessionId
        "agent_id": found_session.get("agentId", "main"),  # Derive from session object
        "kind": found_session.get("chatType"),
        "model": found_session.get("model"),
        "context_tokens": found_session.get("contextTokens"),
        "token_usage": {
            "input_tokens": found_session.get("inputTokens"),
            "output_tokens": found_session.get("outputTokens"),
            "total_tokens": found_session.get("totalTokens"),
            "remaining_tokens": max(
                (found_session.get("contextTokens") or 0) - (found_session.get("totalTokens") or 0),
                0
            ),
            "percent_used": (
                round(found_session["totalTokens"] / found_session["contextTokens"] * 100, 2)
                if found_session.get("contextTokens")
                else None
            )
        } if found_session.get("inputTokens") is not None or found_session.get("outputTokens") is not None else None,
        "timestamps": {
            "updated_at": found_session.get("updatedAt"),
            "age": int((datetime.now().timestamp() * 1000) - found_session.get("updatedAt", 0))
                if found_session.get("updatedAt") else None
        } if found_session.get("updatedAt") else None,
        "flags": []
    }

    # Add system flag if applicable
    if found_session.get("systemSent"):
        response_data["flags"].append("system")

    # Include any other fields from the session object
    # Add fields like modelProvider, origin, deliveryContext, etc.
    if found_session.get("modelProvider"):
        response_data["model_provider"] = found_session.get("modelProvider")

    if found_session.get("origin"):
        response_data["origin"] = found_session.get("origin")

    # Note: We intentionally do NOT expose systemPromptReport or skillsSnapshot
    # as they contain internal prompts and may be large

    return response_data

# ============================================================================
# AI Chat Completion Endpoint
# ============================================================================

@app.post("/ai/completion", response_model=CompletionResponse)
async def completion(request: CompletionRequest):
    """
    AI Multi-turn Chat Completion - Stateful conversation support.

    This endpoint acts as a chatbot, accepting the full conversation history
    and returning the next AI response. It maintains conversation context
    across multiple turns.

    It does NOT generate code or execute anything - it only prepares
    structured prompts for project creation or modification.

    Request:
        projectType: Type of project (website, telegrambot, discordbot,
                    tradingbot, scheduler, custom)
        mode: Operation mode (create or modify)
        messages: Array of chat messages (full conversation history)
                Must contain at least one user message
                Only allows 'user' and 'assistant' roles (no 'system')

    Response:
        success: Whether the operation succeeded
        message: Chat message with role "assistant" and AI response
        error: Error message (if failed)

    This endpoint is stateless - no database storage of history.
    The client must maintain and send full conversation history.

    Security:
        - Rejects 'system' role from client
        - Sanitizes message roles
        - Limits message array length (max 50)
    """
    try:
        # Convert Pydantic messages to dict for the service
        messages_dict = [msg.dict() for msg in request.messages]

        result = await completion_service.complete(
            project_type=request.projectType,
            mode=request.mode,
            messages=messages_dict,
        )

        # If validation failed, return 400
        if not result["success"] and "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        return CompletionResponse(**result)

    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is

    except RuntimeError as e:
        # Service unavailable (e.g., Groq not configured)
        if "not available" in str(e).lower() or "not configured" in str(e).lower():
            return CompletionResponse(
                success=False,
                error="Completion service not available - GROQ_API_KEY not configured"
            )
        raise HTTPException(status_code=502, detail=str(e))

    except Exception as e:
        # Unexpected errors
        logger.error(f"Completion unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

if __name__ == "__main__":
    import uvicorn
    print(f"Starting Clawdbot Adapter API...")
    print(f"Images directory: {IMAGES_DIR}")
    print(f"Images accessible at: {IMAGES_BASE_URL}")
    uvicorn.run(app, host="0.0.0.0", port=8002)
