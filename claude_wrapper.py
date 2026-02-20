#!/usr/bin/env python3
"""
Claude Code Wrapper for DreamPilot Project Initialization.

This script:
- Starts Claude Code in interactive mode
- Sends initialization prompt
- Monitors for completion signals
- Updates project status in database
- Handles errors gracefully

Usage:
    python3 claude_wrapper.py <project_id> <project_path> <project_name> [description]
"""

import sys
import subprocess
import time
import logging
import sqlite3
import signal
import os
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database path
DB_PATH = "/root/clawd-backend/clawdbot_adapter.db"

# Completion keywords to watch for
COMPLETION_KEYWORDS = [
    "done",
    "complete",
    "finished",
    "successfully",
    "initialization complete",
    "project ready",
    "setup complete"
]


class ClaudeCodeWrapper:
    """Wrapper for Claude Code interactive sessions."""

    def __init__(self, project_id: int, project_path: str, project_name: str, description: str = None):
        self.project_id = project_id
        self.project_path = Path(project_path)
        self.project_name = project_name
        self.description = description or ""
        self.claude_process = None
        self.completed = False

    def build_prompt(self) -> str:
        """Build the initialization prompt."""
        if self.description:
            prompt = f"""Initialize website project. Project name: {self.project_name} Description: {self.description}

Follow DreamPilot rules from rule.md strictly.
Use template registry at /root/dreampilot/website/frontend/template-registry.json.
Select best frontend template.
Clone template repository.
Setup FastAPI backend.
Setup PostgreSQL database.
Configure environment variables.
Verify deployment.

When you are completely done, respond with: "INITIALIZATION COMPLETE" and nothing else."""
        else:
            prompt = f"""Initialize website project. Project name: {self.project_name}

Follow DreamPilot rules from rule.md strictly.
Use template registry at /root/dreampilot/website/frontend/template-registry.json.
Select best frontend template.
Clone template repository.
Setup FastAPI backend.
Setup PostgreSQL database.
Configure environment variables.
Verify deployment.

When you are completely done, respond with: "INITIALIZATION COMPLETE" and nothing else."""

        return prompt

    def update_status(self, status: str):
        """Update project status in database."""
        try:
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute(
                    "UPDATE projects SET status = ? WHERE id = ?",
                    (status, self.project_id)
                )
                conn.commit()
                logger.info(f"Project {self.project_id} status updated to '{status}'")
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"Failed to update project status: {e}")

    def is_complete(self, text: str) -> bool:
        """Check if Claude indicates completion."""
        text_lower = text.lower()

        # Check for explicit completion marker
        if "initialization complete" in text_lower:
            logger.info("Detected explicit completion marker: 'INITIALIZATION COMPLETE'")
            return True

        # Check for completion keywords
        for keyword in COMPLETION_KEYWORDS:
            if keyword in text_lower:
                logger.info(f"Detected completion keyword: '{keyword}'")
                return True

        return False

    def run(self):
        """Run Claude Code interactively and monitor for completion."""
        try:
            logger.info(f"Starting Claude Code wrapper for project {self.project_id}")
            logger.info(f"Project path: {self.project_path}")
            logger.info(f"Project name: {self.project_name}")

            # Build prompt
            prompt = self.build_prompt()

            # Start Claude Code with permission skip
            # Use --allow-dangerously-skip-permissions to avoid approval prompts
            # Use --continue to resume if needed, otherwise start fresh
            logger.info("Starting Claude Code with permissions skipped")

            self.claude_process = subprocess.Popen(
                ["claude", "--allow-dangerously-skip-permissions"],
                cwd=self.project_path,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
            )

            # Send the prompt
            self.claude_process.stdin.write(prompt + "\n")
            self.claude_process.stdin.flush()

            # Monitor output
            logger.info("Monitoring Claude Code output for completion signals...")

            # Read output lines
            full_output = []
            max_lines = 1000  # Safety limit
            line_count = 0

            while line_count < max_lines:
                try:
                    # Set timeout for reading (check every second)
                    self.claude_process.stdin.flush()

                    # Read line with timeout
                    # Note: readline() will block, so we need to be careful
                    # For now, let's use a non-blocking approach
                    line = self.claude_process.stdout.readline()

                    if not line and self.claude_process.poll() is not None:
                        # Process ended
                        logger.info("Claude Code process ended")
                        break

                    if line:
                        line_count += 1
                        full_output.append(line)

                        # Check for completion
                        if self.is_complete(line):
                            logger.info("Completion signal detected!")
                            self.completed = True
                            self.update_status("ready")
                            break

                        # Log every 50 lines
                        if line_count % 50 == 0:
                            logger.info(f"Read {line_count} lines from Claude Code output")

                except Exception as e:
                    logger.error(f"Error reading output: {e}")
                    break

            # Check process exit code
            return_code = self.claude_process.wait(timeout=30)

            if return_code == 0:
                if not self.completed:
                    # Process finished but no explicit completion signal
                    logger.info("Claude Code finished normally (no explicit completion)")
                    self.update_status("ready")
            else:
                # Process failed
                logger.error(f"Claude Code failed with exit code: {return_code}")

                # Read stderr
                _, stderr = self.claude_process.communicate()
                if stderr:
                    logger.error(f"Claude Code stderr: {stderr[-500:]}")

                self.update_status("failed")

        except subprocess.TimeoutExpired:
            logger.error("Claude Code timed out")
            self.update_status("failed")

        except Exception as e:
            logger.error(f"Unexpected error in Claude Code wrapper: {e}")
            self.update_status("failed")

        finally:
            # Cleanup
            if self.claude_process and self.claude_process.poll() is None:
                logger.info("Terminating Claude Code process")
                self.claude_process.terminate()
                try:
                    self.claude_process.wait(timeout=10)
                except:
                    logger.warning("Claude Code process did not terminate gracefully")
                    self.claude_process.kill()

            logger.info("Claude Code wrapper finished")


def main():
    """Main entry point."""
    if len(sys.argv) < 4:
        print("Usage: python3 claude_wrapper.py <project_id> <project_path> <project_name> [description]")
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
