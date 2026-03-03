#!/usr/bin/env python3
"""
ACP Controlled Frontend Editor Module

Implements safe, validated frontend editing for Phase 8 projects with:
- Path validation (whitelist src/, forbid backend, forbid components/ui/)
- File limit (max 4 new files per execution)
- Snapshot system (backup before modifications)
- Rollback (restore on validation/build failure)
- Build gate (npm install && npm run build)
- Mutation logging (track all changes)
"""

import os
import re
import json
import shutil
import subprocess
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

# Allowed paths
ALLOWED_PROJECTS_BASE = "/root/dreampilot/projects/website"
FORBIDDEN_BACKEND = "/root/clawd-backend"
FORBIDDEN_UI_COMPONENTS = "components/ui"

# File limits
MAX_NEW_FILES = 4

# Build settings
BUILD_TIMEOUT = 300  # 5 minutes

# =============================================================================
# PATH VALIDATION
# =============================================================================

class ACPPathValidator:
    """Validates all file paths for ACP frontend editing."""

    def __init__(self, frontend_src_path: str):
        """
        Initialize validator with project's frontend src path.

        Args:
            frontend_src_path: Absolute path to frontend/src directory
        """
        self.frontend_src_path = Path(frontend_src_path).resolve()
        self.ui_components_path = self.frontend_src_path / "components" / "ui"

        # Ensure paths exist
        if not self.frontend_src_path.exists():
            raise ValueError(f"Frontend src path does not exist: {frontend_src_path}")

    def is_path_allowed(self, file_path: str) -> Tuple[bool, str]:
        """
        Check if a file path is allowed for modification.

        Args:
            file_path: Absolute or relative file path

        Returns:
            Tuple of (is_allowed, reason)
        """
        # Normalize path - resolve relative paths to frontend_src_path
        path = Path(file_path)
        if not path.is_absolute():
            # Relative path: resolve it relative to frontend_src_path
            path = (self.frontend_src_path / file_path).resolve()
        else:
            # Absolute path: normalize it
            path = path.resolve()

        # Check 1: Forbidden backend path
        try:
            if FORBIDDEN_BACKEND in str(path) or str(path).startswith(FORBIDDEN_BACKEND):
                return False, f"Forbidden: Cannot modify backend files ({path})"
        except (ValueError, RuntimeError):
            # Handle case where relative path goes above root
            return False, f"Forbidden: Invalid path ({path})"

        # Check 2: Must be inside frontend/src
        try:
            path.relative_to(self.frontend_src_path)
        except ValueError:
            return False, f"Forbidden: Path outside frontend/src ({path})"

        # Check 3: Forbidden UI components directory
        try:
            if self.ui_components_path.exists():
                path.relative_to(self.ui_components_path)
                return False, f"Forbidden: Cannot modify components/ui/ ({path})"
        except ValueError:
            # Path is not inside components/ui, which is good
            pass

        # Check 4: Must be inside src directory (not parent directories)
        # Normalize both paths for comparison
        try:
            path_str = str(path)
            src_str = str(self.frontend_src_path)
            if not path_str.startswith(src_str):
                return False, f"Forbidden: Path must be inside frontend/src ({path})"
        except Exception as e:
            return False, f"Forbidden: Path validation error ({e})"

        # All checks passed
        return True, "Allowed"

    def validate_paths(self, file_paths: List[str]) -> Tuple[bool, List[str]]:
        """
        Validate multiple file paths.

        Args:
            file_paths: List of file paths to validate

        Returns:
            Tuple of (all_valid, error_messages)
        """
        errors = []
        for file_path in file_paths:
            logger.info(f"[ACP] Validating path: '{file_path}'")
            allowed, reason = self.is_path_allowed(file_path)
            logger.info(f"[ACP]   Result: allowed={allowed}, reason='{reason}'")
            if not allowed:
                errors.append(reason)

        return len(errors) == 0, errors

    def is_ui_component_file(self, file_path: str) -> bool:
        """
        Check if file is inside components/ui directory.

        Args:
            file_path: File path to check

        Returns:
            True if file is inside components/ui/
        """
        try:
            path = Path(file_path).resolve()
            path.relative_to(self.ui_components_path)
            return True
        except ValueError:
            return False


# =============================================================================
# SNAPSHOT MANAGER
# =============================================================================

class ACPSnapshotManager:
    """Manages snapshot creation and restoration for frontend editing."""

    def __init__(self, frontend_path: str):
        """
        Initialize snapshot manager.

        Args:
            frontend_path: Absolute path to frontend directory
        """
        self.frontend_path = Path(frontend_path).resolve()
        self.backup_dir = self.frontend_path.parent / f"frontend_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def create_snapshot(self) -> Tuple[bool, str]:
        """
        Create a full backup of the frontend directory.

        Returns:
            Tuple of (success, backup_path_or_error)
        """
        try:
            logger.info(f"Creating snapshot at {self.backup_dir}")

            # Create backup directory
            self.backup_dir.mkdir(parents=True, exist_ok=True)

            # Copy entire frontend directory
            if self.frontend_path.exists():
                shutil.copytree(
                    self.frontend_path,
                    self.backup_dir / "frontend",
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(
                        'node_modules',
                        '.git',
                        'dist',
                        'build',
                        '*.log'
                    )
                )
            else:
                # If frontend doesn't exist, create empty backup
                (self.backup_dir / "frontend").mkdir(parents=True)

            logger.info(f"Snapshot created successfully")
            return True, str(self.backup_dir)

        except Exception as e:
            logger.error(f"Failed to create snapshot: {e}")
            return False, str(e)

    def restore_snapshot(self) -> Tuple[bool, str]:
        """
        Restore frontend from snapshot.

        Returns:
            Tuple of (success, message)
        """
        try:
            if not self.backup_dir.exists():
                return False, "Snapshot backup directory not found"

            backup_frontend = self.backup_dir / "frontend"

            if not backup_frontend.exists():
                return False, "Frontend backup not found in snapshot"

            # Remove existing frontend directory
            if self.frontend_path.exists():
                shutil.rmtree(self.frontend_path)

            # Restore from backup
            shutil.copytree(backup_frontend, self.frontend_path)

            logger.info(f"Restored snapshot from {self.backup_dir}")
            return True, "Snapshot restored successfully"

        except Exception as e:
            logger.error(f"Failed to restore snapshot: {e}")
            return False, str(e)

    def cleanup_snapshot(self) -> bool:
        """
        Remove snapshot directory after successful changes.

        Returns:
            True if cleanup successful
        """
        try:
            if self.backup_dir.exists():
                shutil.rmtree(self.backup_dir)
                logger.info(f"Cleaned up snapshot at {self.backup_dir}")
            return True
        except Exception as e:
            logger.error(f"Failed to cleanup snapshot: {e}")
            return False


# =============================================================================
# MUTATION LOGGER
# =============================================================================

class ACPMutationLogger:
    """Logs all mutations made during ACP frontend editing."""

    def __init__(self, frontend_path: str):
        """
        Initialize mutation logger.

        Args:
            frontend_path: Absolute path to frontend directory
        """
        self.frontend_path = Path(frontend_path).resolve()
        self.log_file = self.frontend_path / ".acp_mutation_log.json"

    def create_log_entry(self, execution_id: str) -> Dict[str, Any]:
        """
        Create a new log entry for this ACP execution.

        Args:
            execution_id: Unique ID for this execution

        Returns:
            Log entry dictionary
        """
        return {
            "execution_id": execution_id,
            "timestamp": datetime.now().isoformat(),
            "files_added": [],
            "files_modified": [],
            "files_removed": [],
            "build_result": None,
            "rollback_status": None,
            "status": "in_progress"
        }

    def save_log(self, log_entry: Dict[str, Any]) -> bool:
        """
        Save log entry to mutation log file.

        Args:
            log_entry: Log entry dictionary

        Returns:
            True if save successful
        """
        try:
            # Read existing logs or create new
            logs = []
            if self.log_file.exists():
                try:
                    with open(self.log_file, 'r') as f:
                        logs = json.load(f)
                except json.JSONDecodeError:
                    logs = []

            # Append new log
            logs.append(log_entry)

            # Write back
            with open(self.log_file, 'w') as f:
                json.dump(logs, f, indent=2)

            return True

        except Exception as e:
            logger.error(f"Failed to save mutation log: {e}")
            return False

    def log_file_added(self, log_entry: Dict[str, Any], file_path: str) -> None:
        """Log a file being added."""
        log_entry["files_added"].append(file_path)

    def log_file_modified(self, log_entry: Dict[str, Any], file_path: str) -> None:
        """Log a file being modified."""
        log_entry["files_modified"].append(file_path)

    def log_file_removed(self, log_entry: Dict[str, Any], file_path: str) -> None:
        """Log a file being removed."""
        log_entry["files_removed"].append(file_path)

    def update_build_result(self, log_entry: Dict[str, Any], success: bool, output: str = "") -> None:
        """Update build result in log."""
        log_entry["build_result"] = {
            "success": success,
            "output": output[:1000] if output else "",  # Limit output size
            "timestamp": datetime.now().isoformat()
        }

    def update_rollback_status(self, log_entry: Dict[str, Any], rolled_back: bool, reason: str = "") -> None:
        """Update rollback status in log."""
        log_entry["rollback_status"] = {
            "rolled_back": rolled_back,
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        }

    def finalize_status(self, log_entry: Dict[str, Any], status: str) -> None:
        """Finalize log entry status."""
        log_entry["status"] = status
        log_entry["completed_at"] = datetime.now().isoformat()


# =============================================================================
# FILE OPERATIONS
# =============================================================================

class ACPFileOperations:
    """Handles file operations with validation."""

    def __init__(self, validator: ACPPathValidator, logger_obj: ACPMutationLogger):
        """
        Initialize file operations.

        Args:
            validator: Path validator instance
            logger_obj: Mutation logger instance
        """
        self.validator = validator
        self.logger = logger_obj
        self._new_files_count = 0

    def write_file(self, file_path: str, content: str, log_entry: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Write a file with validation.

        Args:
            file_path: Path to file
            content: File content
            log_entry: Log entry to update

        Returns:
            Tuple of (success, message)
        """
        # Validate path
        allowed, reason = self.validator.is_path_allowed(file_path)
        if not allowed:
            return False, reason

        # Resolve path the same way as is_path_allowed (relative paths resolve to frontend_src_path)
        path = Path(file_path)
        if not path.is_absolute():
            path = (self.validator.frontend_src_path / file_path).resolve()
        else:
            path = path.resolve()

        # Check file limit for new files
        if not path.exists():
            if self._new_files_count >= MAX_NEW_FILES:
                return False, f"File limit exceeded: max {MAX_NEW_FILES} new files allowed"

            self._new_files_count += 1
            self.logger.log_file_added(log_entry, file_path)
        else:
            self.logger.log_file_modified(log_entry, file_path)

        # Create parent directories if needed
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True, f"File written: {file_path}"
        except Exception as e:
            return False, f"Failed to write file: {e}"

    def remove_file(self, file_path: str, log_entry: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Remove a file with validation.

        Args:
            file_path: Path to file
            log_entry: Log entry to update

        Returns:
            Tuple of (success, message)
        """
        # Validate path
        allowed, reason = self.validator.is_path_allowed(file_path)
        if not allowed:
            return False, reason

        # Resolve path the same way as is_path_allowed (relative paths resolve to frontend_src_path)
        path = Path(file_path)
        if not path.is_absolute():
            path = (self.validator.frontend_src_path / file_path).resolve()
        else:
            path = path.resolve()

        # Check if file exists
        if not path.exists():
            return False, f"File not found: {file_path}"

        # Remove file
        try:
            path.unlink()
            self.logger.log_file_removed(log_entry, file_path)
            return True, f"File removed: {file_path}"
        except Exception as e:
            return False, f"Failed to remove file: {e}"

    def get_new_files_count(self) -> int:
        """Get count of new files created."""
        return self._new_files_count

    def validate_file_limit(self) -> bool:
        """Check if file limit is within allowed range."""
        return self._new_files_count <= MAX_NEW_FILES


# =============================================================================
# BUILD GATE
# =============================================================================

class ACPBuildGate:
    """Handles build validation after frontend changes."""

    def __init__(self, frontend_path: str):
        """
        Initialize build gate.

        Args:
            frontend_path: Absolute path to frontend directory
        """
        self.frontend_path = Path(frontend_path).resolve()
        self.package_json_path = self.frontend_path / "package.json"

    def validate_environment(self) -> Tuple[bool, str]:
        """
        Validate that the environment is ready for building.

        Returns:
            Tuple of (is_valid, message)
        """
        if not self.package_json_path.exists():
            return False, "package.json not found"

        # Check for npm
        try:
            result = subprocess.run(
                ["npm", "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                return False, "npm not found or not working"
        except Exception as e:
            return False, f"Failed to check npm: {e}"

        return True, "Environment valid"

    def run_build(self) -> Tuple[bool, str]:
        """
        Run npm install and npm run build.

        Returns:
            Tuple of (success, output)
        """
        # Validate environment first
        valid, message = self.validate_environment()
        if not valid:
            return False, f"Environment validation failed: {message}"

        output = []
        output.append("=== Starting Build Process ===")
        output.append(f"Working directory: {self.frontend_path}")

        try:
            # Step 1: npm install
            output.append("\n--- Running npm install ---")
            result = subprocess.run(
                ["npm", "install"],
                cwd=self.frontend_path,
                capture_output=True,
                text=True,
                timeout=BUILD_TIMEOUT
            )

            output.append(result.stdout)
            if result.stderr:
                output.append("STDERR: " + result.stderr)

            if result.returncode != 0:
                output.append(f"npm install failed with code {result.returncode}")
                return False, "\n".join(output)

            output.append("npm install completed successfully")

            # Step 2: npm run build
            output.append("\n--- Running npm run build ---")
            result = subprocess.run(
                ["npm", "run", "build"],
                cwd=self.frontend_path,
                capture_output=True,
                text=True,
                timeout=BUILD_TIMEOUT
            )

            output.append(result.stdout)
            if result.stderr:
                output.append("STDERR: " + result.stderr)

            if result.returncode != 0:
                output.append(f"npm run build failed with code {result.returncode}")
                return False, "\n".join(output)

            output.append("npm run build completed successfully")
            output.append("=== Build Process Complete ===")

            return True, "\n".join(output)

        except subprocess.TimeoutExpired:
            output.append(f"Build timeout after {BUILD_TIMEOUT} seconds")
            return False, "\n".join(output)
        except Exception as e:
            output.append(f"Build error: {e}")
            return False, "\n".join(output)


# =============================================================================
# MAIN ACP EDITOR
# =============================================================================

class ACPFrontendEditor:
    """
    Main ACP Frontend Editor orchestrates the entire editing process.

    Workflow:
    1. Create snapshot
    2. Validate all paths
    3. Apply changes ( respecting file limit )
    4. Run build gate
    5. On failure: rollback and log
    6. On success: cleanup snapshot and log
    """

    def __init__(self, frontend_src_path: str, project_name: str):
        """
        Initialize ACP Frontend Editor.

        Args:
            frontend_src_path: Absolute path to frontend/src directory
            project_name: Name of the project for logging
        """
        self.frontend_src_path = Path(frontend_src_path).resolve()
        self.frontend_path = self.frontend_src_path.parent
        self.project_name = project_name

        # Initialize components
        self.validator = ACPPathValidator(frontend_src_path)
        self.snapshot_manager = ACPSnapshotManager(str(self.frontend_path))
        self.mutation_logger = ACPMutationLogger(str(self.frontend_path))
        self.file_ops = ACPFileOperations(self.validator, self.mutation_logger)
        self.build_gate = ACPBuildGate(str(self.frontend_path))

    def apply_changes(
        self,
        changes: List[Dict[str, Any]],
        execution_id: str
    ) -> Dict[str, Any]:
        """
        Apply a set of changes to the frontend.

        Args:
            changes: List of change dictionaries with keys:
                - action: 'write', 'remove', or 'modify'
                - path: file path
                - content: file content (for write/modify)
            execution_id: Unique ID for this execution

        Returns:
            Result dictionary with keys:
                - success: bool
                - message: str
                - files_modified: int
                - files_added: int
                - files_removed: int
                - build_output: str
                - rollback: bool
        """
        # Create log entry
        log_entry = self.mutation_logger.create_log_entry(execution_id)

        # Step 1: Create snapshot
        snapshot_success, snapshot_msg = self.snapshot_manager.create_snapshot()
        if not snapshot_success:
            log_entry["status"] = "snapshot_failed"
            self.mutation_logger.save_log(log_entry)
            return {
                "success": False,
                "message": f"Snapshot creation failed: {snapshot_msg}",
                "rollback": False
            }

        logger.info(f"Snapshot created: {snapshot_msg}")

        # Step 2: Validate all paths first
        all_paths = [c["path"] for c in changes]
        valid, errors = self.validator.validate_paths(all_paths)

        if not valid:
            # Rollback immediately on validation failure
            self.snapshot_manager.restore_snapshot()
            self.snapshot_manager.cleanup_snapshot()

            log_entry["status"] = "validation_failed"
            self.mutation_logger.update_rollback_status(log_entry, True, "Path validation failed")
            self.mutation_logger.finalize_status(log_entry, "validation_failed")
            self.mutation_logger.save_log(log_entry)

            return {
                "success": False,
                "message": "Path validation failed",
                "errors": errors,
                "rollback": True
            }

        # Step 3: Count potential new files
        new_file_count = sum(
            1 for c in changes
            if c.get("action") in ("write", "modify")
            and not Path(c["path"]).exists()
        )

        if new_file_count > MAX_NEW_FILES:
            # Rollback on file limit violation
            self.snapshot_manager.restore_snapshot()
            self.snapshot_manager.cleanup_snapshot()

            log_entry["status"] = "file_limit_exceeded"
            self.mutation_logger.update_rollback_status(
                log_entry,
                True,
                f"File limit exceeded: {new_file_count} > {MAX_NEW_FILES}"
            )
            self.mutation_logger.finalize_status(log_entry, "file_limit_exceeded")
            self.mutation_logger.save_log(log_entry)

            return {
                "success": False,
                "message": f"File limit exceeded: {new_file_count} new files, max {MAX_NEW_FILES} allowed",
                "rollback": True
            }

        # Step 4: Apply changes
        files_added = 0
        files_modified = 0
        files_removed = 0

        for change in changes:
            action = change.get("action")
            path = change.get("path")
            content = change.get("content", "")

            try:
                if action in ("write", "modify"):
                    success, msg = self.file_ops.write_file(path, content, log_entry)
                    if success:
                        if "written" in msg and path not in log_entry["files_modified"]:
                            # Check if it was added or modified
                            if "added" in str(log_entry["files_added"][-1:] if log_entry["files_added"] else []):
                                files_added += 1
                            else:
                                files_modified += 1
                    else:
                        raise Exception(msg)

                elif action == "remove":
                    success, msg = self.file_ops.remove_file(path, log_entry)
                    if success:
                        files_removed += 1
                    else:
                        raise Exception(msg)

                else:
                    raise Exception(f"Unknown action: {action}")

            except Exception as e:
                # Rollback on any error
                self.snapshot_manager.restore_snapshot()
                self.snapshot_manager.cleanup_snapshot()

                log_entry["status"] = "apply_failed"
                self.mutation_logger.update_rollback_status(log_entry, True, str(e))
                self.mutation_logger.finalize_status(log_entry, "apply_failed")
                self.mutation_logger.save_log(log_entry)

                return {
                    "success": False,
                    "message": f"Failed to apply changes: {e}",
                    "rollback": True
                }

        logger.info(f"Applied changes: {files_added} added, {files_modified} modified, {files_removed} removed")

        # Step 5: Run build gate
        build_success, build_output = self.build_gate.run_build()

        log_entry["build_result"] = {
            "success": build_success,
            "output": build_output[:1000] if build_output else ""
        }

        if not build_success:
            # Rollback on build failure
            self.snapshot_manager.restore_snapshot()
            self.snapshot_manager.cleanup_snapshot()

            log_entry["status"] = "build_failed"
            self.mutation_logger.update_rollback_status(log_entry, True, "Build failed")
            self.mutation_logger.finalize_status(log_entry, "build_failed")
            self.mutation_logger.save_log(log_entry)

            return {
                "success": False,
                "message": "Build failed",
                "build_output": build_output,
                "rollback": True
            }

        # Step 6: Success - cleanup snapshot and finalize log
        self.snapshot_manager.cleanup_snapshot()

        log_entry["status"] = "success"
        self.mutation_logger.update_rollback_status(log_entry, False, "")
        self.mutation_logger.finalize_status(log_entry, "success")
        self.mutation_logger.save_log(log_entry)

        return {
            "success": True,
            "message": "Changes applied successfully",
            "files_added": files_added,
            "files_modified": files_modified,
            "files_removed": files_removed,
            "build_output": build_output,
            "rollback": False
        }

    def get_mutation_log(self) -> List[Dict[str, Any]]:
        """
        Get the mutation log for this frontend.

        Returns:
            List of mutation log entries
        """
        log_file = self.mutation_logger.log_file
        if not log_file.exists():
            return []

        try:
            with open(log_file, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
