import os
import uuid
import json
import shutil
import re
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Any, Optional, Dict
from contextlib import contextmanager
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from fastapi import FastAPI, HTTPException, Request, Body, Header
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from httpx import AsyncClient

import image_handler
from database_adapter import get_db, init_schema, is_master_database, validate_project_database_deletion, delete_project_database, get_database_info
from project_manager import ProjectFileManager
from chat_handlers import generate_sse_stream, generate_sse_stream_with_db_save, handle_chat_with_image, handle_chat_text_only
from file_utils import FileUtils
from completion_service import CompletionService
from claude_code_worker import run_claude_code_background
from github_service import get_github_service
from services.session_lock_service import SessionLockService


# ============================================================================
# ACP Chat Handler
# ============================================================================

async def handle_acp_chat(request, session_id: int, user_content: str) -> str:
    """
    Handle chat in ACP mode - uses ACPX for frontend editing.
    
    Args:
        request: ChatRequest with acp_mode=True
        session_id: Session ID for context
        user_content: User's message content
        
    Returns:
        Assistant response content string
    """
    from acp_chat_handler import get_acp_chat_handler
    
    logger.info(f"[ACP-CHAT] Handling ACP chat for session {session_id}")
    
    # Get project info from session
    with get_db() as conn:
        session = conn.execute(
            """SELECT s.project_id, p.project_path, p.name 
               FROM sessions s 
               JOIN projects p ON s.project_id = p.id 
               WHERE s.id = ?""",
            (session_id,)
        ).fetchone()
        
        if not session:
            return "Error: Session not found or no project associated."
        
        project_path = session['project_path']
        project_name = session['name']
    
    if not project_path:
        return "Error: No project path found for this session."
    
    # Get ACP chat handler
    try:
        handler = get_acp_chat_handler(request.session_key, project_path)
        if not handler:
            return f"Error: ACP mode not available for project '{project_name}'. Make sure the frontend directory exists."
    except Exception as e:
        logger.error(f"[ACP-CHAT] Failed to create handler: {e}")
        return f"Error: Failed to initialize ACP mode: {str(e)}"
    
    # Build session context from recent messages (last 4 messages = 2 exchanges)
    context_lines = []
    with get_db() as conn:
        recent_messages = conn.execute(
            """SELECT role, content FROM messages 
               WHERE session_id = ? 
               ORDER BY created_at DESC 
               LIMIT 4""",
            (session_id,)
        ).fetchall()
        
        for msg in reversed(recent_messages):  # Oldest first
            role = "User" if msg['role'] == 'user' else "Assistant"
            context_lines.append(f"{role}: {msg['content'][:500]}")
    
    session_context = "\n\n".join(context_lines) if context_lines else ""
    
    # Log prompt framing before sending to Claude
    logger.info(f"[ACP-CHAT] === PROMPT FRAMING ===")
    logger.info(f"[ACP-CHAT] User message: {user_content[:200]}...")
    logger.info(f"[ACP-CHAT] Session context ({len(context_lines)} messages): {session_context[:500]}...")
    logger.info(f"[ACP-CHAT] ========================")
    
    # Run chat (use unified method that prefers Claude Agent)
    try:
        # Try async version first
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(handler.run_chat_unified(user_content, session_context))
        loop.close()
    except RuntimeError:
        # Fallback to sync ACPX if async fails
        logger.warning("[ACP-CHAT] Async not available, using ACPX fallback")
        result = handler.run_acpx_chat(user_content, session_context)
    
    if result.get('success'):
        backend = result.get('backend', 'unknown')
        logger.info(f"[ACP-CHAT] Chat completed successfully using {backend}")
        return result.get('response', 'Operation completed.')
    else:
        error_msg = result.get('error', 'Unknown error')
        response = result.get('response', '')
        if response:
            return f"{response}\n\n(Note: {error_msg})"
        return f"Error: {error_msg}"
from template_selector import TemplateSelector

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

DB_PATH = os.getenv("DB_PATH", "/root/clawd-backend/clawdbot_adapter.db")

DEFAULT_AGENT_ID = "main"
DEFAULT_CHANNEL = "webchat"

IMAGE_MODEL = "zai/glm-4.6v"
TEXT_MODEL = "agent:main"

CLAWDBOT_SESSIONS_PATH = os.path.expanduser("~/.clawdbot/agents/main/sessions/sessions.json")

IMAGES_DIR = "/root/clawd/public/images"
os.makedirs(IMAGES_DIR, exist_ok=True)

IMAGES_BASE_URL = "http://195.200.14.37:8002/images"

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
    created_at: str  # Changed from datetime to str for PostgreSQL compatibility

class ProjectResponse(BaseModel):
    id: int
    user_id: int
    name: str
    domain: str
    description: Optional[str] = None
    project_path: Optional[str] = None
    type_id: Optional[int] = None
    status: Optional[str] = None
    claude_code_session_name: Optional[str] = None
    template_id: Optional[str] = None  # Selected frontend template ID
    frontend: Optional[dict] = None  # Frontend template details
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
    domain: Optional[str] = Field(None, min_length=3, max_length=50)
    description: Optional[str] = None
    user_id: Optional[int] = None
    type_id: Optional[int] = Field(None, alias="typeId")
    template_id: Optional[str] = None  # Optional pre-selected template ID (bypasses Task 1)

class CreateSessionRequest(BaseModel):
    label: str
    project_id: int = 1

class ChatRequest(BaseModel):
    session_key: str
    messages: list[Message]
    stream: bool = False
    image: Optional[str] = None
    acp_mode: bool = True  # Default to ACP mode for frontend editing via ACPX

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
# ACP Frontend Edit Models
# ============================================================================

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

    # Populate frontend info for projects with template_id
    response_projects = []
    selector = TemplateSelector()

    for project in projects:
        # Handle both dict (PostgreSQL) and tuple (SQLite) row types
        if isinstance(project, dict):
            project_dict = project
        else:
            project_dict = dict(project)

        # Ensure created_at is a string (handle both string and integer timestamps)
        if "created_at" in project_dict and not isinstance(project_dict["created_at"], str):
            project_dict["created_at"] = str(project_dict["created_at"])

        # Ensure updated_at is a string (handle both string and integer timestamps)
        if "updated_at" in project_dict and not isinstance(project_dict["updated_at"], str):
            project_dict["updated_at"] = str(project_dict["updated_at"])

        # Add frontend info if template_id is set
        if "template_id" in project_dict and project_dict["template_id"]:
            try:
                template = selector._find_template_by_id(project_dict["template_id"])
                if template:
                    project_dict["frontend"] = {
                        "template": template.get("id"),
                        "repo": template.get("repo"),
                        "category": template.get("category"),
                        "modified": False
                    }
            except Exception as e:
                logger.error(f"Failed to fetch template details for project {project_dict.get('id')}: {e}")

        response_projects.append(ProjectResponse(**project_dict))

    return response_projects

@app.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(request: CreateProjectRequest):
    # Get GitHub service for repo name sanitization
    github = get_github_service()
    
    # Auto-generate domain if not provided (use GitHub-compatible naming)
    domain = request.domain
    if not domain or not domain.strip():
        # Sanitize project name for GitHub repo format
        domain = github.sanitize_repo_name(request.name)
        
        # Add random suffix to ensure uniqueness
        random_suffix = ''.join(__import__('random').choices('abcdefghijklmnopqrstuvwxyz0123456789', k=6))
        domain = f"{domain}-{random_suffix}"
        logger.info(f"Auto-generated domain for project '{request.name}': {domain}")
    else:
        # Sanitize user-provided domain for GitHub compatibility
        domain = github.sanitize_repo_name(domain.strip())
        # Validate subdomain format if provided
        if not validate_subdomain(domain):
            raise HTTPException(
                status_code=400,
                detail="Invalid subdomain format. Must be 3-50 characters, lowercase letters, numbers, hyphens only, must start with a letter."
            )

    # Default to user_id=1 if not provided
    user_id = request.user_id if request.user_id is not None else 1

    # Check for duplicate domain (only if user provided one, auto-generated ones use random suffix)
    if request.domain and request.domain.strip():
        with get_db() as conn:
            existing_domain = conn.execute(
                "SELECT id FROM projects WHERE domain = ?",
                (domain,)
            ).fetchone()
            if existing_domain:
                raise HTTPException(
                    status_code=409,
                    detail=f"Domain '{domain}' is already in use. Please choose a different subdomain."
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
    logger.info("[PROJECT] inserting project into database")
    with get_db() as conn:
        try:
            conn.execute(
                "INSERT INTO projects (user_id, name, domain, description, project_path, type_id, status, claude_code_session_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                (user_id, request.name, domain, request.description, '', type_id, 'creating', None)
            )
            result = conn.fetchone()
            # Handle both dict (PostgreSQL) and tuple (SQLite) row types
            if isinstance(result, dict):
                project_id = result.get('id')
            else:
                project_id = result[0] if result else None
            
            if not project_id:
                raise RuntimeError("Failed to get project_id from INSERT RETURNING")
                
            logger.info(f"[PROJECT] database insert successful, project_id: {project_id}")
            conn.commit()
            logger.info("[PROJECT] database commit successful")
        except Exception as e:
            logger.error(f"[PROJECT] database insert failed: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create project record: {str(e)}"
            )

    # Step 2: Create project folder with Git initialization
    project_manager = ProjectFileManager()
    project_folder_path, folder_success = project_manager.create_project_with_git(project_id, request.name, type_id)

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

    # Step 3.5: Create GitHub repository (push happens at end of project creation)
    repo_url = None
    try:
        logger.info(f"[GITHUB] Creating repository for project: {domain}")
        repo_url = github.create_repository(
            name=domain,
            public=True,  # Public by default
            description=f"Project: {request.name}"
        )
        
        if repo_url:
            logger.info(f"[GITHUB] Repository created: {repo_url}")
            
            # Add remote to local repo (push will happen after all project steps complete)
            if github.add_remote(project_folder_path, repo_url):
                logger.info(f"[GITHUB] Remote added to local repo")
                
                # Store repo_url in database
                with get_db() as conn:
                    conn.execute(
                        "UPDATE projects SET repo_url = ? WHERE id = ?",
                        (repo_url, project_id)
                    )
                    conn.commit()
            else:
                logger.warning(f"[GITHUB] Failed to add remote, continuing anyway")
        else:
            logger.warning(f"[GITHUB] Failed to create repository, continuing without GitHub")
    except Exception as e:
        logger.warning(f"[GITHUB] GitHub integration failed: {e}, continuing without GitHub")

    # Step 4: Select template (if not provided)
    selected_template_id = request.template_id

    # Check if EMPTY_TEMPLATE_MODE is enabled
    empty_template_mode = os.getenv("EMPTY_TEMPLATE_MODE", "false").lower() == "true"

    if empty_template_mode:
        logger.info("EMPTY_TEMPLATE_MODE is enabled - using blank template")
        selected_template_id = "blank"
    elif type_id == 1 and not selected_template_id:
        # Auto-select template for website projects using Groq
        try:
            selector = TemplateSelector()
            if selector.is_available():
                logger.info(f"Auto-selecting template for project {project_id}")
                result = await selector.select_template(
                    project_name=request.name,
                    project_description=request.description or "",
                    project_type="website"
                )
                if result.get("template"):
                    selected_template_id = result["template"]["id"]
                    logger.info(f"Auto-selected template: {selected_template_id}")
                else:
                    logger.warning(f"Template selection returned no result, will use fallback in worker")
            else:
                logger.warning("Template selector not available, worker will use fallback")
        except Exception as e:
            logger.error(f"Template selection failed: {e}, worker will use fallback")

    # Step 5: Trigger background Claude Code worker for website projects only
    # Project type 'website' has type_id = 1
    if type_id == 1:
        # Generate unique session name for Claude Code
        session_name = f"project-{project_id}-{request.name.replace(' ', '-')}"

        # Save session name to database
        with get_db() as conn:
            conn.execute(
                "UPDATE projects SET claude_code_session_name = ? WHERE id = ?",
                (session_name, project_id)
            )
            conn.commit()

        logger.info(f"Triggering background Claude Code worker for website project {project_id}")
        logger.info(f"Claude Code session name: {session_name}")
        if selected_template_id:
            logger.info(f"Using pre-selected template: {selected_template_id}")

            # Save template_id to database
            with get_db() as conn:
                conn.execute(
                    "UPDATE projects SET template_id = ? WHERE id = ?",
                    (selected_template_id, project_id)
                )
                conn.commit()

        try:
            logger.info(f"[PROJECT] launching fast_wrapper for project {project_id}")
            run_claude_code_background(
                project_id=project_id,
                project_path=project_folder_path,
                project_name=request.name,
                description=request.description,
                session_name=session_name,
                template_id=selected_template_id  # Pass selected template ID
            )
            logger.info(f"[PROJECT] fast_wrapper launched successfully for project {project_id}")
        except Exception as e:
            # Log error but don't fail the project creation
            # Project will remain in 'creating' status
            logger.error(f"[PROJECT] failed to launch fast_wrapper: {e}")
            # Update project status to failed
            with get_db() as conn:
                conn.execute(
                    "UPDATE projects SET status = ? WHERE id = ?",
                    ("failed", project_id)
                )
                conn.commit()

    # Note: GitHub push happens at end of infrastructure_manager.provision_all()
    # This ensures all template files, builds, and infrastructure are included

    # Fetch the final project data from database (includes status and session_key)
    with get_db() as conn:
        final_project = conn.execute(
            "SELECT * FROM projects WHERE id = ?",
            (project_id,)
        ).fetchone()

    # Get template details if template_id is set
    frontend_info = None
    if "template_id" in final_project and final_project["template_id"]:
        try:
            selector = TemplateSelector()
            template = selector._find_template_by_id(final_project["template_id"])
            if template:
                frontend_info = {
                    "template": template.get("id"),
                    "repo": template.get("repo"),
                    "category": template.get("category"),
                    "modified": False
                }
        except Exception as e:
            logger.error(f"Failed to fetch template details: {e}")

    return ProjectResponse(
        id=final_project["id"],
        user_id=final_project["user_id"],
        name=final_project["name"],
        domain=final_project["domain"],
        description=final_project["description"],
        project_path=final_project["project_path"],
        type_id=final_project["type_id"],
        status=final_project["status"],
        claude_code_session_name=final_project["claude_code_session_name"],
        template_id=final_project["template_id"] if "template_id" in final_project else None,
        frontend=frontend_info,
        created_at=str(final_project["created_at"]) if isinstance(final_project.get("created_at"), (datetime,)) else final_project.get("created_at")
    )

@app.get("/project-types", response_model=list[ProjectTypeResponse])
async def get_project_types():
    """Get all available project types."""
    with get_db() as conn:
        types = conn.execute("SELECT id, type, display_name FROM project_types ORDER BY id").fetchall()

    return [ProjectTypeResponse(**dict(t)) for t in types]


class TemplateSelectionRequest(BaseModel):
    project_name: str
    description: str
    project_type: str = "website"


@app.post("/templates/select")
async def select_template(request: TemplateSelectionRequest):
    """
    Select the best frontend template based on project description using Groq LLM.

    This is much faster than using Claude Code for template selection.
    The selected template ID can be passed to project creation to skip the slow Task 1.
    """
    selector = TemplateSelector()

    if not selector.is_available():
        raise HTTPException(
            status_code=503,
            detail="Template selector not available - Groq not configured or registry missing"
        )

    try:
        result = await selector.select_template(
            project_name=request.project_name,
            project_description=request.description,
            project_type=request.project_type
        )

        if result.get("success"):
            return {
                "success": True,
                "template": result["template"]
            }
        else:
            # Return fallback template even on failure
            return {
                "success": False,
                "error": result.get("error"),
                "template": result.get("template")  # fallback template
            }

    except Exception as e:
        logger.error(f"Template selection failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Template selection failed: {str(e)}"
        )


@app.get("/templates")
async def list_templates():
    """List all available templates from the registry."""
    selector = TemplateSelector()

    if not selector.is_available():
        raise HTTPException(
            status_code=503,
            detail="Template selector not available"
        )

    return selector.list_templates()

def cleanup_pm2_services(project_name: str) -> Dict[str, Any]:
    """
    Stop and remove PM2 services for a project.

    Args:
        project_name: Project name (used to build service names)

    Returns:
        Dict with cleanup status
    """
    logger.info(f"Cleaning up PM2 services for project: {project_name}")

    frontend_service = f"{project_name}-frontend"
    backend_service = f"{project_name}-backend"

    results = {
        "frontend": {"stopped": False, "deleted": False, "error": None},
        "backend": {"stopped": False, "deleted": False, "error": None}
    }

    # Stop and delete frontend service
    try:
        subprocess.run(["pm2", "stop", frontend_service], capture_output=True, timeout=10)
        results["frontend"]["stopped"] = True
        logger.info(f"Stopped PM2 service: {frontend_service}")
    except subprocess.TimeoutExpired:
        results["frontend"]["error"] = "Timeout stopping service"
        logger.warning(f"Timeout stopping {frontend_service}")
    except Exception as e:
        logger.warning(f"Failed to stop {frontend_service}: {e}")

    try:
        subprocess.run(["pm2", "delete", frontend_service], capture_output=True, timeout=10)
        results["frontend"]["deleted"] = True
        logger.info(f"Deleted PM2 service: {frontend_service}")
    except subprocess.TimeoutExpired:
        if results["frontend"]["stopped"]:
            results["frontend"]["error"] = "Timeout deleting service"
        logger.warning(f"Timeout deleting {frontend_service}")
    except Exception as e:
        logger.warning(f"Failed to delete {frontend_service}: {e}")

    # Stop and delete backend service
    try:
        subprocess.run(["pm2", "stop", backend_service], capture_output=True, timeout=10)
        results["backend"]["stopped"] = True
        logger.info(f"Stopped PM2 service: {backend_service}")
    except subprocess.TimeoutExpired:
        results["backend"]["error"] = "Timeout stopping service"
        logger.warning(f"Timeout stopping {backend_service}")
    except Exception as e:
        logger.warning(f"Failed to stop {backend_service}: {e}")

    try:
        subprocess.run(["pm2", "delete", backend_service], capture_output=True, timeout=10)
        results["backend"]["deleted"] = True
        logger.info(f"Deleted PM2 service: {backend_service}")
    except subprocess.TimeoutExpired:
        if results["backend"]["stopped"]:
            results["backend"]["error"] = "Timeout deleting service"
        logger.warning(f"Timeout deleting {backend_service}")
    except Exception as e:
        logger.warning(f"Failed to delete {backend_service}: {e}")

    # Save PM2 process list
    try:
        subprocess.run(["pm2", "save"], capture_output=True, timeout=10)
        logger.info("Saved PM2 process list")
    except Exception as e:
        logger.warning(f"Failed to save PM2 list: {e}")

    return results


def cleanup_nginx_config(project_name: str) -> Dict[str, Any]:
    """
    Remove Nginx configuration for a project.

    Args:
        project_name: Project name (used for config filename)

    Returns:
        Dict with cleanup status
    """
    logger.info(f"Cleaning up Nginx config for project: {project_name}")

    config_path = f"/etc/nginx/sites-available/{project_name}.conf"
    symlink_path = f"/etc/nginx/sites-enabled/{project_name}.conf"

    results = {
        "config_removed": False,
        "symlink_removed": False,
        "nginx_reloaded": False,
        "errors": []
    }

    # Remove symlink FIRST (must be removed before config file to avoid nginx test failure)
    if os.path.exists(symlink_path) or os.path.islink(symlink_path):
        try:
            subprocess.run(["rm", "-f", symlink_path], capture_output=True, check=True)
            results["symlink_removed"] = True
            logger.info(f"Removed Nginx symlink: {symlink_path}")
        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to remove symlink: {e}"
            results["errors"].append(error_msg)
            logger.error(error_msg)
    else:
        logger.info(f"Nginx symlink not found (already removed): {symlink_path}")

    # Remove config file
    if os.path.exists(config_path):
        try:
            subprocess.run(["rm", "-f", config_path], capture_output=True, check=True)
            results["config_removed"] = True
            logger.info(f"Removed Nginx config: {config_path}")
        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to remove config: {e}"
            results["errors"].append(error_msg)
            logger.error(error_msg)
    else:
        logger.info(f"Nginx config not found (already removed): {config_path}")

    # Test and reload nginx
    try:
        subprocess.run(["/usr/sbin/nginx", "-t"], capture_output=True, check=True, timeout=10)
        subprocess.run(["/usr/bin/systemctl", "reload", "nginx"], capture_output=True, check=True, timeout=10)
        results["nginx_reloaded"] = True
        logger.info("Nginx configuration tested and reloaded successfully")
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to reload nginx: {e}"
        results["errors"].append(error_msg)
        logger.error(error_msg)
    except subprocess.TimeoutExpired:
        error_msg = "Timeout reloading nginx"
        results["errors"].append(error_msg)
        logger.error(error_msg)

    return results


def cleanup_ssl_certificates(frontend_domain: str, backend_domain: str) -> Dict[str, Any]:
    """
    Remove SSL certificates for a project.

    Args:
        frontend_domain: Frontend domain (e.g., "project.dreambigwithai.com")
        backend_domain: Backend domain (e.g., "project-api.dreambigwithai.com")

    Returns:
        Dict with cleanup status
    """
    logger.info(f"Cleaning up SSL certificates for {frontend_domain} and {backend_domain}")

    frontend_cert_path = f"/etc/letsencrypt/live/{frontend_domain}"
    backend_cert_path = f"/etc/letsencrypt/live/{backend_domain}"

    results = {
        "frontend_removed": False,
        "backend_removed": False,
        "errors": []
    }

    # Remove frontend certificate
    if os.path.exists(frontend_cert_path):
        try:
            subprocess.run(["rm", "-rf", frontend_cert_path], capture_output=True, check=True)
            results["frontend_removed"] = True
            logger.info(f"Removed SSL certificate: {frontend_cert_path}")
        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to remove frontend cert: {e}"
            results["errors"].append(error_msg)
            logger.error(error_msg)
    else:
        logger.info(f"Frontend SSL cert not found: {frontend_cert_path}")

    # Remove backend certificate
    if os.path.exists(backend_cert_path):
        try:
            subprocess.run(["rm", "-rf", backend_cert_path], capture_output=True, check=True)
            results["backend_removed"] = True
            logger.info(f"Removed SSL certificate: {backend_cert_path}")
        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to remove backend cert: {e}"
            results["errors"].append(error_msg)
            logger.error(error_msg)
    else:
        logger.info(f"Backend SSL cert not found: {backend_cert_path}")

    return results


def cleanup_dns_records(frontend_domain: str, backend_domain: str) -> Dict[str, Any]:
    """
    Remove DNS A records using local DNS manager.

    Args:
        frontend_domain: Frontend domain name (e.g., "project")
        backend_domain: Backend domain name (e.g., "project-api")

    Returns:
        Dict with cleanup status
    """
    logger.info(f"Cleaning up DNS records for {frontend_domain} and {backend_domain}")

    results = {
        "frontend_deleted": False,
        "backend_deleted": False,
        "skipped": False,
        "errors": []
    }

    # Import local DNS manager
    try:
        import infrastructure_manager_dns as dns_mgr
    except ImportError as e:
        logger.warning(f"⚠️ DNS manager not available: {e}")
        logger.warning(f"  Skipping DNS cleanup. Remove these A records manually in Hostinger hPanel:")
        logger.warning(f"    - {frontend_domain}.{dns_mgr.BASE_DOMAIN}")
        logger.warning(f"    - {backend_domain}.{dns_mgr.BASE_DOMAIN}")
        results["skipped"] = True
        return results

    # Remove frontend DNS record
    try:
        if dns_mgr.delete_a_record(frontend_domain):
            results["frontend_deleted"] = True
            logger.info(f"Removed DNS record: {frontend_domain}.{dns_mgr.BASE_DOMAIN}")
        else:
            results["errors"].append(f"Failed to remove frontend DNS record")
    except Exception as e:
        error_msg = f"Error removing frontend DNS: {e}"
        results["errors"].append(error_msg)
        logger.warning(error_msg)

    # Remove backend DNS record
    try:
        if dns_mgr.delete_a_record(backend_domain):
            results["backend_deleted"] = True
            logger.info(f"Removed DNS record: {backend_domain}.{dns_mgr.BASE_DOMAIN}")
        else:
            results["errors"].append(f"Failed to remove backend DNS record")
    except Exception as e:
        error_msg = f"Error removing backend DNS: {e}"
        results["errors"].append(error_msg)
        logger.warning(error_msg)

    return results


def cleanup_postgresql_database(db_name: str, db_user: str) -> Dict[str, Any]:
    """
    Drop PostgreSQL database and user for a project.

    Args:
        db_name: Database name (e.g., "project_db")
        db_user: Database user (e.g., "project_user")

    Returns:
        Dict with cleanup status
    """
    logger.info(f"Cleaning up PostgreSQL database: {db_name}, user: {db_user}")

    results = {
        "database_dropped": False,
        "user_dropped": False,
        "errors": []
    }

    # Drop database
    try:
        subprocess.run(
            ["docker", "exec", "-i", "dreampilot-postgres", "psql", "-U", "admin", "-d", "defaultdb"],
            input=f"DROP DATABASE IF EXISTS {db_name};\n",
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        results["database_dropped"] = True
        logger.info(f"Dropped database: {db_name}")
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to drop database: {e.stderr if e.stderr else str(e)}"
        results["errors"].append(error_msg)
        logger.warning(error_msg)
    except subprocess.TimeoutExpired:
        error_msg = "Timeout dropping database"
        results["errors"].append(error_msg)
        logger.warning(error_msg)

    # Drop user
    try:
        subprocess.run(
            ["docker", "exec", "-i", "dreampilot-postgres", "psql", "-U", "admin", "-d", "defaultdb"],
            input=f"DROP USER IF EXISTS {db_user};\n",
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        results["user_dropped"] = True
        logger.info(f"Dropped database user: {db_user}")
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to drop user: {e.stderr if e.stderr else str(e)}"
        results["errors"].append(error_msg)
        logger.warning(error_msg)
    except subprocess.TimeoutExpired:
        error_msg = "Timeout dropping user"
        results["errors"].append(error_msg)
        logger.warning(error_msg)

    return results


def cleanup_project_directory(project_path: str) -> Dict[str, Any]:
    """
    Remove project directory safely with validation.

    Args:
        project_path: Full path to project directory

    Returns:
        Dict with cleanup status
    """
    logger.info(f"Cleaning up project directory: {project_path}")

    results = {
        "removed": False,
        "error": None
    }

    # Validate path is within DreamPilot root
    dreampilot_root = "/root/dreampilot/projects/website"
    normalized_path = os.path.abspath(project_path)
    normalized_root = os.path.abspath(dreampilot_root)

    if not normalized_path.startswith(normalized_root):
        error_msg = f"Path traversal attempt detected: {project_path}"
        results["error"] = error_msg
        logger.error(error_msg)
        return results

    # Remove directory with better error handling
    if os.path.exists(project_path):
        try:
            # First pass: try normal removal
            shutil.rmtree(project_path)
            results["removed"] = True
            logger.info(f"Removed project directory: {project_path}")
        except OSError as e:
            # Second pass: if directory not empty, try removing subdirectories individually
            logger.warning(f"First pass failed ({e}), trying subdirectory removal...")
            try:
                for item in os.listdir(project_path):
                    item_path = os.path.join(project_path, item)
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                        logger.info(f"Removed subdirectory: {item_path}")
                    else:
                        os.remove(item_path)
                        logger.info(f"Removed file: {item_path}")
                # Finally remove the parent directory
                os.rmdir(project_path)
                results["removed"] = True
                logger.info(f"Removed project directory (second pass): {project_path}")
            except Exception as e2:
                error_msg = f"Failed to remove directory (both attempts): {e}, {e2}"
                results["error"] = error_msg
                logger.error(error_msg)
        except Exception as e:
            error_msg = f"Failed to remove directory: {e}"
            results["error"] = error_msg
            logger.error(error_msg)
    else:
        logger.info(f"Project directory not found (already removed): {project_path}")

    return results


# ============================================================================
# DYNAMIC BACKEND PORT ALLOCATION
# ============================================================================

def check_port_availability(port: int) -> bool:
    """
    Check if a port is available for binding.

    Args:
        port: Port number to check

    Returns:
        True if port is available, False if in use
    """
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('0.0.0.0', port))
            return True
    except OSError as e:
        if e.errno == 98:  # Address already in use
            return False
        raise


def get_next_backend_port() -> int:
    """
    Get next available backend port from database.

    Scans ports 8010-9000 to find an unused port.

    Returns:
        Available port number

    Raises:
        Exception if no available ports in range
    """
    # Get used ports from database
    with get_db() as conn:
        used_ports_result = conn.execute(
            "SELECT backend_port FROM projects WHERE backend_port IS NOT NULL"
        ).fetchall()
        used_ports = set(row[0] for row in used_ports_result)

    logger.info(f"[Port Allocation] Currently used ports: {sorted(used_ports)}")

    # Find next available port in range 8010-9000
    for port in range(8010, 9000):
        # Skip if port is in use by other projects
        if port in used_ports:
            continue

        # Check if port is actually available at system level
        if not check_port_availability(port):
            logger.warning(f"[Port Allocation] Port {port} in use by system, skipping")
            continue

        logger.info(f"[Port Allocation] Found available port: {port}")
        return port

    raise Exception("No available ports in range 8010-9000")


def allocate_backend_port(project_id: int) -> int:
    """
    Allocate a backend port for a project and save to database.

    Args:
        project_id: Project ID

    Returns:
        Allocated port number

    Raises:
        Exception if port allocation fails
    """
    port = get_next_backend_port()

    with get_db() as conn:
        conn.execute(
            "UPDATE projects SET backend_port = ? WHERE id = ?",
            (port, project_id)
        )
        conn.commit()

    logger.info(f"[Port Allocation] Allocated port {port} for project {project_id}")
    return port



def cleanup_infrastructure(project_path: str) -> Dict[str, Any]:
    """
    Full infrastructure cleanup for a project.

    Args:
        project_path: Full path to project directory

    Returns:
        Dict with complete cleanup status
    """
    logger.info(f"Starting infrastructure cleanup for: {project_path}")

    # Load project metadata
    project_json_path = os.path.join(project_path, "project.json")
    project_metadata = {}

    if os.path.exists(project_json_path):
        try:
            with open(project_json_path, 'r') as f:
                project_metadata = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load project.json: {e}")
    else:
        logger.warning(f"project.json not found at: {project_json_path}")

    # Extract project details from metadata or path
    project_name = project_metadata.get("project_name")
    if not project_name:
        # Extract from path (e.g., "124_test-api-project_20260220_153219" -> "test-api-project")
        import re
        path_basename = os.path.basename(project_path)
        # Remove ID prefix and timestamp suffix (pattern: _YYYYMMDD_HHMMSS at the end)
        # Matches: 123_project-name_20260220_153219 -> extracts "project-name"
        match = re.match(r'^\d+_(.+?)_\d{8}_\d{6}$', path_basename)
        if match:
            project_name = match.group(1)
        else:
            # Fallback: just remove ID prefix
            parts = path_basename.split('_', 1)
            project_name = parts[1] if len(parts) > 1 else path_basename
        logger.warning(f"Extracted project name from path: {project_name}")

    frontend_domain = project_metadata.get("domains", {}).get("frontend", "").replace(".dreambigwithai.com", "")
    backend_domain = project_metadata.get("domains", {}).get("backend", "").replace(".dreambigwithai.com", "")
    db_name = project_metadata.get("database", {}).get("name", "")
    db_user = project_metadata.get("database", {}).get("user", "")

    # Fallback: extract from full domains
    if not frontend_domain:
        full_frontend = project_metadata.get("frontend_domain", "")
        if full_frontend:
            frontend_domain = full_frontend.replace(".dreambigwithai.com", "")

    if not backend_domain:
        full_backend = project_metadata.get("backend_domain", "")
        if full_backend:
            backend_domain = full_backend.replace(".dreambigwithai.com", "")

    # Fallback: extract from project.json database field
    if not db_name:
        db_name = project_metadata.get("database", "")
        if db_name:
            db_user = db_name.replace("_db", "_user")

    # Final fallback: construct from project_name if metadata is incomplete
    if not frontend_domain and project_name:
        frontend_domain = project_name
        logger.info(f"Using constructed frontend domain: {frontend_domain}")

    if not backend_domain and project_name:
        backend_domain = f"{project_name}-api"
        logger.info(f"Using constructed backend domain: {backend_domain}")

    if not db_name and project_name:
        # Convert project name to database format (e.g., "test-api-project" -> "test_api_project_db")
        db_name = project_name.replace("-", "_") + "_db"
        db_user = project_name.replace("-", "_") + "_user"
        logger.info(f"Using constructed database: {db_name}, user: {db_user}")

    cleanup_results = {
        "project_name": project_name,
        "project_path": project_path,
        "steps": {}
    }

    # STEP 1: Stop and remove PM2 services
    # Use domain for PM2 service names (matches provisioning logic)
    pm2_service_name = frontend_domain or project_name
    try:
        cleanup_results["steps"]["pm2"] = cleanup_pm2_services(pm2_service_name)
    except Exception as e:
        logger.error(f"Error in PM2 cleanup: {e}")
        cleanup_results["steps"]["pm2"] = {"error": str(e)}

    # STEP 2: Remove Nginx configuration
    # Use domain for nginx config name (matches provisioning logic)
    nginx_service_name = frontend_domain or project_name
    try:
        cleanup_results["steps"]["nginx"] = cleanup_nginx_config(nginx_service_name)
    except Exception as e:
        logger.error(f"Error in Nginx cleanup: {e}")
        cleanup_results["steps"]["nginx"] = {"error": str(e)}

    # STEP 3: Remove SSL certificates
    try:
        full_frontend = f"{frontend_domain}.dreambigwithai.com" if frontend_domain else ""
        full_backend = f"{backend_domain}.dreambigwithai.com" if backend_domain else ""
        if full_frontend or full_backend:
            cleanup_results["steps"]["ssl"] = cleanup_ssl_certificates(full_frontend, full_backend)
        else:
            logger.info("Skipping SSL cleanup: no domains found in metadata")
            cleanup_results["steps"]["ssl"] = {"skipped": True}
    except Exception as e:
        logger.error(f"Error in SSL cleanup: {e}")
        cleanup_results["steps"]["ssl"] = {"error": str(e)}

    # STEP 4: Remove DNS records
    try:
        if frontend_domain or backend_domain:
            cleanup_results["steps"]["dns"] = cleanup_dns_records(frontend_domain, backend_domain)
        else:
            logger.info("Skipping DNS cleanup: no domains found in metadata")
            cleanup_results["steps"]["dns"] = {"skipped": True}
    except Exception as e:
        logger.error(f"Error in DNS cleanup: {e}")
        cleanup_results["steps"]["dns"] = {"error": str(e)}

    # STEP 5: Drop PostgreSQL database
    # Use domain for database name (matches provisioning logic in infrastructure_manager.py)
    db_service_name = frontend_domain or project_name
    try:
        if db_name and db_user:
            # Use validated database deletion with master DB protection
            cleanup_results["steps"]["database"] = delete_project_database(db_service_name, force=False)
        else:
            logger.info("Skipping database cleanup: no database info found in metadata")
            cleanup_results["steps"]["database"] = {"skipped": True}
    except Exception as e:
        logger.error(f"Error in database cleanup: {e}")
        cleanup_results["steps"]["database"] = {"error": str(e)}

    # STEP 6: Remove project directory
    try:
        cleanup_results["steps"]["directory"] = cleanup_project_directory(project_path)
    except Exception as e:
        logger.error(f"Error in directory cleanup: {e}")
        cleanup_results["steps"]["directory"] = {"error": str(e)}

    # Log final status
    logger.info(f"Infrastructure cleanup completed for {project_name}")

    return cleanup_results


@app.delete("/projects/{project_id}")
async def delete_project(project_id: int, force: bool = False):
    """
    Delete a project with infrastructure cleanup and master DB protection.
    
    Args:
        project_id: ID of the project to delete
        force: Force deletion even if validation fails (DANGEROUS)
    
    Returns:
        Deletion status with cleanup results
    """
    # Security: Log force deletion attempts
    if force:
        logger.warning(f"⚠️ FORCE deletion requested for project {project_id}")
    
    # Step 1: Get project info before deletion
    with get_db() as conn:
        project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()

        if not project:
            raise HTTPException(status_code=404, detail=f"Project with id {project_id} not found")

        project_path = project['project_path']
        project_name = project['name']

        # Master DB Protection: Validate no master database is being deleted
        db_info = get_database_info()
        if db_info["backend"] == "postgresql":
            # Check if project database matches project pattern (not master DB)
            # Project DBs are named: {project_name}_db
            # Master DB is protected and should never be deleted
            if is_master_database(f"{project_name}_db"):
                error_msg = "CRITICAL: Attempt to delete master database blocked!"
                logger.error(f"❌ {error_msg}")
                raise HTTPException(status_code=403, detail=error_msg)
        else:
            logger.info("✓ Master database validation passed (SQLite mode)")

        # Validate project database deletion if in PostgreSQL mode
        if db_info["backend"] == "postgresql":
            db_name = f"{project_name.replace('-', '_')}_db"
            is_allowed, reason = validate_project_database_deletion(project_name, db_name)
            
            if not is_allowed and not force:
                error_msg = f"Project database deletion rejected: {reason}"
                logger.error(f"❌ {error_msg}")
                raise HTTPException(status_code=400, detail={
                    "success": False,
                    "error": reason,
                    "database": db_name,
                    "force_required": True
                })
            elif force:
                logger.warning(f"⚠️ FORCE deletion: {reason}")

        # Get all session_keys linked to this project before deletion
        sessions_to_delete = conn.execute(
            "SELECT session_key FROM sessions WHERE project_id = ?",
            (project_id,)
        ).fetchall()
        session_keys = [row['session_key'] for row in sessions_to_delete]
        
        # Get repo_url for GitHub deletion
        repo_url = project.get('repo_url')

    # Step 2: Delete GitHub repository (before database deletion)
    if repo_url:
        try:
            github = get_github_service()
            # Extract repo name from URL (owner/repo format)
            if "github.com/" in repo_url:
                repo_name = repo_url.split("github.com/")[-1].strip("/")
                logger.info(f"[GITHUB] Attempting to delete repository: {repo_name}")
                logger.info(f"[GITHUB] Full repo_url from DB: {repo_url}")
                
                if github.delete_repository(repo_name):
                    logger.info(f"[GITHUB] ✓ Repository deleted: {repo_name}")
                else:
                    logger.warning(f"[GITHUB] ✗ Failed to delete repository: {repo_name}")
            else:
                logger.warning(f"[GITHUB] Invalid repo_url format: {repo_url}")
        except Exception as e:
            logger.error(f"[GITHUB] Error deleting repository: {e}")
            import traceback
            logger.error(f"[GITHUB] Traceback: {traceback.format_exc()}")
    else:
        logger.info(f"[GITHUB] No repo_url found for project {project_id}, skipping GitHub deletion")

    # Step 3: DELETE FROM DATABASE FIRST (so UI shows correct count immediately)
    with get_db() as conn:
        # Delete messages first (foreign key dependency)
        conn.execute("DELETE FROM messages WHERE session_id IN (SELECT id FROM sessions WHERE project_id = ?)", (project_id,))
        conn.execute("DELETE FROM sessions WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()
    
    logger.info(f"✓ Deleted project {project_id} from database (infrastructure cleanup in background)")
    
    # Step 3: Start infrastructure cleanup in BACKGROUND (async)
    import asyncio
    from fastapi.concurrency import run_in_threadpool
    
    async def cleanup_task():
        """Background task for infrastructure cleanup."""
        try:
            logger.info(f"[BG] Starting infrastructure cleanup for project {project_id}: {project_path}")
            
            # Run cleanup in threadpool to avoid blocking
            cleanup_result = await run_in_threadpool(cleanup_infrastructure, project_path)
            
            # Delete OpenClaw sessions
            sessions_json_path = os.path.expanduser("~/.openclaw/agents/main/sessions/sessions.json")
            if os.path.exists(sessions_json_path):
                try:
                    with open(sessions_json_path, 'r') as f:
                        sessions_data = json.load(f)
                    
                    openclaw_keys_to_delete = []
                    for key in sessions_data.keys():
                        for session_key in session_keys:
                            if key.endswith(f"adapter-session-{session_key}"):
                                openclaw_keys_to_delete.append(key)
                                break
                    
                    deleted_count = 0
                    for key in openclaw_keys_to_delete:
                        if key in sessions_data:
                            session_id = sessions_data.get(key, {}).get('sessionId')
                            del sessions_data[key]
                            deleted_count += 1
                            
                            if session_id:
                                jsonl_path = os.path.join(os.path.dirname(sessions_json_path), f"{session_id}.jsonl")
                                if os.path.exists(jsonl_path):
                                    os.remove(jsonl_path)
                    
                    with open(sessions_json_path, 'w') as f:
                        json.dump(sessions_data, f, indent=2)
                    
                    logger.info(f"[BG] Deleted {deleted_count} OpenClaw sessions")
                except Exception as e:
                    logger.warning(f"[BG] Failed to delete OpenClaw sessions: {e}")
            
            logger.info(f"[BG] ✅ Cleanup completed for project {project_id}")
            return cleanup_result
        except Exception as e:
            logger.error(f"[BG] ❌ Cleanup failed for project {project_id}: {e}")
            return {"error": str(e)}
    
    # Start background task
    asyncio.create_task(cleanup_task())
    
    # IMMEDIATE RESPONSE - project already deleted from DB
    return {
        "status": "deleted",
        "message": "Project deleted successfully (infrastructure cleanup running in background)",
        "project_id": project_id,
        "project_name": project_name,
        "cleanup": "running"
    }

class UpdateProjectRequest(BaseModel):
    """Request model for updating project name and description only."""
    name: Optional[str] = None
    description: Optional[str] = None
    type_id: Optional[int] = Field(None, alias="typeId")
    domain: Optional[str] = None

class ProjectStatusResponse(BaseModel):
    """Response model for project status endpoint."""
    status: str  # "creating", "ready", or "failed"

@app.put("/projects/{project_id}", response_model=ProjectResponse, status_code=200)
async def update_project(project_id: int, request: UpdateProjectRequest):
    """Update project name and description only. type_id and domain cannot be modified."""

    # Validate that project exists
    with get_db() as conn:
        project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not project:
            raise HTTPException(
                status_code=404,
                detail=f"Project with id {project_id} not found"
            )

    # Reject if trying to modify type_id or domain
    if request.type_id is not None or request.domain is not None:
        raise HTTPException(
            status_code=400,
            detail="Project type and domain cannot be modified once created"
        )

    # Build UPDATE statement dynamically based on provided fields
    update_fields = []
    update_values = []

    if request.name is not None:
        if not request.name.strip():
            raise HTTPException(
                status_code=400,
                detail="Project name cannot be empty"
            )
        update_fields.append("name = ?")
        update_values.append(request.name.strip())

    if request.description is not None:
        update_fields.append("description = ?")
        update_values.append(request.description)

    # If no valid fields to update, return current project
    if not update_fields:
        return ProjectResponse(**dict(project))

    # Update project
    with get_db() as conn:
        update_values.append(project_id)  # Add project_id as last parameter
        set_clause = ", ".join(update_fields)
        conn.execute(
            f"UPDATE projects SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            update_values
        )
        conn.commit()

    # Fetch and return updated project
    with get_db() as conn:
        updated_project = conn.execute(
            "SELECT * FROM projects WHERE id = ?",
            (project_id,)
        ).fetchone()

    return ProjectResponse(**dict(updated_project))

# ============================================================================
# Build & Publish Endpoints
# ============================================================================

class BuildPublishRequest(BaseModel):
    """Request model for build & publish operations"""
    project_path: str = Field(..., description="Absolute path to project directory")
    project_name: Optional[str] = Field(None, description="Project name for PM2 restart")
    domain: Optional[str] = Field(None, description="Domain for placeholder replacement")
    skip_install: bool = Field(False, description="Skip npm/pip install")
    skip_build: bool = Field(False, description="Skip build step")
    restart: bool = Field(True, description="Restart PM2 and nginx after build")

class BuildPublishResponse(BaseModel):
    """Response model for build & publish operations"""
    success: bool
    message: str
    output: Optional[str] = None
    error: Optional[str] = None

@app.post("/projects/{project_id}/publish/frontend", response_model=BuildPublishResponse)
async def publish_frontend(project_id: int, request: BuildPublishRequest):
    """
    Build and publish frontend for a project.
    
    Steps:
    1. Clean Vite caches
    2. Remove node_modules
    3. npm install --include=dev --legacy-peer-deps
    4. npm run build
    5. Verify dist/
    6. Fix permissions
    7. Cleanup node_modules
    8. Restart PM2/nginx (optional)
    
    Args:
        project_id: Project ID
        request: Build configuration
    
    Returns:
        Build status and output
    """
    import threading
    
    # Validate project exists
    with get_db() as conn:
        project = conn.execute(
            "SELECT id, name, project_path, status FROM projects WHERE id = ?",
            (project_id,)
        ).fetchone()
    
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    
    # Use project_path from DB if not provided in request
    project_path = request.project_path or project["project_path"]
    frontend_path = Path(project_path) / "frontend"
    
    if not frontend_path.exists():
        raise HTTPException(status_code=400, detail=f"Frontend directory not found: {frontend_path}")
    
    if not (frontend_path / "package.json").exists():
        raise HTTPException(status_code=400, detail=f"package.json not found in {frontend_path}")
    
    # Build command args
    cmd_args = ["python", "buildpublish.py"]
    if request.skip_install:
        cmd_args.append("--skip-install")
    if request.skip_build:
        cmd_args.append("--skip-build")
    if request.restart:
        cmd_args.append("--restart")
    if request.project_name:
        cmd_args.extend(["--project-name", request.project_name])
    else:
        cmd_args.extend(["--project-name", project["name"]])
    
    logger.info(f"📦 Starting frontend build for project {project_id}: {' '.join(cmd_args)}")
    
    try:
        result = subprocess.run(
            cmd_args,
            cwd=str(frontend_path),
            capture_output=True,
            text=True,
            timeout=900  # 15 minutes
        )
        
        if result.returncode == 0:
            logger.info(f"✅ Frontend build completed for project {project_id}")
            return BuildPublishResponse(
                success=True,
                message="Frontend build and publish completed successfully",
                output=result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout
            )
        else:
            logger.error(f"❌ Frontend build failed for project {project_id}: {result.stderr}")
            return BuildPublishResponse(
                success=False,
                message="Frontend build failed",
                error=result.stderr[-1000:] if len(result.stderr) > 1000 else result.stderr,
                output=result.stdout[-1000:] if len(result.stdout) > 1000 else result.stdout
            )
    
    except subprocess.TimeoutExpired:
        logger.error(f"⏱️ Frontend build timeout for project {project_id}")
        return BuildPublishResponse(
            success=False,
            message="Frontend build timed out (15 min limit)"
        )
    except Exception as e:
        logger.error(f"❌ Frontend build error for project {project_id}: {e}")
        return BuildPublishResponse(
            success=False,
            message=f"Frontend build error: {str(e)}"
        )


@app.post("/projects/{project_id}/publish/backend", response_model=BuildPublishResponse)
async def publish_backend(project_id: int, request: BuildPublishRequest):
    """
    Build and publish backend for a project.
    
    Steps:
    1. pip install -r requirements.txt
    2. Verify main.py
    3. Run migrations (if alembic configured)
    4. Restart PM2/nginx (optional)
    
    Args:
        project_id: Project ID
        request: Build configuration
    
    Returns:
        Build status and output
    """
    # Validate project exists and get domain
    with get_db() as conn:
        project = conn.execute(
            "SELECT id, name, project_path, status, domain FROM projects WHERE id = ?",
            (project_id,)
        ).fetchone()
    
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    
    # Use project_path from DB if not provided in request
    project_path = request.project_path or project["project_path"]
    backend_path = Path(project_path) / "backend"
    
    # Get domain from request or DB
    domain = request.domain or project.get("domain")
    
    if not backend_path.exists():
        raise HTTPException(status_code=400, detail=f"Backend directory not found: {backend_path}")
    
    if not (backend_path / "main.py").exists():
        raise HTTPException(status_code=400, detail=f"main.py not found in {backend_path}")
    
    # Build command args
    cmd_args = ["python", "buildpublish.py"]
    if request.skip_install:
        cmd_args.append("--skip-deps")
    if request.restart:
        cmd_args.append("--restart")
    if request.project_name:
        cmd_args.extend(["--project-name", request.project_name])
    else:
        cmd_args.extend(["--project-name", project["name"]])
    if domain:
        cmd_args.extend(["--domain", domain])
    
    logger.info(f"🔧 Starting backend build for project {project_id}: {' '.join(cmd_args)}")
    
    try:
        result = subprocess.run(
            cmd_args,
            cwd=str(backend_path),
            capture_output=True,
            text=True,
            timeout=600  # 10 minutes
        )
        
        if result.returncode == 0:
            logger.info(f"✅ Backend build completed for project {project_id}")
            return BuildPublishResponse(
                success=True,
                message="Backend build and publish completed successfully",
                output=result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout
            )
        else:
            logger.error(f"❌ Backend build failed for project {project_id}: {result.stderr}")
            return BuildPublishResponse(
                success=False,
                message="Backend build failed",
                error=result.stderr[-1000:] if len(result.stderr) > 1000 else result.stderr,
                output=result.stdout[-1000:] if len(result.stdout) > 1000 else result.stdout
            )
    
    except subprocess.TimeoutExpired:
        logger.error(f"⏱️ Backend build timeout for project {project_id}")
        return BuildPublishResponse(
            success=False,
            message="Backend build timed out (10 min limit)"
        )
    except Exception as e:
        logger.error(f"❌ Backend build error for project {project_id}: {e}")
        return BuildPublishResponse(
            success=False,
            message=f"Backend build error: {str(e)}"
        )


@app.get("/projects/{project_id}/status", response_model=ProjectStatusResponse)
async def get_project_status(project_id: int):
    """
    Get project creation status.

    Returns the current status of the project:
    - "creating": OpenClaw is running in background
    - "ready": OpenClaw completed successfully
    - "failed": OpenClaw failed

    Args:
        project_id: Project ID

    Returns:
        Project status

    Raises:
        404: If project not found
    """
    with get_db() as conn:
        project = conn.execute(
            "SELECT status FROM projects WHERE id = ?",
            (project_id,)
        ).fetchone()

    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project with id {project_id} not found"
        )

    return ProjectStatusResponse(status=project["status"])

@app.get("/projects/{project_id}/ai-status", response_model=Dict[str, Any])
async def get_ai_status(project_id: int):
    """
    Get AI refinement status for a project.

    Returns detailed status of Claude Code AI refinement (Phase 8):
    - Process running or not
    - PID if running
    - Elapsed time
    - Recent file modifications
    - Project path and frontend path

    Args:
        project_id: Project ID

    Returns:
        AI status details

    Raises:
        404: If project not found
    """
    import time

    # Get project info
    with get_db() as conn:
        project = conn.execute(
            "SELECT id, name, project_path, claude_code_session_name, status, created_at FROM projects WHERE id = ?",
            (project_id,)
        ).fetchone()

    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project with id {project_id} not found"
        )

    project_path = Path(project["project_path"])
    frontend_path = project_path / "frontend"

    # Check for openclaw_wrapper process
    claude_wrapper_pid = None
    claude_process_info = None

    # Find openclaw_wrapper.py process for this project
    try:
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True,
            text=True,
            timeout=5
        )

        for line in result.stdout.split('\n'):
            if f"openclaw_wrapper.py {project_id}" in line:
                parts = line.split()
                if len(parts) >= 2:
                    claude_wrapper_pid = int(parts[1])
                    break
    except Exception as e:
        logger.warning(f"Failed to check openclaw_wrapper process: {e}")

    # Check for Claude Code process
    claude_pid = None
    if claude_wrapper_pid:
        try:
            result = subprocess.run(
                ["ps", "-p", str(claude_wrapper_pid), "-o", "ppid="],
                capture_output=True,
                text=True,
                timeout=5
            )

            # Get parent PID of openclaw_wrapper
            claude_ppid = result.stdout.strip()
            if claude_ppid and claude_ppid.isdigit():
                claude_pid = int(claude_ppid)

        except Exception as e:
            logger.warning(f"Failed to find Claude Code PID: {e}")

    # Get elapsed time if processes running
    elapsed_seconds = 0
    elapsed_display = "0:00"

    if claude_wrapper_pid:
        try:
            # Get start time
            result = subprocess.run(
                ["ps", "-p", str(claude_wrapper_pid), "-o", "etime="],
                capture_output=True,
                text=True,
                timeout=5
            )
            elapsed_str = result.stdout.strip()
            elapsed_display = elapsed_str
        except Exception:
            pass

    # Check for recent file modifications in frontend (last 5 minutes)
    recent_files = []
    if frontend_path.exists():
        try:
            result = subprocess.run(
                ["find", str(frontend_path), "-type", "f", "-name", "*.tsx", "-o", "-name", "*.ts",
                 "-mmin", "-5"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.stdout:
                recent_files = [
                    Path(f).name for f in result.stdout.strip().split('\n') if f and f.strip()
                ][:10]  # Limit to 10 files
        except Exception as e:
            logger.warning(f"Failed to check recent files: {e}")

    # Build status response
    ai_status = {
        "project_id": project_id,
        "project_name": project["name"],
        "project_status": project["status"],
        "ai_refinement_status": None,
        "processes": {
            "openclaw_wrapper": {
                "running": claude_wrapper_pid is not None,
                "pid": claude_wrapper_pid,
                "elapsed": elapsed_display
            },
            "claude_code": {
                "running": claude_pid is not None,
                "pid": claude_pid
            }
        },
        "paths": {
            "project": str(project_path),
            "frontend": str(frontend_path)
        },
        "recent_activity": {
            "files_modified": recent_files,
            "count": len(recent_files)
        },
        "phase_info": {
            "phase": 8,
            "phase_name": "AI-Driven Frontend Refinement",
            "total_phases": 8,
            "completed_phases": 7
        }
    }

    # Determine overall AI refinement status
    if project["status"] == "ai_provisioning":
        ai_status["ai_refinement_status"] = "in_progress"
    elif project["status"] == "ready":
        ai_status["ai_refinement_status"] = "completed"
    elif project["status"] == "failed":
        ai_status["ai_refinement_status"] = "failed"
    else:
        ai_status["ai_refinement_status"] = "not_started"

    return ai_status

@app.get("/projects/{project_id}/claude-session")
async def get_claude_session(project_id: int):
    """
    Get Claude Code session details for a project.

    Returns Claude Code session information for tracking progress.

    Args:
        project_id: Project ID

    Returns:
        Claude Code session details including session_name and status

    Raises:
        404: If project not found or has no session
    """
    with get_db() as conn:
        project = conn.execute(
            "SELECT id, claude_code_session_name, status FROM projects WHERE id = ?",
            (project_id,)
        ).fetchone()

    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project with id {project_id} not found"
        )

    if not project["claude_code_session_name"]:
        raise HTTPException(
            status_code=404,
            detail=f"Project has no Claude Code session (only website projects get sessions)"
        )

    # Check if Claude Code wrapper process is running
    try:
        # Check for Python wrapper process running
        result = subprocess.run(
            ["pgrep", "-f", f"python3.*claude_wrapper.py.*{project_id}"],
            capture_output=True,
            text=True,
            timeout=5
        )

        is_running = result.returncode == 0 and result.stdout.strip()

        return {
            "project_id": project_id,
            "session_name": project["claude_code_session_name"],
            "status": project["status"],
            "is_running": is_running,
            "message": "Claude Code wrapper is running" if is_running else "Claude Code wrapper has finished"
        }
    except Exception as e:
        logger.error(f"Failed to check Claude Code wrapper process status: {e}")
        return {
            "project_id": project_id,
            "session_name": project["claude_code_session_name"],
            "status": project["status"],
            "is_running": None,
            "message": f"Could not determine process status: {str(e)}"
        }

# ============================================================================
# Session Locking Endpoints
# ============================================================================

class ActiveSessionResponse(BaseModel):
    active_session_id: Optional[int] = None
    session_name: Optional[str] = None

@app.get("/projects/{project_id}/active-session", response_model=ActiveSessionResponse)
async def get_active_session(project_id: int):
    """
    Get the active (locked) session for a project.
    
    Returns the session that currently holds the lock on this project,
    or null if the project is unlocked.
    
    Args:
        project_id: Project ID
        
    Returns:
        Active session ID and name, or null if unlocked
    """
    result = SessionLockService.get_active_session(project_id)
    return ActiveSessionResponse(
        active_session_id=result["active_session_id"],
        session_name=result["session_name"]
    )

@app.delete("/projects/{project_id}/lock")
async def force_release_project_lock(project_id: int):
    """
    Force release any lock on a project (admin override).
    
    Use for crash recovery when a session didn't complete properly
    and the lock is still held.
    
    Args:
        project_id: Project ID to unlock
        
    Returns:
        Released session ID if a lock was held
    """
    result = SessionLockService.force_release_lock(project_id)
    
    if result["released_session_id"]:
        logger.warning(f"[ADMIN] Force released lock on project {project_id}, was held by session {result['released_session_id']}")
        return {
            "success": True,
            "released_session_id": result["released_session_id"],
            "message": f"Lock released from session {result['released_session_id']}"
        }
    else:
        return {
            "success": True,
            "released_session_id": None,
            "message": "Project was not locked"
        }

@app.post("/sessions/{session_id}/release-lock")
async def release_session_lock(session_id: int):
    """
    Explicitly release lock held by a session.
    
    Allows frontend to end a session's lock without deleting the session.
    Useful for "End Chat" buttons.
    
    Args:
        session_id: Session ID to release lock for
        
    Returns:
        Success status
    """
    # Get project_id from session
    with get_db() as conn:
        session = conn.execute(
            "SELECT project_id FROM sessions WHERE id = ?",
            (session_id,)
        ).fetchone()
        
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        
        project_id = session["project_id"]
    
    result = SessionLockService.release_lock(project_id, session_id)
    
    if result["released"]:
        return {"success": True, "message": "Lock released"}
    else:
        return {"success": True, "message": "No lock held by this session"}

# ============================================================================
# Session Endpoints
# ============================================================================

@app.get("/projects/{project_id}/sessions", response_model=list[SessionResponse])
async def get_sessions(project_id: int):
    with get_db() as conn:
        sessions = conn.execute(
            "SELECT * FROM sessions WHERE project_id = ? AND archived = 0 ORDER BY created_at DESC",
            (project_id,)
        ).fetchall()

    # Convert datetime objects to strings for PostgreSQL compatibility
    session_responses = []
    for s in sessions:
        session_dict = dict(s) if isinstance(s, dict) else dict(s)
        # Convert datetime fields to strings
        if "created_at" in session_dict and isinstance(session_dict.get("created_at"), (datetime,)):
            session_dict["created_at"] = str(session_dict["created_at"])
        if "last_used_at" in session_dict and isinstance(session_dict.get("last_used_at"), (datetime,)):
            session_dict["last_used_at"] = str(session_dict["last_used_at"])
        session_responses.append(SessionResponse(**session_dict))

    return session_responses

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

        # Handle both dict (PostgreSQL) and tuple (SQLite) row types
        if isinstance(result, dict):
            # PostgreSQL: RealDictRow (already a dict)
            session_data = result.copy()
            # Convert datetime fields to strings
            if "created_at" in session_data and isinstance(session_data.get("created_at"), (datetime,)):
                session_data["created_at"] = str(session_data["created_at"])
            if "last_used_at" in session_data and isinstance(session_data.get("last_used_at"), (datetime,)):
                session_data["last_used_at"] = str(session_data["last_used_at"])
        else:
            # SQLite: Tuple-like access
            session_data = {
                "id": result[0],
                "project_id": result[1],
                "session_key": result[2],
                "label": result[3],
                "archived": result[4] or 0,
                "scope": result[5],
                "channel": result[6],
                "agent_id": result[7],
                "created_at": result[8],
                "last_used_at": result[9]
            }
            # Convert datetime fields to strings if they're datetime objects
            if isinstance(session_data.get("created_at"), (datetime,)):
                session_data["created_at"] = str(session_data["created_at"])
            if isinstance(session_data.get("last_used_at"), (datetime,)):
                session_data["last_used_at"] = str(session_data["last_used_at"])

        return SessionResponse(**session_data)

@app.delete("/sessions/{session_id}")
async def delete_session(session_id: int):
    # Get project_id before deletion to release lock
    with get_db() as conn:
        session_info = conn.execute(
            "SELECT project_id FROM sessions WHERE id = ?",
            (session_id,)
        ).fetchone()
        
        if session_info:
            project_id = session_info['project_id']
            # Release lock if held by this session
            SessionLockService.release_lock(project_id, session_id)
        
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
    
    return {"status": "deleted", "message": "Session deleted"}

@app.delete("/projects/{project_id}/sessions/{session_id}")
async def delete_project_session(project_id: int, session_id: int):
    """Delete a specific session within a project."""
    # Release lock if held by this session
    SessionLockService.release_lock(project_id, session_id)
    
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

    # Convert datetime objects to strings for PostgreSQL compatibility
    message_responses = []
    for m in messages:
        message_dict = dict(m) if isinstance(m, dict) else dict(m)
        # Convert created_at to string if it's a datetime object
        if "created_at" in message_dict and isinstance(message_dict.get("created_at"), (datetime,)):
            message_dict["created_at"] = str(message_dict["created_at"])
        message_responses.append(MessageResponse(**message_dict))

    return message_responses

@app.post("/chat/stream")
async def chat_stream_endpoint(request: ChatRequest):
    """Handle streaming chat requests using extracted chat handlers."""
    import asyncio
    from chat_handlers import StreamState, save_stream_to_db, generate_sse_stream_with_db_save

    logger.info(f"[STREAM ENDPOINT] Called with session_key={request.session_key}, stream={request.stream}")

    with get_db() as conn:
        session = conn.execute(
            "SELECT * FROM sessions WHERE session_key = ? AND archived = 0",
            (request.session_key,)
        ).fetchone()

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        session_id = session['id']
        project_id = session['project_id']
        
        # === SESSION LOCK CHECK ===
        # Acquire lock for this project/session
        lock_result = SessionLockService.acquire_lock(project_id, session_id)
        if not lock_result["success"]:
            raise HTTPException(
                status_code=423,  # Locked
                detail={"error": lock_result["error"], "active_session_id": lock_result.get("active_session_id")}
            )
        # === END SESSION LOCK CHECK ===

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
        logger.info(f"[STREAM ENDPOINT] User message saved for session {session_id}")

    # Create shared state that survives client disconnect
    state = StreamState()
    state.session_id = session_id
    logger.info(f"[STREAM ENDPOINT] Starting streaming response for session {session_id}")

    # Handle ACP mode - route to ACPX for frontend editing with file access
    if request.acp_mode:
        logger.info(f"[ACP-STREAM] === ACP MODE STARTED ===")
        logger.info(f"[ACP-STREAM] Session key: {request.session_key}")
        logger.info(f"[ACP-STREAM] Session ID: {session_id}")
        logger.info(f"[ACP-STREAM] User message: {user_content[:200]}...")
        
        from acp_chat_handler import get_acp_chat_handler
        import asyncio
        import re
        
        try:
            # Get ACP handler (validates project path)
            logger.info(f"[ACP-STREAM] Getting ACP handler...")
            handler = get_acp_chat_handler(request.session_key)
            if not handler:
                logger.error(f"[ACP-STREAM] Failed to get ACP handler - project not found")
                raise ValueError("Could not initialize ACP handler - project not found or invalid path")
            
            logger.info(f"[ACP-STREAM] Handler initialized for project: {handler.project_name}")
            logger.info(f"[ACP-STREAM] Frontend path: {handler.frontend_src_path}")
            
            # Handle image for ACP mode - save to temp file and use path instead of base64
            acp_user_content = user_content
            image_path_for_context = None
            
            if request.image:
                logger.info(f"[ACP-STREAM] Image detected, saving to temp file...")
                # Save image to temp file for ACPX to access
                import base64
                import uuid
                temp_dir = "/tmp/acp_images"
                os.makedirs(temp_dir, exist_ok=True)
                image_filename = f"{session_id}_{uuid.uuid4().hex[:8]}.png"
                image_path = os.path.join(temp_dir, image_filename)
                
                try:
                    # Decode and save image
                    image_data = base64.b64decode(request.image)
                    with open(image_path, 'wb') as f:
                        f.write(image_data)
                    image_path_for_context = image_path
                    acp_user_content = f"{user_content}\n\n[Image attached: {image_path}]"
                    logger.info(f"[ACP-STREAM] Saved image to {image_path} ({len(image_data)} bytes)")
                except Exception as img_err:
                    logger.error(f"[ACP-STREAM] Failed to save image: {img_err}")
                    acp_user_content = f"{user_content}\n\n[Image was attached but could not be saved]"
            
            # Get conversation context from database for continuity (last 4 messages = 2 exchanges)
            # Replace base64 images with placeholder to avoid bloating context
            session_context = ""
            try:
                with get_db() as conn:
                    rows = conn.execute(
                        """SELECT role, content, image FROM messages 
                           WHERE session_id = ? 
                           ORDER BY created_at DESC LIMIT 4""",
                        (session_id,)
                    ).fetchall()
                    if rows:
                        context_parts = []
                        for row in reversed(rows):  # Chronological order
                            role = row['role'] if isinstance(row, dict) else row[0]
                            content = row['content'] if isinstance(row, dict) else row[1]
                            image = row['image'] if isinstance(row, dict) else row[2] if len(row) > 2 else None
                            
                            # If message has image, add placeholder instead of base64
                            if image:
                                content = f"{content}\n\n[Image was attached in previous message]"
                            
                            context_parts.append(f"{role.upper()}: {content}")
                        session_context = "\n\n".join(context_parts)
                        logger.info(f"[ACP-STREAM] Loaded {len(rows)} messages as context ({len(session_context)} chars)")
            except Exception as ctx_err:
                logger.warning(f"[ACP-STREAM] Could not load context: {ctx_err}")
            
            # Log prompt framing before sending to Claude
            logger.info(f"[ACP-STREAM] === PROMPT FRAMING ===")
            logger.info(f"[ACP-STREAM] User message: {acp_user_content[:200]}...")
            logger.info(f"[ACP-STREAM] Session context: {session_context[:500]}...")
            logger.info(f"[ACP-STREAM] ========================")
            
            # ── PREPROCESSOR CHECK ────────────────────────────────────────────
            # Try fast LLM first to see if we can skip ACPX
            direct_response = None
            try:
                from acp_chat_handler import check_preprocessor
                project_name = handler.project_name if handler else "App"
                project_path = handler.frontend_src_path if handler else None
                direct_response = await check_preprocessor(acp_user_content, project_name, project_path)
                if direct_response:
                    logger.info(f"[ACP-STREAM] Using preprocessor direct response")
            except Exception as pre_err:
                logger.warning(f"[ACP-STREAM] Preprocessor check failed: {pre_err}")
            
            # If preprocessor handled it, return direct response
            if direct_response:
                async def preprocessor_response():
                    """Return preprocessor's direct response."""
                    event_data = json.dumps({'choices': [{'delta': {'content': direct_response + "\n"}}]})
                    yield f"data: {event_data}\n\n"
                    
                    # Save to database
                    try:
                        with get_db() as save_conn:
                            save_conn.execute(
                                "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                                (session_id, 'assistant', direct_response)
                            )
                            save_conn.commit()
                            logger.info(f"[ACP-STREAM] Saved preprocessor response ({len(direct_response)} chars)")
                    except Exception as save_err:
                        logger.error(f"[ACP-STREAM] Failed to save preprocessor response: {save_err}")
                    
                    logger.info(f"[ACP-STREAM] === PREPROCESSOR RESPONSE COMPLETED ===")
                
                return StreamingResponse(
                    preprocessor_response(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no"
                    }
                )
            # ── END PREPROCESSOR CHECK ────────────────────────────────────────
            
            # Run streaming with unified backend (ClaudeCodeAgent or ACPX fallback)
            logger.info(f"[ACP-STREAM] Starting unified streaming (timeout: 900s)...")
            
            async def acp_streaming_response():
                """Stream output in real-time via SSE using best available backend."""
                full_response = []
                
                async def save_response_to_db(content: str):
                    """Save response to DB."""
                    try:
                        with get_db() as save_conn:
                            save_conn.execute(
                                "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                                (session_id, 'assistant', content)
                            )
                            save_conn.execute(
                                "UPDATE sessions SET last_used_at = CURRENT_TIMESTAMP WHERE id = ?",
                                (session_id,)
                            )
                            save_conn.commit()
                        logger.info(f"[ACP-STREAM] Saved assistant message ({len(content)} chars)")
                    except Exception as save_err:
                        logger.error(f"[ACP-STREAM] Failed to save message: {save_err}")
                
                async def background_save_when_complete():
                    """Wait for query to complete in background, then save to DB."""
                    # Wait for the handler to signal completion
                    max_wait = 600  # 10 minutes max
                    waited = 0
                    while waited < max_wait:
                        await asyncio.sleep(1)
                        waited += 1
                        # Check if handler has collected all chunks
                        if hasattr(handler, '_last_query_chunks'):
                            chunks = handler._last_query_chunks
                            # Filter out PROGRESS: messages, keep TEXT: and unprefixed
                            real_chunks = [c for c in chunks if not c.startswith('PROGRESS:')]
                            # Strip TEXT: prefix from actual content
                            real_chunks = [c[5:] if c.startswith('TEXT:') else c for c in real_chunks]
                            if real_chunks:
                                content = '\n'.join(real_chunks).strip()
                                if content:
                                    logger.info(f"[ACP-STREAM] Background save: {len(content)} chars after {waited}s")
                                    await save_response_to_db(content)
                                    return
                        # Also check for direct response
                        if hasattr(handler, '_last_query_response') and handler._last_query_response:
                            logger.info(f"[ACP-STREAM] Background save from response: {len(handler._last_query_response)} chars")
                            await save_response_to_db(handler._last_query_response)
                            return
                    logger.warning(f"[ACP-STREAM] Background save timed out after {max_wait}s")
                
                try:
                    # Use unified streaming method
                    async for chunk in handler.run_chat_streaming_unified(acp_user_content, session_context):
                        # Yield SSE event for each chunk (with newline for chat display)
                        full_response.append(chunk)
                        event_data = json.dumps({'choices': [{'delta': {'content': chunk + "\n"}}]})
                        yield f"data: {event_data}\n\n"
                        logger.info(f"[ACP-STREAM] Yielded chunk: {len(chunk)} chars")
                    
                    # Filter out PROGRESS: messages, keep TEXT: and unprefixed
                    real_chunks = [c for c in full_response if not c.startswith('PROGRESS:')]
                    # Strip TEXT: prefix from actual content
                    real_chunks = [c[5:] if c.startswith('TEXT:') else c for c in real_chunks]
                    
                    # Save complete response to database (with newlines between chunks)
                    assistant_content = '\n'.join(real_chunks).strip()
                    
                    if assistant_content:
                        await save_response_to_db(assistant_content)
                    
                    # Cleanup temp image file
                    if image_path_for_context and os.path.exists(image_path_for_context):
                        try:
                            os.remove(image_path_for_context)
                            logger.info(f"[ACP-STREAM] Cleaned up temp image")
                        except:
                            pass
                    
                    logger.info(f"[ACP-STREAM] === ACP STREAMING COMPLETED ===")
                    
                except asyncio.CancelledError:
                    # Client disconnected - spawn background task to save when complete
                    logger.warning(f"[ACP-STREAM] Client disconnected, spawning background save task...")
                    
                    # Filter out PROGRESS: messages from what we have so far
                    real_chunks = [c for c in full_response if not c.startswith('PROGRESS:')]
                    # Strip TEXT: prefix from actual content
                    real_chunks = [c[5:] if c.startswith('TEXT:') else c for c in real_chunks]
                    
                    # Spawn background task that will poll until query completes
                    async def wait_and_save():
                        """Poll until query completion then save."""
                        try:
                            max_wait = 600  # 10 minutes max
                            poll_interval = 5  # Check every 5 seconds
                            waited = 0
                            
                            while waited < max_wait:
                                await asyncio.sleep(poll_interval)
                                waited += poll_interval
                                
                                # Check handler for collected chunks
                                if hasattr(handler, '_last_query_chunks'):
                                    chunks = handler._last_query_chunks
                                    # Filter out PROGRESS: messages, keep TEXT: and unprefixed
                                    real = [c for c in chunks if not c.startswith('PROGRESS:')]
                                    # Strip TEXT: prefix from actual content
                                    real = [c[5:] if c.startswith('TEXT:') else c for c in real]
                                    if real:
                                        content = '\n'.join(real).strip()
                                        if content and len(content) > 50:  # Ensure we have real content
                                            logger.info(f"[ACP-STREAM] Background saved after {waited}s: {len(content)} chars")
                                            await save_response_to_db(content)
                                            return
                                
                                # Also check for direct response
                                if hasattr(handler, '_last_query_response') and handler._last_query_response:
                                    content = handler._last_query_response.strip()
                                    if content and len(content) > 20:
                                        logger.info(f"[ACP-STREAM] Background saved (response) after {waited}s: {len(content)} chars")
                                        await save_response_to_db(content)
                                        return
                            
                            # Fall back to what we collected before disconnect
                            if real_chunks:
                                content = '\n'.join(real_chunks).strip()
                                logger.info(f"[ACP-STREAM] Background saved (partial, timeout): {len(content)} chars")
                                await save_response_to_db(content)
                            else:
                                logger.warning(f"[ACP-STREAM] Background save: no content after {max_wait}s")
                        except Exception as e:
                            logger.error(f"[ACP-STREAM] Background save error: {e}")
                    
                    # Create task that survives disconnection
                    asyncio.create_task(wait_and_save())
                    logger.info(f"[ACP-STREAM] Background save task spawned")
                    
                    
                    logger.info(f"[ACP-STREAM] === ACP STREAMING COMPLETED (client disconnected) ===")
                    raise
                    
                except Exception as stream_err:
                    logger.error(f"[ACP-STREAM] Streaming error: {stream_err}")
                    error_msg = f"Error: {str(stream_err)}"
                    event_data = json.dumps({'error': error_msg})
                    yield f"data: {event_data}\n\n"
                
                yield "data: [DONE]\n\n"
            
            return StreamingResponse(
                acp_streaming_response(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                }
            )
        except Exception as e:
            logger.error(f"[STREAM ENDPOINT] ACP mode error: {e}")
            error_content = f"Error: ACP chat failed - {str(e)}"
            state.content = error_content
            save_stream_to_db(state)
            
            async def error_stream():
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
                yield "data: [DONE]\n\n"
            
            return StreamingResponse(
                error_stream(),
                media_type="text/event-stream"
            )

    # Use non-streaming request to OpenClaw, then wrap in SSE format
    # This is more reliable than true streaming which had issues with async generators
    import httpx
    from context_injector import ContextInjector
    context_injector = ContextInjector()
    
    CLAWDBOT_BASE_URL = os.getenv("CLAWDBOT_BASE_URL", "http://localhost:18789")
    CLAWDBOT_TOKEN = os.getenv("CLAWDBOT_TOKEN", "355fc5e1f0d6078a8a9a56f684d551d803f92decf956d11ca7494f0f461b470a")
    
    user_field = f"adapter-session-{request.session_key}"
    user_messages = [{"role": "user", "content": user_content}]
    messages_with_context = context_injector.inject_system_context(
        request.session_key,
        user_messages
    )
    
    request_body = {
        "model": "agent:main",
        "user": user_field,
        "messages": messages_with_context,
        "stream": False
    }
    
    headers = {
        "Authorization": f"Bearer {CLAWDBOT_TOKEN}",
        "Content-Type": "application/json",
    }
    
    logger.info(f"[STREAM] Sending request to OpenClaw for session {session_id}")
    
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{CLAWDBOT_BASE_URL}/v1/chat/completions",
                json=request_body,
                headers=headers
            )
            logger.info(f"[STREAM] Response status: {response.status_code}, length: {len(response.content)} bytes")
            
            if response.status_code == 200 and response.content:
                result = response.json()
                assistant_content = result.get('choices', [{}])[0].get('message', {}).get('content', 'No response')
                logger.info(f"[STREAM] Got response for session {session_id}: {len(assistant_content)} chars")
                
                # Save to database
                state.content = assistant_content
                save_stream_to_db(state)
                
                # Return as SSE stream (single event for compatibility)
                async def single_chunk_stream():
                    event_data = json.dumps({'choices': [{'delta': {'content': assistant_content}}]})
                    yield f"data: {event_data}\n\n"
                    yield "data: [DONE]\n\n"
                
                return StreamingResponse(
                    single_chunk_stream(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Accel-Buffering": "no",
                    }
                )
            else:
                error_msg = response.text[:500] if response.text else "No response body"
                logger.error(f"[STREAM] OpenClaw error: status={response.status_code}, body={error_msg}")
                error_content = f"Error: AI service returned status {response.status_code}"
                state.content = error_content
                save_stream_to_db(state)
                
                async def error_stream():
                    yield f"data: {json.dumps({'error': error_content})}\n\n"
                    yield "data: [DONE]\n\n"
                
                return StreamingResponse(
                    error_stream(),
                    media_type="text/event-stream"
                )
    except Exception as e:
        logger.error(f"[STREAM] Exception for session {session_id}: {e}")
        state.content = f"Error: {str(e)}"
        save_stream_to_db(state)
        
        async def error_stream():
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"
        
        return StreamingResponse(
            error_stream(),
            media_type="text/event-stream"
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
        project_id = session['project_id']
        
        # === SESSION LOCK CHECK ===
        # Acquire lock for this project/session
        lock_result = SessionLockService.acquire_lock(project_id, session_id)
        if not lock_result["success"]:
            raise HTTPException(
                status_code=423,  # Locked
                detail={"error": lock_result["error"], "active_session_id": lock_result.get("active_session_id")}
            )
        # === END SESSION LOCK CHECK ===

        user_messages = [msg for msg in request.messages if msg.role == 'user']

        if not user_messages:
            raise HTTPException(status_code=400, detail="No user message provided")

        last_user_message = user_messages[-1]
        user_content = last_user_message.content

        # Insert user message and COMMIT IMMEDIATELY (ensures user message saved even if API fails)
        # Image belongs to USER message, not assistant
        if request.image:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, image) VALUES (?, ?, ?, ?)",
                (session_id, 'user', user_content, request.image)
            )
        else:
            conn.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, 'user', user_content)
            )
        conn.commit()

        # Check for ACP mode - frontend editing via ACPX
        if request.acp_mode:
            logger.info(f"[ACP-MODE] === ACP MODE STARTED (non-streaming) ===")
            logger.info(f"[ACP-MODE] Session key: {request.session_key}")
            logger.info(f"[ACP-MODE] Session ID: {session_id}")
            logger.info(f"[ACP-MODE] User message: {user_content[:200]}...")
            
            from acp_chat_handler import get_acp_chat_handler
            import asyncio
            import base64
            import uuid
            
            # Get ACP handler (validates project path)
            logger.info(f"[ACP-MODE] Getting ACP handler...")
            handler = get_acp_chat_handler(request.session_key)
            if not handler:
                logger.error(f"[ACP-MODE] Failed to get ACP handler - project not found")
                assistant_content = "Error: Could not initialize ACP handler - project not found or invalid path"
            else:
                logger.info(f"[ACP-MODE] Handler initialized for project: {handler.project_name}")
                logger.info(f"[ACP-MODE] Frontend path: {handler.frontend_src_path}")
                
                # Handle image for ACP mode - save to temp file and use path instead of base64
                acp_user_content = user_content
                image_path_for_context = None
                
                if request.image:
                    logger.info(f"[ACP-MODE] Image detected, saving to temp file...")
                    # Save image to temp file for ACPX to access
                    temp_dir = "/tmp/acp_images"
                    os.makedirs(temp_dir, exist_ok=True)
                    image_filename = f"{session_id}_{uuid.uuid4().hex[:8]}.png"
                    image_path = os.path.join(temp_dir, image_filename)
                    
                    try:
                        # Decode and save image
                        image_data = base64.b64decode(request.image)
                        with open(image_path, 'wb') as f:
                            f.write(image_data)
                        image_path_for_context = image_path
                        acp_user_content = f"{user_content}\n\n[Image attached: {image_path}]"
                        logger.info(f"[ACP-MODE] Saved image to {image_path} ({len(image_data)} bytes)")
                    except Exception as img_err:
                        logger.error(f"[ACP-MODE] Failed to save image: {img_err}")
                        acp_user_content = f"{user_content}\n\n[Image was attached but could not be saved]"
                
                # Get conversation context from database
                # Replace base64 images with placeholder to avoid bloating context
                session_context = ""
                try:
                    with get_db() as ctx_conn:
                        rows = ctx_conn.execute(
                            """SELECT role, content, image FROM messages 
                               WHERE session_id = ? 
                               ORDER BY created_at DESC LIMIT 10""",
                            (session_id,)
                        ).fetchall()
                        if rows:
                            context_parts = []
                            for row in reversed(rows):
                                role = row['role'] if isinstance(row, dict) else row[0]
                                content = row['content'] if isinstance(row, dict) else row[1]
                                image = row['image'] if isinstance(row, dict) else row[2] if len(row) > 2 else None
                                
                                # If message has image, add placeholder instead of base64
                                if image:
                                    content = f"{content}\n\n[Image was attached in previous message]"
                                
                                context_parts.append(f"{role.upper()}: {content}")
                            session_context = "\n\n".join(context_parts)
                except Exception as ctx_err:
                    logger.warning(f"[ACP-MODE] Could not load context: {ctx_err}")
                
                # Log prompt framing before sending to Claude
                logger.info(f"[ACP-MODE] === PROMPT FRAMING ===")
                logger.info(f"[ACP-MODE] User message: {acp_user_content[:200]}...")
                logger.info(f"[ACP-MODE] Session context: {session_context[:500]}...")
                logger.info(f"[ACP-MODE] ========================")
                
                # Run ACPX (synchronous)
                logger.info(f"[ACP-MODE] Starting ACPX execution (timeout: 300s)...")
                result = handler.run_acpx_chat(acp_user_content, session_context)
                
                logger.info(f"[ACP-MODE] ACPX completed with status: {result.get('status')}")
                assistant_content = result.get('response', '')
                if not result.get('success'):
                    logger.error(f"[ACP-MODE] ACPX failed: {result.get('error')}")
                    assistant_content = f"Error: {result.get('error', 'ACPX failed')}"
                else:
                    logger.info(f"[ACP-MODE] Response length: {len(assistant_content)} chars")
                
                # Kill orphan processes after response
                handler.kill_orphan_processes()
                logger.info(f"[ACP-MODE] Cleaned up ACPX processes for session {session_id}")
                
                # Cleanup temp image file
                if image_path_for_context and os.path.exists(image_path_for_context):
                    try:
                        os.remove(image_path_for_context)
                        logger.info(f"[ACP-MODE] Cleaned up temp image: {image_path_for_context}")
                    except:
                        pass
            
            # Save assistant message
            logger.info(f"[ACP-MODE] Saving assistant message to database...")
            with get_db() as save_conn:
                save_conn.execute(
                    "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                    (session_id, 'assistant', assistant_content)
                )
                save_conn.execute(
                    "UPDATE sessions SET last_used_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (session_id,)
                )
                save_conn.commit()
            
            logger.info(f"[ACP-MODE] === ACP MODE COMPLETED ===")
            
            return ChatResponse(
                id=0,
                role="assistant",
                content=assistant_content,
                created_at=datetime.now().isoformat()
            )

        # Generate assistant response with error handling
        assistant_content = ""

        try:
            if request.image:
                logger.info(f"[IMAGE] Processing image for session {session_id}, image length: {len(request.image)}")
                assistant_content = await handle_chat_with_image(request, session_id, user_content)
                logger.info(f"[IMAGE] Image processed successfully")
            elif not request.image and not request.stream:
                assistant_content = await handle_chat_text_only(request, user_content)
        except Exception as e:
            # CRITICAL: Save error message to database even if API fails
            logger.error(f"Chat API failed for session {session_id}: {e}")
            assistant_content = f"Error: Unable to process request. Please try again. (Details: {str(e)})"

        # GUARANTEED: Insert assistant message (even if it's an error message)
        # Note: Image is stored on USER message, not assistant
        with get_db() as save_conn:
            save_conn.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                (session_id, 'assistant', assistant_content)
            )

            save_conn.execute(
                "UPDATE sessions SET last_used_at = CURRENT_TIMESTAMP WHERE id = ?",
                (session_id,)
            )
            save_conn.commit()
            logger.info(f"[IMAGE] Database commit successful for session {session_id}")

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
# ============================================================================
# Authentication API
# ============================================================================

import bcrypt
import secrets

# In-memory token store (token -> user_id)
AUTH_TOKENS: Dict[str, int] = {}


class LoginRequest(BaseModel):
    email: str
    password: str


class SignupRequest(BaseModel):
    email: str
    password: str
    name: Optional[str] = None


class UserResponse(BaseModel):
    id: str
    email: str
    name: Optional[str] = None


class AuthResponse(BaseModel):
    token: str
    user: UserResponse


class MessageResponseModel(BaseModel):
    message: str


def hash_password(password: str) -> str:
    """Hash password using bcrypt."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against hash."""
    return bcrypt.checkpw(
        password.encode('utf-8'),
        password_hash.encode('utf-8')
    )


def generate_token() -> str:
    """Generate a secure random token."""
    return secrets.token_hex(32)


@app.post("/auth/signup", response_model=AuthResponse)
async def signup(request: SignupRequest):
    """Register a new user and return token."""
    # Check if user already exists
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE email = ?",
            (request.email,)
        ).fetchone()
        
        if existing:
            raise HTTPException(status_code=400, detail="Email already exists")
        
        # Hash password and create user
        password_hash = hash_password(request.password)
        
        conn.execute(
            "INSERT INTO users (email, name, password) VALUES (?, ?, ?) RETURNING id",
            (request.email, request.name, password_hash)
        )
        result = conn.fetchone()
        
        if isinstance(result, dict):
            user_id = result.get('id')
        else:
            user_id = result[0] if result else None
        
        conn.commit()
    
    # Generate token
    token = generate_token()
    AUTH_TOKENS[token] = user_id
    
    return AuthResponse(
        token=token,
        user=UserResponse(
            id=str(user_id),
            email=request.email,
            name=request.name
        )
    )


@app.post("/auth/login", response_model=AuthResponse)
async def login(request: LoginRequest):
    """Login and return token."""
    with get_db() as conn:
        user = conn.execute(
            "SELECT id, email, name, password FROM users WHERE email = ?",
            (request.email,)
        ).fetchone()
        
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        # Handle both dict (PostgreSQL) and tuple (SQLite) row types
        if isinstance(user, dict):
            user_id = user.get('id')
            email = user.get('email')
            name = user.get('name')
            password_hash = user.get('password')
        else:
            user_id = user[0]
            email = user[1]
            name = user[2]
            password_hash = user[3]
        
        # Verify password
        if not password_hash or not verify_password(request.password, password_hash):
            raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Generate token
    token = generate_token()
    AUTH_TOKENS[token] = user_id
    
    return AuthResponse(
        token=token,
        user=UserResponse(
            id=str(user_id),
            email=email,
            name=name
        )
    )


@app.post("/auth/logout")
async def logout(authorization: Optional[str] = Header(None)):
    """Logout and invalidate token."""
    if not authorization:
        return {"message": "Logged out"}
    
    # Extract token from "Bearer <token>"
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        token = parts[1]
        # Remove token from store
        if token in AUTH_TOKENS:
            del AUTH_TOKENS[token]
    
    return {"message": "Logged out"}


@app.get("/auth/me", response_model=UserResponse)
async def get_current_user(authorization: Optional[str] = Header(None)):
    """Get current user from token."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    
    # Extract token from "Bearer <token>"
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization format")
    
    token = parts[1]
    
    # Validate token
    user_id = AUTH_TOKENS.get(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    # Get user from database
    with get_db() as conn:
        user = conn.execute(
            "SELECT id, email, name FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
        
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        # Handle both dict (PostgreSQL) and tuple (SQLite) row types
        if isinstance(user, dict):
            return UserResponse(
                id=str(user.get('id')),
                email=user.get('email'),
                name=user.get('name')
            )
        else:
            return UserResponse(
                id=str(user[0]),
                email=user[1],
                name=user[2]
            )


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


# ============================================================================
# Recent Activity Endpoints
# ============================================================================

from recent_activity_service import (
    get_recent_activity_optimized,
    get_recent_activity_simple,
    get_project_activity_detail,
    RecentActivityResponse,
    RecentActivityItem,
    ProjectActivityDetailResponse
)


@app.get("/projects/recent-activity", response_model=RecentActivityResponse)
async def get_recent_activity(
    limit: int = 20,
    offset: int = 0,
    include_preview: bool = True,
    user_id: int = 1,  # TODO: Get from auth token when auth is implemented
    authorization: Optional[str] = Header(None)
):
    """
    Get recent activity grouped by project.
    
    Returns projects sorted by latest message timestamp across all sessions.
    Used for Activity page (Recent Work UI).
    
    Query params:
        limit: Max projects to return (default 20, max 100)
        offset: Pagination offset (default 0)
        include_preview: Include last message preview (default True)
    
    Response:
        items: List of project activity with:
            - project_id, project_name, project_status
            - last_activity: ISO timestamp of latest message
            - total_messages, total_sessions
            - last_message_preview (if include_preview=true)
            - last_session_id, last_session_label
            - active_session_id (for lock badge)
        total: Total count for pagination
        limit, offset: Current pagination state
    
    Performance:
        - Uses PostgreSQL DISTINCT ON for single-pass query
        - Indexed on messages(session_id, created_at)
        - Lightweight response (preview truncated to 100 chars)
    """
    try:
        # Validate params
        limit = min(max(limit, 1), 100)  # Clamp to 1-100
        offset = max(offset, 0)
        
        # Fetch activity
        items = get_recent_activity_optimized(
            user_id=user_id,
            limit=limit,
            offset=offset,
            include_preview=include_preview,
            preview_length=100
        )
        
        # Get total count for pagination (approximate - count projects with messages)
        with get_db() as cur:
            cur.execute("""
                SELECT COUNT(DISTINCT p.id)
                FROM projects p
                INNER JOIN sessions s ON s.project_id = p.id
                INNER JOIN messages m ON m.session_id = s.id
                WHERE p.user_id = %s
            """, (user_id,))
            total = cur.fetchone()
            total = total[0] if not isinstance(total, dict) else total['count']
        
        return RecentActivityResponse(
            items=items,
            total=total or 0,
            limit=limit,
            offset=offset
        )
        
    except Exception as e:
        logger.error(f"Failed to fetch recent activity: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch recent activity: {str(e)}")


@app.get("/projects/recent-activity/simple")
async def get_recent_activity_simple_endpoint(
    limit: int = 20,
    user_id: int = 1,
    authorization: Optional[str] = Header(None)
):
    """
    Simplified recent activity (faster, no preview).
    Use when preview text is not needed.
    """
    try:
        limit = min(max(limit, 1), 100)
        items = get_recent_activity_simple(user_id=user_id, limit=limit)
        return {"items": items, "count": len(items)}
    except Exception as e:
        logger.error(f"Failed to fetch recent activity (simple): {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/projects/{project_id}/activity", response_model=ProjectActivityDetailResponse)
async def get_project_activity(
    project_id: int,
    message_limit: int = 10,
    authorization: Optional[str] = Header(None)
):
    """
    Get detailed activity for a single project.
    
    Includes:
        - Project details (name, status, domain)
        - Stats (total sessions, total messages)
        - Recent messages across all sessions (up to message_limit)
        - Active session ID (for lock badge)
    
    Query params:
        message_limit: Max recent messages to include (default 10, max 50)
    """
    try:
        message_limit = min(max(message_limit, 1), 50)
        
        result = get_project_activity_detail(
            project_id=project_id,
            message_limit=message_limit
        )
        
        if not result:
            raise HTTPException(status_code=404, detail="Project not found")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch project activity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    print(f"Starting Clawdbot Adapter API...")
    print(f"Images directory: {IMAGES_DIR}")
    print(f"Images accessible at: {IMAGES_BASE_URL}")

    # Dynamic port allocation
    try:
        port = get_next_backend_port()
        print(f"Allocated backend port: {port}")
        uvicorn.run(app, host="0.0.0.0", port=port)
    except Exception as e:
        logger.error(f"Failed to allocate backend port: {e}")
        raise

# TEMPORARY FIX: Make domain field optional to allow testing
# This is a quick workaround to unblock Phase 9 ACP integration
# TODO: Implement proper configurable domain validation with better error handling

# ============================================================================

