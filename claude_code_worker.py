"""
Claude Code Background Worker Module.
Handles background execution of Claude Code for website project initialization.
"""

import threading
import subprocess
import logging
import sys
from pathlib import Path
from typing import Optional

from database_adapter import get_db

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Dynamically determine backend directory (works on both Windows and Linux)
BACKEND_DIR = Path(__file__).parent.resolve()
logger.info(f"BACKEND_DIR resolved to: {BACKEND_DIR}")


def run_claude_code_background(project_id: int, project_path: str, project_name: str, description: Optional[str] = None, session_name: str = None, template_id: Optional[str] = None) -> threading.Thread:
    """
    Run Claude Code initialization in a background thread.

    This function:
    - Creates and starts a background thread
    - Executes Claude Code wrapper script
    - Updates project status in database (creating → ready/failed)
    - Creates new DB session inside thread (thread safety)
    - Handles errors safely

    Args:
        project_id: Project ID from database
        project_path: Absolute path to project folder
        project_name: Project name
        description: Project description (optional)
        session_name: Unique session name for Claude Code (for tracking)

    Returns:
        Thread object that has been started

    Thread Safety:
        - Creates new database connection inside thread
        - Does NOT reuse request DB session
        - Closes DB session after completion
    """

    def _worker():
        """Worker function that runs in background thread."""
        try:
            # Log start
            logger.info(f"Starting Claude Code background worker for project {project_id}")
            logger.info(f"Project path: {project_path}")
            logger.info(f"Session name for tracking: {session_name}")

            # Step 1: Run fast wrapper for phases 1-2 (template setup)
            logger.info(f"Executing: python3 fast_wrapper.py {project_id} {project_path} '{project_name}' (template_id: {template_id})")

            # Build command args - use current Python interpreter and dynamic paths
            python_exe = sys.executable
            fast_wrapper_path = str(BACKEND_DIR / "fast_wrapper.py")
            cmd_args = [python_exe, fast_wrapper_path,
                       str(project_id), project_path, project_name, description or "", template_id or ""]

            # Add template_id if provided
            if template_id:
                cmd_args.append(template_id)

            # Pass environment variables for EMPTY_TEMPLATE_MODE
            import os
            env = os.environ.copy()
            env["EMPTY_TEMPLATE_MODE"] = os.getenv("EMPTY_TEMPLATE_MODE", "false")

            result = subprocess.run(
                cmd_args,
                capture_output=True,
                text=True,
                timeout=3600,  # 60 minutes total
                env=env  # Pass environment variables
            )

            if result.returncode != 0:
                logger.error(f"Fast wrapper failed for project {project_id}")
                logger.error(f"Return code: {result.returncode}")
                logger.error(f"Error output: {result.stderr[-500:]}")
                return

            logger.info(f"Fast wrapper completed successfully for project {project_id}")

            # Step 2: Run OpenClaw wrapper for phases 3-7 (infrastructure provisioning)
            logger.info(f"Executing: python3 openclaw_wrapper.py {project_id} {project_path} '{project_name}' (template_id: {template_id})")

            # Build command args - use current Python interpreter and dynamic paths
            openclaw_wrapper_path = str(BACKEND_DIR / "openclaw_wrapper.py")
            cmd_args = [python_exe, openclaw_wrapper_path,
                       str(project_id), project_path, project_name, description or "",
                       template_id or ""]

            result = subprocess.run(
                cmd_args,
                capture_output=True,
                text=True,
                timeout=3600  # 60 minutes total (10 min per task)
            )

            # Check result
            if result.returncode == 0:
                # Success (wrapper updates status internally)
                logger.info(f"Claude Code wrapper completed successfully for project {project_id}")
                logger.info(f"Output (last 2000 chars):\n{result.stdout[-2000:]}")
                logger.info(f"Full stdout length: {len(result.stdout)} characters")
            else:
                # Failure
                logger.error(f"Claude Code wrapper failed for project {project_id}")
                logger.error(f"Return code: {result.returncode}")
                logger.error(f"Error output: {result.stderr}")

                # Update project status to 'failed' in NEW DB session
                # (wrapper should handle this, but we double-check)
                try:
                    with get_db() as conn:
                        conn.execute(
                            "UPDATE projects SET status = 'failed' WHERE id = ?",
                            (project_id,)
                        )
                        conn.commit()
                        logger.info(f"Project {project_id} status updated to 'failed' (safety check)")
                except Exception as db_error:
                    logger.error(f"Failed to update project status: {db_error}")

        except subprocess.TimeoutExpired:
            # Timeout
            logger.error(f"Claude Code wrapper timeout for project {project_id}")

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
            logger.error(f"Claude Code wrapper worker error for project {project_id}: {e}")

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
            logger.info(f"Claude Code worker thread for project {project_id} finished")

    # Create and start thread
    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    logger.info(f"Background thread started for project {project_id}")

    return thread
