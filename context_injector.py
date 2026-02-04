"""
Context Injector module for Clawd Backend.
Handles project folder context injection and rule file registration for OpenClaw sessions.
"""

import os
from typing import Optional

from database import get_db


class ContextInjector:
    """Handles injection of project context and rules into OpenClaw sessions."""

    def __init__(self):
        """Initialize the context injector."""
        pass

    def get_project_folder_path(self, session_key: str) -> Optional[str]:
        """
        Get the project folder path for a given session.

        Args:
            session_key: Session key

        Returns:
            Absolute path to project folder, or None if not found
        """
        try:
            with get_db() as conn:
                # Join with projects table to get project_path
                result = conn.execute("""
                    SELECT p.project_path
                    FROM sessions s
                    JOIN projects p ON s.project_id = p.id
                    WHERE s.session_key = ?
                """, (session_key,)).fetchone()

                if result:
                    return result["project_path"]
                return None
        except Exception as e:
            print(f"Error getting project folder path: {e}")
            return None

    def read_rule_file(self, file_path: str) -> Optional[str]:
        """
        Read a rule file from the project folder.

        Args:
            file_path: Absolute path to the rule file

        Returns:
            File contents as string, or None if file doesn't exist or can't be read
        """
        try:
            if not os.path.exists(file_path):
                return None

            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            print(f"Error reading rule file {file_path}: {e}")
            return None

    def build_project_context_message(self, project_path: str) -> dict:
        """
        Build a system message containing the project folder path.

        This message provides context about the workspace directory.

        Args:
            project_path: Absolute path to project folder

        Returns:
            Dictionary representing a system message
        """
        content = f"Project folder path: {project_path}"
        return {
            "role": "system",
            "content": content
        }

    def load_and_register_rules(self, project_path: str) -> list[dict]:
        """
        Load rule files from project folder and build system messages.

        This loads changerule.md and rule.md (if present) and converts them
        to system messages for registration.

        Args:
            project_path: Absolute path to project folder

        Returns:
            List of system message dictionaries
        """
        system_messages = []

        # Load changerule.md (required)
        changerule_path = os.path.join(project_path, "changerule.md")
        changerule_content = self.read_rule_file(changerule_path)
        if changerule_content:
            system_messages.append({
                "role": "system",
                "content": changerule_content
            })

        # Load rule.md (optional)
        rule_path = os.path.join(project_path, "rule.md")
        rule_content = self.read_rule_file(rule_path)
        if rule_content:
            system_messages.append({
                "role": "system",
                "content": rule_content
            })

        return system_messages

    def inject_system_context(self, session_key: str, user_messages: list[dict]) -> list[dict]:
        """
        Inject system context (project path + rules) into message array.

        This prepends system messages to the user's messages before sending to OpenClaw.
        The system context includes:
        1. Project folder path (always injected)
        2. Rules from changerule.md and rule.md (if present)

        Note: This context is invisible to the user and UI - it's server-side injection.

        Args:
            session_key: Session key
            user_messages: List of user messages (from request)

        Returns:
            List of messages with system context prepended
        """
        # Get project folder path
        project_path = self.get_project_folder_path(session_key)
        if not project_path:
            # No project context available, return user messages as-is
            return user_messages

        # Build system messages
        system_messages = []

        # Add project folder path context
        system_messages.append(self.build_project_context_message(project_path))

        # Load and add rules from project folder
        rule_messages = self.load_and_register_rules(project_path)
        system_messages.extend(rule_messages)

        # Prepend system messages to user messages
        # This ensures the context is available for the session
        return system_messages + user_messages
