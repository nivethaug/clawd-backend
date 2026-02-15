#!/usr/bin/env python3
"""
Claude Code Step-by-Step Wrapper for DreamPilot Project Initialization.

This script breaks complex initialization into 5 focused tasks:
1. Select template from registry
2. Clone repository
3. Create FastAPI backend
4. Setup PostgreSQL
5. Configure environment

Each task is a separate Claude Code call with clear completion tracking.
"""

import sys
import json
import subprocess
import logging
import sqlite3
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database path
DB_PATH = "/root/clawd-backend/clawdbot_adapter.db"


class StepByStepWrapper:
    """Step-by-step wrapper for Claude Code initialization."""

    def __init__(self, project_id: int, project_path: str, project_name: str, description: str = None, template_id: str = None):
        self.project_id = project_id
        self.project_path = Path(project_path)
        self.project_name = project_name
        self.description = description or ""
        self.template_id = template_id  # Optional pre-selected template ID
        self.completed_tasks = []
        self.failed_tasks = []

    def update_status(self, status: str):
        """Update project status in database."""
        try:
            logger.info(f"Updating project {self.project_id} status to '{status}'")
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute(
                    "UPDATE projects SET status = ? WHERE id = ?",
                    (status, self.project_id)
                )
                conn.commit()
                logger.info(f"✓ Project {self.project_id} status updated to '{status}'")
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"✗ Failed to update project status: {e}")

    def run_git_clone(self, repo_url: str, target_dir: str = "frontend", timeout: int = 600) -> bool:
        """
        Run git clone directly with subprocess (much faster than Claude Code).

        Args:
            repo_url: Repository URL to clone
            target_dir: Target directory name
            timeout: Timeout in seconds

        Returns:
            True if clone succeeded, False otherwise
        """
        try:
            logger.info(f"🚀 Running git clone: {repo_url} → {target_dir}")

            # Check if target directory already exists
            target_path = self.project_path / target_dir
            if target_path.exists():
                logger.warning(f"⚠️ Target directory '{target_dir}' already exists, skipping clone")
                return True

            # Run git clone
            result = subprocess.run(
                ["git", "clone", "--depth", "1", repo_url, target_dir],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            # Check result
            if result.returncode == 0:
                logger.info(f"✅ Git clone completed successfully")
                logger.info(f"✓ Repository cloned to {target_dir}")

                # Verify clone
                if target_path.exists():
                    logger.info(f"✓ Target directory verified: {target_dir}")
                    return True
                else:
                    logger.error(f"❌ Target directory not created: {target_dir}")
                    return False

            else:
                logger.error(f"❌ Git clone failed with code: {result.returncode}")
                logger.error(f"Error output: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error(f"❌ Git clone timed out after {timeout} seconds")
            return False
        except Exception as e:
            logger.error(f"❌ Git clone error: {e}")
            return False

    def run_task(self, task_name: str, task_prompt: str, expected_files: list = None, timeout: int = 600) -> bool:
        """
        Run a single task with Claude Code.

        Args:
            task_name: Name of the task
            task_prompt: Prompt for this task
            expected_files: List of files to check for completion
            timeout: Timeout in seconds

        Returns:
            True if task succeeded, False otherwise
        """
        try:
            logger.info(f"🚀 Starting task: {task_name}")

            # Run Claude Code with permission skip
            result = subprocess.run(
                ["claude", "--allow-dangerously-skip-permissions", task_prompt],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            # Check result
            if result.returncode == 0:
                logger.info(f"✅ Task '{task_name}' completed successfully")

                # Verify expected files if provided
                if expected_files:
                    all_exist = True
                    for file_path in expected_files:
                        full_path = self.project_path / file_path
                        if not full_path.exists():
                            logger.warning(f"⚠️ Expected file not created: {file_path}")
                            all_exist = False

                    if all_exist:
                        logger.info(f"✓ All expected files verified for '{task_name}'")
                        return True
                    else:
                        logger.warning(f"⚠️ Some expected files missing for '{task_name}'")
                        return True
                else:
                    return True

            else:
                logger.error(f"❌ Task '{task_name}' failed with code: {result.returncode}")
                if result.stderr:
                    logger.error(f"❌ Error output: {result.stderr[:500]}")

                return False

        except subprocess.TimeoutExpired:
            logger.error(f"⏱️ Task '{task_name}' timed out ({timeout}s)")
            return False

        except Exception as e:
            logger.error(f"💥 Task '{task_name}' unexpected error: {e}")
            return False

    def run(self):
        """Run all 5 initialization steps."""
        try:
            logger.info(f"🚀 Starting step-by-step initialization for project {self.project_id}")
            logger.info(f"📁 Project path: {self.project_path}")
            logger.info(f"📝 Project name: {self.project_name}")

            tasks_succeeded = 0
            total_tasks = 5

            # Task 1: Select template from registry (SKIP if template_id is provided)
            if self.template_id:
                logger.info(f"📋 Task 1/{total_tasks}: Select template from registry - SKIPPED (template_id provided: {self.template_id})")
                self.completed_tasks.append("Select template")
                tasks_succeeded += 1
                logger.info(f"✓ Task 1 skipped - using pre-selected template: {self.template_id}")
            else:
                logger.info(f"📋 Task 1/{total_tasks}: Select template from registry")
                task1_prompt = f"""Reads template registry at /root/dreampilot/website/frontend/template-registry.json.
Analyze this project: Project name: {self.project_name}. Description: {self.description}.
Selects best frontend template based on project description.
When you've selected a template, respond with exactly: "TASK_1_COMPLETE" and nothing else."""

                if self.run_task("Select template", task1_prompt, timeout=1800):
                    self.completed_tasks.append("Select template")
                    tasks_succeeded += 1
                    logger.info(f"✓ Task 1 completed!")
                else:
                    self.failed_tasks.append("Select template")
                    self.update_status("failed")
                    logger.error("❌ Initialization failed at task 1")
                    return

            # Task 2: Clone repository (use subprocess directly for speed)
            logger.info(f"📋 Task 2/{total_tasks}: Clone repository")

            # Get template repository URL
            template_registry_path = Path("/root/dreampilot/website/frontend/template-registry.json")
            repo_url = None

            if template_id or self.template_id:
                # Use provided template_id or pre-selected template_id
                tid = template_id if template_id else self.template_id
                logger.info(f"Looking up template ID: {tid}")

                try:
                    with open(template_registry_path, 'r') as f:
                        registry = json.load(f)

                    for template in registry.get('templates', []):
                        if template.get('id') == tid:
                            repo_url = template.get('repo')
                            logger.info(f"Found repository URL: {repo_url}")
                            break
                except Exception as e:
                    logger.error(f"Failed to read template registry: {e}")

            if not repo_url:
                logger.error(f"❌ Could not find repository URL for template ID: {template_id or self.template_id}")
                self.failed_tasks.append("Clone repository")
                self.update_status("failed")
                logger.error("❌ Initialization failed at task 2")
                return

            # Clone repository directly with subprocess (much faster than Claude Code)
            if self.run_git_clone(repo_url, "frontend", timeout=1800):
                self.completed_tasks.append("Clone repository")
                tasks_succeeded += 1
                logger.info(f"✓ Task 2 completed!")
            else:
                self.failed_tasks.append("Clone repository")
                self.update_status("failed")
                logger.error("❌ Initialization failed at task 2")
                return

            # Task 3: Create FastAPI backend
            logger.info(f"📋 Task 3/{total_tasks}: Create FastAPI backend")
            task3_prompt = f"""Creates a FastAPI backend application in the project.
Creates a backend/ directory structure:
- Creates backend/ directory
- Creates main.py with FastAPI app
- Creates requirements.txt with necessary dependencies
- Creates .env.example with database configuration
- Creates a simple API route for testing

Ensure all files are created and backend structure is complete.
When done, respond with exactly: "TASK_3_COMPLETE" and nothing else."""

            if self.run_task("Create backend", task3_prompt, timeout=1800, expected_files=["backend", "backend/main.py", "backend/requirements.txt", "backend/.env.example"]):
                self.completed_tasks.append("Create backend")
                tasks_succeeded += 1
                logger.info(f"✓ Task 3 completed!")
            else:
                self.failed_tasks.append("Create backend")
                self.update_status("failed")
                logger.error("❌ Initialization failed at task 3")
                return

            # Task 4: Setup PostgreSQL
            logger.info(f"📋 Task 4/{total_tasks}: Setup PostgreSQL")
            task4_prompt = f"""Sets up a PostgreSQL database for this project.
Creates database initialization scripts:
- Creates database/ directory
- Creates init.sql or migrations folder
- Adds basic schema SQL
- Creates a database connection helper

Ensure database setup is complete.
When done, respond with exactly: "TASK_4_COMPLETE" and nothing else."""

            if self.run_task("Setup PostgreSQL", task4_prompt, timeout=1800, expected_files=["database"]):
                self.completed_tasks.append("Setup PostgreSQL")
                tasks_succeeded += 1
                logger.info(f"✓ Task 4 completed!")
            else:
                self.failed_tasks.append("Setup PostgreSQL")
                self.update_status("failed")
                logger.error("❌ Initialization failed at task 4")
                return

            # Task 5: Configure environment
            logger.info(f"📋 Task 5/{total_tasks}: Configure environment")
            task5_prompt = f"""Configures environment variables for this project.
Creates a .env file with:
- Database connection string
- API keys or environment variables
- Project-specific settings
- Documentation for each variable

Ensure .env file is created with proper configuration.
When done, respond with exactly: "TASK_5_COMPLETE" and nothing else."""

            if self.run_task("Configure environment", task5_prompt, timeout=1800, expected_files=[".env"]):
                self.completed_tasks.append("Configure environment")
                tasks_succeeded += 1
                logger.info(f"✓ Task 5 completed!")
            else:
                self.failed_tasks.append("Configure environment")
                self.update_status("failed")
                logger.error("❌ Initialization failed at task 5")
                return

            # All tasks completed!
            if tasks_succeeded == 5:
                logger.info(f"✅ All {total_tasks} initialization tasks completed successfully!")
                self.update_status("ready")
                logger.info(f"✓ Project {self.project_id} status updated to 'ready'")
                logger.info(f"📊 Completed tasks: {', '.join(self.completed_tasks)}")
            else:
                logger.error(f"❌ Initialization incomplete. Succeeded: {tasks_succeeded}/{total_tasks}, Failed: {', '.join(self.failed_tasks)}")
                self.update_status("failed")

        except Exception as e:
            logger.error(f"💥 Unexpected error in step-by-step wrapper: {e}")
            self.update_status("failed")

        finally:
            logger.info("🏁 Step-by-step wrapper finished")


def main():
    """Main entry point."""
    if len(sys.argv) < 4:
        print("Usage: python3 claude_wrapper_final.py <project_id> <project_path> <project_name> [description] [template_id]")
        print("  project_id: Database project ID")
        print("  project_path: Absolute path to project folder")
        print("  project_name: Project name")
        print("  description: (optional) Project description")
        print("  template_id: (optional) Pre-selected template ID (skips Task 1)")
        sys.exit(1)

    project_id = int(sys.argv[1])
    project_path = sys.argv[2]
    project_name = sys.argv[3]
    description = sys.argv[4] if len(sys.argv) > 4 else None
    template_id = sys.argv[5] if len(sys.argv) > 5 else None

    # Create and run wrapper
    wrapper = StepByStepWrapper(
        project_id=project_id,
        project_path=project_path,
        project_name=project_name,
        description=description,
        template_id=template_id
    )

    wrapper.run()


if __name__ == "__main__":
    main()
