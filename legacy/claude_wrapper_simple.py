#!/usr/bin/env python3
"""
Claude Code Wrapper for DreamPilot Project Initialization - SIMPLIFIED VERSION.

This script:
- Starts Claude Code in project directory
- Sends initialization prompt
- Waits for Claude Code to complete
- Updates project status in database
- Handles errors gracefully

Usage:
    python3 claude_wrapper_simple.py <project_id> <project_path> <project_name> [description]
"""

import sys
import subprocess
import time
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


class ClaudeCodeWrapper:
    """Simplified wrapper for Claude Code sessions."""

    def __init__(self, project_id: int, project_path: str, project_name: str, description: str = None):
        self.project_id = project_id
        self.project_path = Path(project_path)
        self.project_name = project_name
        self.description = description or ""
        self.claude_process = None

    def build_prompt(self) -> str:
        """Build initialization prompt."""
        if self.description:
            return f"""Initialize website project. Project name: {self.project_name} Description: {self.description}

Follow DreamPilot rules from rule.md strictly.
Use template registry at /root/dreampilot/website/frontend/template-registry.json.
Select best frontend template.
Clone template repository.
Setup FastAPI backend.
Setup PostgreSQL database.
Configure environment variables.
Verify deployment."""
        else:
            return f"""Initialize website project. Project name: {self.project_name}

Follow DreamPilot rules from rule.md strictly.
Use template registry at /root/dreampilot/website/frontend/template-registry.json.
Select best frontend template.
Clone template repository.
Setup FastAPI backend.
Setup PostgreSQL database.
Configure environment variables.
Verify deployment."""

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

    def run(self):
        """Run Claude Code and wait for completion."""
        try:
            logger.info(f"🚀 Starting Claude Code for project {self.project_id}")
            logger.info(f"📁 Project path: {self.project_path}")
            logger.info(f"📝 Project name: {self.project_name}")
            logger.info(f"🔒 Permissions: SKIPPED")

            # Build prompt
            prompt = self.build_prompt()
            logger.info(f"📊 Prompt length: {len(prompt)} characters")

            # Start Claude Code with permission skip
            logger.info("🔨 Starting Claude Code with --allow-dangerously-skip-permissions")

            # Write prompt to temp file
            prompt_file = self.project_path / "init_prompt.txt"
            prompt_file.write_text(prompt)

            # Run Claude Code with the prompt file
            self.claude_process = subprocess.Popen(
                ["claude", "--allow-dangerously-skip-permissions", str(prompt_file)],
                cwd=self.project_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            logger.info("👀 Claude Code process started")
            logger.info("⏱️ Waiting for completion (up to 60 minutes)...")

            # Wait for completion with timeout
            try:
                return_code = self.claude_process.wait(timeout=3600)  # 60 minutes
                logger.info(f"🏁 Claude Code exited with code: {return_code}")

                if return_code == 0:
                    # Success - update status to ready
                    logger.info("✅ Claude Code completed successfully")
                    self.update_status("ready")
                else:
                    # Failure - update status to failed
                    logger.error(f"❌ Claude Code failed with code: {return_code}")

                    # Read stderr
                    if self.claude_process.stderr:
                        stderr = self.claude_process.stderr.read()
                        if stderr:
                            logger.error(f"❌ Claude Code stderr (last 500 chars): {stderr[:500]}")

                    self.update_status("failed")

            except subprocess.TimeoutExpired:
                logger.error("⏱️ Claude Code timed out (60 minutes)")
                self.update_status("failed")

        except Exception as e:
            logger.error(f"💥 Unexpected error: {e}")
            self.update_status("failed")

        finally:
            # Cleanup
            if self.claude_process and self.claude_process.poll() is None:
                logger.info("🧹 Terminating Claude Code process")
                self.claude_process.terminate()
                try:
                    self.claude_process.wait(timeout=10)
                except:
                    logger.warning("⚠️ Claude Code process did not terminate gracefully")
                    self.claude_process.kill()

            logger.info("🏁 Wrapper finished")


def main():
    """Main entry point."""
    if len(sys.argv) < 4:
        print("Usage: python3 claude_wrapper_simple.py <project_id> <project_path> <project_name> [description]")
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
    wrapper = ClaudeCodeWrapper(
        project_id=project_id,
        project_path=project_path,
        project_name=project_name,
        description=description
    )

    wrapper.run()


if __name__ == "__main__":
    main()
