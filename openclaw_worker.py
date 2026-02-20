"""
OpenClaw Background Worker Module.
Handles background execution of OpenClaw initialization for website projects.
"""

import threading
import subprocess
import logging
from typing import Optional

from database import get_db

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_openclaw_background(project_id: int, project_path: str, project_name: str, description: Optional[str] = None) -> threading.Thread:
    """
    Run OpenClaw initialization in a background thread.

    This function:
    - Creates and starts a background thread
    - Executes 'openclaw agent' with project-specific session and prompt
    - Updates project status in database (creating → ready/failed)
    - Creates new DB session inside thread (thread safety)
    - Handles errors safely

    Args:
        project_id: Project ID from database
        project_path: Absolute path to project folder
        project_name: Project name
        description: Project description (optional)

    Returns:
        Thread object that has been started

    Thread Safety:
        - Creates new database connection inside thread
        - Does NOT reuse request DB session
        - Closes DB session after completion
    """

    # Create unique session identifier for this project
    # Format: "project-{project_id}" for easy tracking
    project_session_key = f"project-{project_id}-{project_name.replace(' ', '-')}"

    def _worker():
        """Worker function that runs in the background thread."""
        try:
            # Log start
            logger.info(f"Starting OpenClaw background worker for project {project_id}")
            logger.info(f"Project path: {project_path}")
            logger.info(f"Session key: {project_session_key}")

            # Build the exact prompt as specified
            if description:
                prompt = f"""Initialize website project. Project name: {project_name} Description: {description} Follow DreamPilot rules from rule.md strictly. Use template registry at /root/dreampilot/website/frontend/template-registry.json. Select best frontend template. Clone template repository. Setup FastAPI backend. Setup PostgreSQL database. Configure environment variables. Verify deployment."""
            else:
                prompt = f"""Initialize website project. Project name: {project_name} Follow DreamPilot rules from rule.md strictly. Use template registry at /root/dreampilot/website/frontend/template-registry.json. Select best frontend template. Clone template repository. Setup FastAPI backend. Setup PostgreSQL database. Configure environment variables. Verify deployment."""

            # Run OpenClaw subprocess with dedicated session
            # Use --to with session key to create a unique session
            # Set working directory to project_path so OpenClaw can read rule.md, README.md, etc.
            logger.info(f"Executing: openclaw agent --to '{project_session_key}' --message '{prompt}' --local")
            logger.info(f"Working directory: {project_path}")

            result = subprocess.run(
                ["openclaw", "agent", "--to", project_session_key, "--message", prompt, "--local"],
                cwd=project_path,  # Set working directory to project folder
                capture_output=True,
                text=True,
                timeout=1200  # 20 minutes timeout (increased)
            )

            # Check result
            if result.returncode == 0:
                # Success
                logger.info(f"OpenClaw completed successfully for project {project_id}")
                logger.info(f"Output: {result.stdout}")

                # Update project status to 'ready' in NEW DB session
                try:
                    with get_db() as conn:
                        conn.execute(
                            "UPDATE projects SET status = 'ready' WHERE id = ?",
                            (project_id,)
                        )
                        conn.commit()
                        logger.info(f"Project {project_id} status updated to 'ready'")
                except Exception as db_error:
                    logger.error(f"Failed to update project status: {db_error}")

            else:
                # Failure
                logger.error(f"OpenClaw failed for project {project_id}")
                logger.error(f"Return code: {result.returncode}")
                logger.error(f"Error output: {result.stderr}")

                # Update project status to 'failed' in NEW DB session
                try:
                    with get_db() as conn:
                        conn.execute(
                            "UPDATE projects SET status = 'failed' WHERE id = ?",
                            (project_id,)
                        )
                        conn.commit()
                        logger.info(f"Project {project_id} status updated to 'failed'")
                except Exception as db_error:
                    logger.error(f"Failed to update project status: {db_error}")

        except subprocess.TimeoutExpired:
            # Timeout
            logger.error(f"OpenClaw timeout for project {project_id}")

            # Update project status to 'failed' in NEW DB session
            try:
                with get_db() as conn:
                    conn.execute(
                        "UPDATE projects SET status = 'failed' WHERE id = ?",
                        (project_id,)
                    )
                    conn.commit()
                    logger.info(f"Project {project_id} status updated to 'failed' (timeout)")
            except Exception as db_error:
                logger.error(f"Failed to update project status: {db_error}")

        except Exception as e:
            # Unexpected error
            logger.error(f"OpenClaw worker error for project {project_id}: {e}")

            # Update project status to 'failed' in NEW DB session
            try:
                with get_db() as conn:
                    conn.execute(
                        "UPDATE projects SET status = 'failed' WHERE id = ?",
                        (project_id,)
                    )
                    conn.commit()
                    logger.info(f"Project {project_id} status updated to 'failed' (error)")
            except Exception as db_error:
                logger.error(f"Failed to update project status: {db_error}")

        finally:
            # Thread cleanup (DB session is auto-closed by get_db context manager)
            logger.info(f"OpenClaw worker thread for project {project_id} finished")

    # Create and start thread
    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    logger.info(f"Background thread started for project {project_id}")

    return thread
