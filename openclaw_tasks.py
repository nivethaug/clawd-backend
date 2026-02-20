"""
OpenClaw Task Runner

Uses OpenClaw's sessions_spawn to execute tasks via sub-agents
instead of calling Claude Code CLI via subprocess.

This is more reliable and avoids subprocess permission issues.
"""

import sys
import logging
import sqlite3
import json
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database path
DB_PATH = "/root/clawd-backend/clawdbot_adapter.db"


class OpenClawTaskRunner:
    """Task runner using OpenClaw sub-agents."""

    def __init__(self, project_id: int, project_path: str, project_name: str):
        self.project_id = project_id
        self.project_path = Path(project_path)
        self.project_name = project_name
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

    def run_task_via_subagent(self, task_name: str, task_prompt: str, expected_files: list = None) -> bool:
        """
        Run a task using OpenClaw sub-agent.

        Args:
            task_name: Name of the task
            task_prompt: Prompt for this task
            expected_files: List of files to check for completion

        Returns:
            True if task succeeded, False otherwise
        """
        try:
            logger.info(f"🚀 Starting task: {task_name}")

            # Create task description for sub-agent
            full_task_prompt = f"""Project Context:
- Project ID: {self.project_id}
- Project Name: {self.project_name}
- Project Path: {self.project_path}

Task: {task_name}

{task_prompt}

IMPORTANT:
- Work in directory: {self.project_path}
- Verify your work before reporting completion
- Create all necessary files and directories"""

            # In a real implementation, we would use sessions_spawn here
            # For now, we'll simulate it with a note
            logger.warning(f"⚠️ OpenClaw sessions_spawn not yet implemented")
            logger.warning(f"⚠️ Task prompt would be: {task_name}")
            logger.warning(f"⚠️ This requires OpenClaw integration")

            # For now, return False (not implemented)
            return False

        except Exception as e:
            logger.error(f"💥 Task '{task_name}' unexpected error: {e}")
            return False

    def run_backend_setup(self) -> bool:
        """Run backend setup task."""
        task_prompt = """Create a FastAPI backend application in the project.

Create a backend/ directory structure:
- Creates backend/ directory
- Creates main.py with FastAPI app
- Creates requirements.txt with necessary dependencies:
  - fastapi
  - uvicorn
  - sqlalchemy
  - pydantic
  - python-dotenv
- Creates .env.example with database configuration:
  - DATABASE_URL=postgresql://user:password@localhost/dbname
  - SECRET_KEY=your-secret-key-here
- Creates a simple API route for testing:
  - GET /health - returns {"status": "ok"}

Ensure all files are created and backend structure is complete."""

        return self.run_task_via_subagent(
            "Create backend",
            task_prompt,
            expected_files=["backend", "backend/main.py", "backend/requirements.txt", "backend/.env.example"]
        )

    def run_database_setup(self) -> bool:
        """Run database setup task."""
        task_prompt = """Sets up a PostgreSQL database for this project.

Create database initialization scripts:
- Creates database/ directory
- Creates init.sql with basic schema:
  - users table (id, name, email, created_at)
  - projects table (id, name, description, created_at)
  - Basic indexes
- Creates database connection helper:
  - Creates database/connection.py with SQLAlchemy setup
  - Includes Base model class
  - Includes get_db() function

Ensure database setup is complete."""

        return self.run_task_via_subagent(
            "Setup PostgreSQL",
            task_prompt,
            expected_files=["database"]
        )

    def run_environment_config(self) -> bool:
        """Run environment configuration task."""
        task_prompt = """Configures environment variables for this project.

Create a .env file with:
- Database connection string
- API keys or environment variables
- Project-specific settings
- Documentation for each variable

Example .env:
```
# Database
DATABASE_URL=postgresql://user:password@localhost/dbname

# API
API_HOST=0.0.0.0
API_PORT=8000
DEBUG=False

# Security
SECRET_KEY=your-secret-key-here
```

Ensure .env file is created with proper configuration."""

        return self.run_task_via_subagent(
            "Configure environment",
            task_prompt,
            expected_files=[".env"]
        )

    def run_all_tasks(self):
        """Run all tasks sequentially."""
        try:
            logger.info(f"🚀 Starting OpenClaw task runner for project {self.project_id}")
            logger.info(f"📁 Project path: {self.project_path}")
            logger.info(f"📝 Project name: {self.project_name}")

            total_tasks = 3
            tasks_succeeded = 0

            # Task 1: Create backend
            logger.info(f"📋 Task 1/{total_tasks}: Create FastAPI backend")
            if self.run_backend_setup():
                self.completed_tasks.append("Create backend")
                tasks_succeeded += 1
                logger.info(f"✓ Task 1 completed!")
            else:
                self.failed_tasks.append("Create backend")
                self.update_status("failed")
                logger.error("❌ Initialization failed at task 1")
                return

            # Task 2: Setup database
            logger.info(f"📋 Task 2/{total_tasks}: Setup PostgreSQL")
            if self.run_database_setup():
                self.completed_tasks.append("Setup PostgreSQL")
                tasks_succeeded += 1
                logger.info(f"✓ Task 2 completed!")
            else:
                self.failed_tasks.append("Setup PostgreSQL")
                self.update_status("failed")
                logger.error("❌ Initialization failed at task 2")
                return

            # Task 3: Configure environment
            logger.info(f"📋 Task 3/{total_tasks}: Configure environment")
            if self.run_environment_config():
                self.completed_tasks.append("Configure environment")
                tasks_succeeded += 1
                logger.info(f"✓ Task 3 completed!")
            else:
                self.failed_tasks.append("Configure environment")
                self.update_status("failed")
                logger.error("❌ Initialization failed at task 3")
                return

            # All tasks completed!
            if tasks_succeeded == 3:
                logger.info(f"✅ All {total_tasks} initialization tasks completed successfully!")
                self.update_status("ready")
                logger.info(f"✓ Project {self.project_id} status updated to 'ready'")
                logger.info(f"📊 Completed tasks: {', '.join(self.completed_tasks)}")
            else:
                logger.error(f"❌ Initialization incomplete. Succeeded: {tasks_succeeded}/{total_tasks}, Failed: {', '.join(self.failed_tasks)}")
                self.update_status("failed")

        except Exception as e:
            logger.error(f"💥 Unexpected error in OpenClaw task runner: {e}")
            self.update_status("failed")

        finally:
            logger.info("🏁 OpenClaw task runner finished")


def main():
    """Main entry point."""
    if len(sys.argv) < 4:
        print("Usage: python3 openclaw_tasks.py <project_id> <project_path> <project_name>")
        print("  project_id: Database project ID")
        print("  project_path: Absolute path to project folder")
        print("  project_name: Project name")
        sys.exit(1)

    project_id = int(sys.argv[1])
    project_path = sys.argv[2]
    project_name = sys.argv[3]

    # Create and run task runner
    runner = OpenClawTaskRunner(
        project_id=project_id,
        project_path=project_path,
        project_name=project_name
    )

    runner.run_all_tasks()


if __name__ == "__main__":
    main()
