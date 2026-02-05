"""
Context Injector module for Clawd Backend.
Handles project folder context injection and rule file registration for OpenClaw sessions.
"""

import os
import logging
from typing import Optional
from functools import lru_cache

from database import get_db

# Configure logging
logger = logging.getLogger(__name__)

# Configuration
PROJECT_BASE_PATH = "/var/lib/openclaw/projects"
RULE_FILE_MAX_SIZE = 1024 * 50  # 50KB
RULE_FILE_MAX_READ_SIZE = 1024 * 100  # 100KB

# Rule files to load (configurable)
RULE_FILES = ["changerule.md", "rule.md"]


class ContextInjector:
    """Handles injection of project context and rules into OpenClaw sessions.

    Uses singleton pattern to avoid duplicate instances and caching.
    """

    _instance = None

    def __new__(cls):
        """Singleton pattern to ensure only one instance exists."""
        if cls._instance is None:
            cls._instance = super(ContextInjector, cls).__new__(cls)
            cls._instance._rule_cache = {}
            cls._instance._cache_lock = True  # Enable caching by default
        return cls._instance

    def __init__(self):
        """Initialize the context injector (singleton)."""
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        self._rule_cache = {}
        self._cache_lock = True
        logger.info("ContextInjector initialized (singleton)")

    def _get_cache_key(self, project_path: str) -> str:
        """Generate a cache key for a project path."""
        return project_path

    def _get_current_mtime(self, project_path: str) -> float:
        """Get the most recent modification time of rule files."""
        mtime = 0.0
        for rule_file in RULE_FILES:
            rule_path = os.path.join(project_path, rule_file)
            if os.path.exists(rule_path):
                file_mtime = os.path.getmtime(rule_path)
                mtime = max(mtime, file_mtime)
        return mtime

    def _are_files_valid(self, project_path: str, cached_mtime: float) -> bool:
        """Check if cached rules are still valid (files haven't been modified)."""
        current_mtime = self._get_current_mtime(project_path)
        return current_mtime <= cached_mtime

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
                    SELECT p.project_path, p.name as project_name, p.id as project_id
                    FROM sessions s
                    JOIN projects p ON s.project_id = p.id
                    WHERE s.session_key = ?
                """, (session_key,)).fetchone()

                if result:
                    path = result["project_path"]
                    project_id = result["project_id"]

                    # Validate project actually has a path
                    if not path:
                        logger.warning(f"Session {session_key} has no project path (project_id: {project_id})")
                        return None

                    return path

                logger.debug(f"Session {session_key} not found")
                return None

        except Exception as e:
            logger.error(f"Error getting project folder path for session {session_key}: {e}")
            return None

    def read_rule_file(self, file_path: str, project_root: str) -> Optional[str]:
        """
        Read a rule file from the project folder with security validation.

        Args:
            file_path: Absolute path to rule file
            project_root: Project root directory for validation

        Returns:
            File contents as string, or None if file doesn't exist, can't be read, or invalid
        """
        try:
            # Security: Resolve symlinks to their real paths
            real_path = os.path.realpath(file_path)

            # Security: Verify resolved path is within project directory
            real_project_root = os.path.realpath(project_root)
            if not real_path.startswith(real_project_root):
                logger.warning(f"Security: Path traversal attempt: {file_path} -> {real_path}")
                return None

            # Check if file exists
            if not os.path.exists(real_path):
                logger.debug(f"Rule file does not exist: {file_path}")
                return None

            # Security: Check file size limit
            file_size = os.path.getsize(real_path)
            if file_size > RULE_FILE_MAX_READ_SIZE:
                logger.warning(f"Security: Rule file too large: {file_path} ({file_size} bytes)")
                return None

            # Read file with proper encoding
            with open(real_path, 'r', encoding='utf-8') as f:
                content = f.read()

                # Security: Limit content size
                if len(content) > RULE_FILE_MAX_SIZE:
                    logger.warning(f"Security: Rule content too large, truncating: {file_path}")
                    return content[:RULE_FILE_MAX_SIZE]

                logger.debug(f"Successfully read rule file: {file_path} ({len(content)} chars)")
                return content

        except UnicodeDecodeError as e:
            logger.error(f"Unicode error reading rule file {file_path}: {e}")
            return None
        except PermissionError as e:
            logger.error(f"Permission denied reading rule file {file_path}: {e}")
            return None
        except OSError as e:
            logger.error(f"OS error reading rule file {file_path}: {e}")
            return None

    def build_project_context_message(self, project_path: str) -> Optional[dict]:
        """
        Build a system message containing the project folder path.

        Validates that the path exists and is a directory before returning.

        Args:
            project_path: Absolute path to project folder

        Returns:
            Dictionary representing a system message, or None if invalid
        """
        if not project_path:
            logger.warning("build_project_context_message: No project path provided")
            return None

        # Validate path exists
        if not os.path.exists(project_path):
            logger.error(f"Project path does not exist: {project_path}")
            return None

        # Validate path is a directory
        if not os.path.isdir(project_path):
            logger.error(f"Project path is not a directory: {project_path}")
            return None

        # Security: Validate path is within allowed directory
        real_path = os.path.realpath(project_path)
        allowed_path = os.path.realpath(PROJECT_BASE_PATH)
        if not real_path.startswith(allowed_path):
            logger.error(f"Security: Project path outside allowed directory: {project_path}")
            return None

        content = f"Project folder path: {project_path}"
        logger.debug(f"Built project context message: {project_path}")

        return {
            "role": "system",
            "content": content
        }

    def load_and_register_rules(self, project_path: str) -> list[dict]:
        """
        Load rule files from project folder and build system messages (with caching).

        This loads changerule.md and rule.md (if present) and converts them
        to system messages for registration.

        Args:
            project_path: Absolute path to project folder

        Returns:
            List of system message dictionaries
        """
        if not self._cache_lock:
            logger.debug("Caching disabled, loading from disk")
            return self._load_rules_from_disk(project_path)

        cache_key = self._get_cache_key(project_path)

        # Check if we have a valid cache
        if cache_key in self._rule_cache:
            cached_data = self._rule_cache[cache_key]
            # Verify cache is still valid (files haven't been modified)
            cache_mtime = cached_data.get('mtime', 0)
            if self._are_files_valid(project_path, cache_mtime):
                logger.debug(f"Using cached rules for: {project_path}")
                return cached_data['messages']

        # Load from disk
        logger.debug(f"Loading rules from disk: {project_path}")
        messages = self._load_rules_from_disk(project_path)

        # Cache the result
        self._rule_cache[cache_key] = {
            'messages': messages,
            'mtime': self._get_current_mtime(project_path)
        }

        return messages

    def _load_rules_from_disk(self, project_path: str) -> list[dict]:
        """Load rules from disk (internal method with security validation)."""
        system_messages = []

        for rule_file in RULE_FILES:
            rule_path = os.path.join(project_path, rule_file)
            rule_content = self.read_rule_file(rule_path, project_path)
            if rule_content:
                system_messages.append({
                    "role": "system",
                    "content": rule_content
                })
                logger.debug(f"Loaded rule file: {rule_file}")

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
            List of messages with system context prepended, or user_messages if no project context
        """
        logger.debug(f"Injecting context for session: {session_key}")

        # Get project folder path
        project_path = self.get_project_folder_path(session_key)
        if not project_path:
            # No project context available, return user messages as-is
            logger.debug(f"No project path found for session: {session_key}")
            return user_messages

        logger.debug(f"Project path: {project_path}")

        # Build system messages
        system_messages = []

        # Add project folder path context
        path_message = self.build_project_context_message(project_path)
        if path_message:
            system_messages.append(path_message)

        # Load and add rules from project folder (with caching)
        rule_messages = self.load_and_register_rules(project_path)
        system_messages.extend(rule_messages)

        logger.debug(f"Loaded {len(rule_messages)} rule messages")

        # Prepend system messages to user messages
        # This ensures the context is available for the session
        final_messages = system_messages + user_messages
        logger.debug(f"Final messages count: {len(final_messages)} (system: {len(system_messages)}, user: {len(user_messages)})")

        return final_messages

    def invalidate_cache(self, project_path: str):
        """Invalidate cache for a specific project (use after file modifications)."""
        cache_key = self._get_cache_key(project_path)
        if cache_key in self._rule_cache:
            del self._rule_cache[cache_key]
            logger.debug(f"Invalidated cache for: {project_path}")
