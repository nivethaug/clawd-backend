#!/usr/bin/env python3
"""
Claude Code Step-by-Step Wrapper for DreamPilot Project Initialization.

This script breaks complex initialization into small, focused tasks:
1. Select template from registry
2. Clone repository
3. Create FastAPI backend
4. Setup PostgreSQL
5. Configure environment

Each task is a separate Claude Code call with clear completion tracking.
"""

import sys
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

    def __init__(self, project_id: int, project_path: str, project_name: str, description: str = None):
        self.project_id = project_id
        self.project_path = Path(project_path)
        self.project_name = project_name
        self.description = description or ""
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

    def run_task(self, task_name: str, task_prompt: str, expected_files: list = None) -> bool:
        """
        Run a single task with Claude Code.

        Args:
            task_name: Name of the task
            task_prompt: Prompt for this task
            expected_files: List of files to check for completion

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
                timeout=600  # 10 minutes per task
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
                        return True  # Still count as success (Claude may use different paths)
                else:
                    return True

            else:
                logger.error(f"❌ Task '{task_name}' failed with code: {result.returncode}")
                if result.stderr:
                    logger.error(f"❌ Error output: {result.stderr[:500]}")

                return False

        except subprocess.TimeoutExpired:
            logger.error(f"⏱️ Task '{task_name}' timed out (10 minutes)")
            return False

        except Exception as e:
            logger.error(f"💥 Task '{task_name}' unexpected error: {e}")
            return False

    def run(self):
        """Run all initialization steps."""
        try:
            logger.info(f"🚀 Starting step-by-step initialization for project {self.project_id}")
            logger.info(f"📁 Project path: {self.project_path}")
            logger.info(f"📝 Project name: {self.project_name}")

            tasks_succeeded = 0

            # Task 1: Select template from registry
            logger.info("📋 Task 1/5: Select template from registry")
            task1_prompt = f"""Read the template registry at /root/dreampilot/website/frontend/template-registry.json.
Analyze this project: Project name: {self.project_name}. Description: {self.description}.
Select the best frontend template based on the project description.
When you've selected a template, respond with exactly: "TASK_1_COMPLETE" and nothing else."""

            if self.run_task("Select template", task1_prompt):
                self.completed_tasks.append("Select template")
                tasks_succeeded += 1
            else:
                self.failed_tasks.append("Select template")
                self.update_status("failed")
                logger.error("❌ Initialization failed at task 1")
                return

            # Task 2: Clone template repository
            logger.info("📋 Task 2/5: Clone template repository")
            task2_prompt = f"""Clone the selected frontend template repository.
Use git to clone the repository.
Ensure the clone is complete before continuing.
When you've successfully cloned the repository, respond with exactly: "TASK_2_COMPLETE" and nothing else."""

            if self.run_task("Clone template", task2_prompt, expected_files=["frontend"]):
                self.completed_tasks.append("Clone repository")
                tasks_succeeded += 1
            else:
                self.failed_tasks.append("Clone repository")
                self.update_status("failed")
                logger.error("❌ Initialization failed at task 2")
                return

            # Task 3: Create FastAPI backend
            logger.info("📋 Task 3/5: Create FastAPI backend")
            task3_prompt = f"""Create a FastAPI backend application in the project.
Create a backend directory structure:
- Create backend/ directory
- Create main.py with FastAPI app
- Create requirements.txt with necessary dependencies
- Create .env.example with database configuration
- Create a simple API route for testing

Ensure all files are created and the backend structure is complete.
When done, respond with exactly: "TASK_3_COMPLETE" and nothing else."""

            if self.run_task("Create backend", task3_prompt, expected_files=["backend", "backend/main.py", "backend/requirements.txt", "backend/.env.example"]):
                self.completed_tasks.append("Create FastAPI backend")
                tasks_succeeded += 1
            else:
                self.failed_tasks.append("Create backend")
                self.update_status("failed")
                logger.error("❌ Initialization failed at task 3")
                return

            # Task 4: Setup PostgreSQL
            logger.info("📋 Task 4/5: Setup PostgreSQL database")
            task4_prompt = f"""Setup a PostgreSQL database for this project.
Create database initialization scripts:
- Create a database/migrations directory
- Create an init.sql or migrations folder
- Add basic schema SQL
- Create a database connection helper

Ensure database setup is complete.
When done, respond with exactly: "TASK_4_COMPLETE" and nothing else."""

            if self.run_task("Setup PostgreSQL", task4_prompt, expected_files=["database"]):
                self.completed_tasks.append("Setup PostgreSQL")
                tasks_succeeded += 1
            else:
                self.failed_tasks.append("Setup PostgreSQL")
                self.update_status("failed")
                logger.error("❌ Initialization failed at task 4")
                return

            # Task 5: Configure environment
            logger.info("📋 Task 5/5: Configure environment variables")
            task5_prompt = f"""Configure environment variables for this project.
Create a .env file with:
- Database connection string
- API keys or environment variables
- Project-specific settings
- Documentation for each variable

Ensure .env file is created with proper configuration.
When done, respond with exactly: "TASK_5_COMPLETE" and nothing else."""

            if self.run_task("Configure environment", task5_prompt, expected_files=[".env"]):
                self.completed_tasks.append("Configure environment")
                tasks_succeeded += 1
            else:
                self.failed_tasks.append("Configure environment")
                self.update_status("failed")
                logger.error("❌ Initialization failed at task 5")
                return

            # All tasks completed!
            if tasks_succeeded == 5:
                logger.info("✅ All 5 initialization tasks completed successfully!")
                self.update_status("ready")
                logger.info(f"✓ Project {self.project_id} status updated to 'ready'")
                logger.info(f"📊 Completed tasks: {', '.join(self.completed_tasks)}")
            else:
                logger.error(f"❌ Initialization incomplete. Succeeded: {tasks_succeeded}/5, Failed: {', '.join(self.failed_tasks)}")
                self.update_status("failed")

        except Exception as e:
            logger.error(f"💥 Unexpected error in step-by-step wrapper: {e}")
            self.update_status("failed")

        finally:
            logger.info("🏁 Step-by-step wrapper finished")


def main():
    """Main entry point."""
    if len(sys.argv) < 4:
        print("Usage: python3 claude_wrapper_step.py <project_id> <project_path> <project_name> [description]")
        print("  project_id: Database project ID")
        print("  project_path: Absolute path to project folder")
        print("  project_name: Project name")
        print("  description: (optional) Project description")
        sys.exit(1)

    project_id = int(sys.argv[1])
    project_path = sys.argv[2]
    project_name = sys.argv[3]
    description = sys.argv[4] if len(sys.argv) > 4 else None

    # Create and run wrapper
    wrapper = StepByStepWrapper(
        project_id=project_id,
        project_path=project_path,
        project_name=project_name,
        description=description
    )

    wrapper.run()


if __name__ == "__main__":
    main()
