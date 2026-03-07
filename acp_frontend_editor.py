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
MAX_NEW_FILES = 12

# Build settings
BUILD_TIMEOUT = 600  # 10 minutes (increased for complex templates like finance)

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
            logger.error(f"[FileOps] Path validation failed: {reason}")
            return False, reason

        # Resolve path the same way as is_path_allowed (relative paths resolve to frontend_src_path)
        path = Path(file_path)
        if not path.is_absolute():
            path = (self.validator.frontend_src_path / file_path).resolve()
        else:
            path = path.resolve()

        logger.info(f"[FileOps] Resolved path: {path}")
        logger.info(f"[FileOps] File exists: {path.exists()}")

        # Check file limit for new files
        if not path.exists():
            if self._new_files_count >= MAX_NEW_FILES:
                logger.error(f"[FileOps] File limit exceeded: {self._new_files_count} >= {MAX_NEW_FILES}")
                return False, f"File limit exceeded: max {MAX_NEW_FILES} new files allowed"

            self._new_files_count += 1
            self.logger.log_file_added(log_entry, file_path)
            logger.info(f"[FileOps] New file #{self._new_files_count}: {file_path}")
        else:
            self.logger.log_file_modified(log_entry, file_path)
            logger.info(f"[FileOps] Modifying existing file: {file_path}")

        # Create parent directories if needed
        path.parent.mkdir(parents=True, exist_ok=True)
        logger.debug(f"[FileOps] Created parent directory: {path.parent}")

        # Write file
        try:
            logger.info(f"[FileOps] Writing {len(content)} bytes to {path}")
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"[FileOps] ✓ File written successfully: {file_path}")
            return True, f"File written: {file_path}"
        except Exception as e:
            logger.error(f"[FileOps] ❌ Failed to write file: {e}")
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

        logger.info(f"[ACPX] Starting to apply {len(changes)} change(s)")

        for i, change in enumerate(changes):
            action = change.get("action")
            path = change.get("path")
            content = change.get("content", "")

            logger.info(f"[ACPX] [{i+1}/{len(changes)}] Processing: action={action}, path={path}")

            try:
                if action in ("write", "modify"):
                    logger.info(f"[ACPX]   Writing/Modifying file: {path}")
                    success, msg = self.file_ops.write_file(path, content, log_entry)
                    if success:
                        logger.info(f"[ACPX]   ✓ File written successfully")
                        if "written" in msg and path not in log_entry["files_modified"]:
                            # Check if it was added or modified
                            if "added" in str(log_entry["files_added"][-1:] if log_entry["files_added"] else []):
                                files_added += 1
                            else:
                                files_modified += 1
                    else:
                        logger.error(f"[ACPX]   ❌ Failed to write file: {msg}")
                        raise Exception(msg)

                elif action == "remove":
                    logger.info(f"[ACPX]   Removing file: {path}")
                    success, msg = self.file_ops.remove_file(path, log_entry)
                    if success:
                        logger.info(f"[ACPX]   ✓ File removed successfully")
                        files_removed += 1
                    else:
                        logger.error(f"[ACPX]   ❌ Failed to remove file: {msg}")
                        raise Exception(msg)

                else:
                    logger.error(f"[ACPX]   ❌ Unknown action: {action}")
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
        logger.info(f"[ACPX] Running build gate (npm install && npm run build)")
        logger.info(f"[ACPX] Build timeout set to {BUILD_TIMEOUT} seconds")

        build_success, build_output = self.build_gate.run_build()

        log_entry["build_result"] = {
            "success": build_success,
            "output": build_output[:1000] if build_output else ""
        }

        if build_success:
            logger.info(f"[ACPX] ✓ Build succeeded!")
        else:
            logger.error(f"[ACPX] ❌ Build failed!")
            logger.error(f"[ACPX] Build output (last 500 chars):\n{build_output[-500:] if build_output else 'N/A'}")

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

    def generate_and_apply_changes(self, goal_description: str, execution_id: str) -> Dict[str, Any]:
        """
        Full flow: Ask Claude for changes → validate → apply → build → log/rollback

        Args:
            goal_description: Natural language description of changes
            execution_id: Unique ID for tracking

        Returns:
            Dict with success status, message, files changed, build output, rollback status
        """
        logger.info(f"Starting ACP edit for goal: {goal_description}")

        # Build instruction for Claude - Production-Grade UI Redesign Mode
        instruction = f"""You are editing a React + Vite + TypeScript project.

Project Name: {self.project_name}
Project Description: {goal_description}

GOAL:
Redesign the existing dashboard UI to a modern, professional analytics dashboard while preserving project structure.

STRICT RULES

You may ONLY modify files inside:
src/

DO NOT modify:
- src/components/ui/ (UI primitives only)
- package.json, vite.config.*, node_modules
- backend files, .env files
- Do NOT change project architecture

SCOPE LIMITATION (CRITICAL)
- ONLY scan files in src/pages/ and src/components/ directories
- DO NOT scan entire project tree
- DO NOT index node_modules, dist, or build directories
- Focus on UI/UX changes, not architectural refactoring
- Limit file operations to {MAX_NEW_FILES} files maximum

UI DESIGN OBJECTIVE

Transform the existing template into a premium analytics dashboard similar to modern SaaS platforms.

IMPROVE:
• Visual hierarchy
• Layout spacing
• Typography scale
• Component grouping
• Responsive behavior
• Chart presentation
• Sidebar styling
• Header UX

DASHBOARD REDESIGN REQUIREMENTS

Redesign the main dashboard page to include:

1. HERO HEADER SECTION
 - Title: {self.project_name}
 - Subtitle based on project description ({goal_description})
 - Action buttons (Add Asset, Refresh Data, View All)

2. STATS CARDS ROW
Modern cards with:
 - Icon
 - Label
 - Large value
 - Change indicator (+/- %)
 - Subtle gradient background

3. ANALYTICS GRID LAYOUT

Left column:
- Portfolio performance chart
- Market trends chart
- Activity timeline

Right column:
- Asset allocation donut/pie chart
- Top assets table
- Recent transactions

4. ASSETS / DATA TABLE
Columns with proper alignment:
- Asset / Name
- Price
- 24h Change
- Holdings
- Value
- Actions

5. MODERN SIDEBAR
Improve sidebar UX:
- Active indicator glow
- Better spacing and padding
- Proper icon alignment
- Improved branding for {self.project_name}
- Collapse/expand behavior

6. HEADER IMPROVEMENTS
Improve header bar:
- Search bar with icon
- Notification badge icon
- Profile avatar dropdown
- Theme toggle (if not present)

DESIGN STYLE

Use modern dashboard design patterns:
- Glassmorphism or subtle gradients
- Card-based layout with proper spacing
- Rounded corners (xl/2xl)
- Soft shadows
- Proper padding and gaps (4, 6, 8)
- Responsive grid (1 col mobile, 2 col tablet, 3-4 col desktop)

Use existing UI primitives from:
src/components/ui/

Do NOT recreate base UI components. Reuse Card, Button, Badge, Table, etc.

FILE CREATION RULES

Minimum new components: 2
Maximum new components: {MAX_NEW_FILES}

Allowed files to create:
- src/pages/ (new dashboard views)
- src/components/ (new dashboard widgets)
- src/features/ (feature-specific components)

Remove generic template pages if they are unused and don't fit the project.

ROUTING

If new pages are added, update routing inside:
src/App.tsx or src/main.tsx

Do NOT break existing routes.

CRITICAL: DO NOT ONLY RENAME TITLES
- Improve layout structure and component organization
- Add proper sections and groupings
- Create visual hierarchy with spacing and typography
- Transform generic template into project-specific dashboard

OUTPUT

Make the UI look like a modern SaaS analytics dashboard.

Focus on visual quality and layout improvement rather than simple text changes.

You MUST return ONLY a valid JSON array with the following structure. Do not include any other text, explanations, or markdown formatting:

[
  {{
    "action": "write" | "modify" | "remove",
    "path": "relative/path/from/src e.g. components/StatsCard.tsx",
    "content": "full file content as string (use empty string for remove)"
  }}
]

Execute this UI redesign now.
"""

        # Call acpx using the working path (from MEMORY.md)
        # Fixed path based on successful test: /usr/lib/node_modules/openclaw/extensions/acpx/node_modules/acpx/dist/cli.js
        acpx_bin = "/usr/lib/node_modules/openclaw/extensions/acpx/node_modules/acpx/dist/cli.js"
        cmd = [acpx_bin, "claude", "exec", "--dangerously-skip-permissions", instruction]

        logger.info(f"[ACPX] 🔴 HEARTBEAT: Starting ACPX subprocess")
        logger.info(f"[ACPX] 🔴 HEARTBEAT: Command: {acpx_bin} claude exec --dangerously-skip-permissions")
        logger.info(f"[ACPX] 🔴 HEARTBEAT: Timeout set to 1800 seconds (30 minutes)")
        logger.info(f"[ACPX] 🔴 HEARTBEAT: Working directory: {self.validator.frontend_src_path}")

        try:
            # Run acpx - ignore exit codes (telemetry bug can cause non-zero exit)
            # Instead, parse the output to detect if changes were made
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=1800,  # Increased from 600s to 1800s (30 minutes)
                # Don't use check=True - telemetry bug can cause false failures
                cwd=self.validator.frontend_src_path
            )

            logger.info(f"[ACPX] 🔴 HEARTBEAT: ACPX subprocess completed (did NOT timeout)")
            logger.info(f"[ACPX] 🔴 HEARTBEAT: Total elapsed time likely < 30 minutes")

            output = result.stdout.strip()
            stderr = result.stderr.strip()

            logger.info(f"[ACPX] Subprocess completed")
            logger.info(f"[ACPX] Return code: {result.returncode}")

            # Log output for debugging (ignore harmless telemetry errors)
            if "session/update" in stderr or "Invalid params" in stderr:
                logger.debug(f"Ignoring harmless telemetry error (ACP bug)")
            elif stderr:
                logger.debug(f"acpx stderr (last 500 chars): {stderr[-500:]}")  # Last 500 chars

            logger.info(f"[ACPX] Output length: {len(output)} chars")
            logger.info(f"[ACPX] First 500 chars:\n{output[:500]}")
            logger.info(f"[ACPX] Last 500 chars:\n{output[-500:]}")

            # Extract JSON patch (robust version - handle markdown formatting)
            logger.info(f"[ACPX] Attempting to extract JSON patch from output")

            # Try multiple patterns to find JSON array
            match = re.search(r'```json\s*\[\s*\{.*\}\s*\]\s*```', output, re.DOTALL)
            if not match:
                match = re.search(r'\[\s*\{.*\}\s*\]', output, re.DOTALL)

            if not match:
                logger.error(f"[ACPX] ❌ JSON patch not found in output!")
                logger.error(f"[ACPX] Full output:\n{output}")
                raise ValueError("No JSON patch found in output")

            patch_str = match.group(0)
            logger.info(f"[ACPX] ✓ Found JSON patch (length: {len(patch_str)} chars)")

            # Strip markdown if present
            patch_str = re.sub(r'^```json\s*|\s*```$', '', patch_str.strip(), flags=re.MULTILINE | re.IGNORECASE)
            logger.info(f"[ACPX] Patch after markdown strip (first 300 chars):\n{patch_str[:300]}")

            changes = json.loads(patch_str)
            if not isinstance(changes, list):
                logger.error(f"[ACPX] ❌ Patch is not a list! Type: {type(changes)}")
                raise ValueError("Patch must be a list")

            logger.info(f"[ACPX] ✓ Parsed JSON array with {len(changes)} change(s)")

            # Log each change
            for i, change in enumerate(changes):
                action = change.get('action', 'unknown')
                path = change.get('path', 'unknown')
                content_len = len(change.get('content', ''))
                logger.info(f"[ACPX]   Change {i+1}: action={action}, path={path}, content_length={content_len}")

        except subprocess.TimeoutExpired:
            logger.error(f"[ACPX] 🔴 HEARTBEAT: ❌ TIMED OUT after 30 minutes (1800 seconds)")
            logger.error(f"[ACPX] 🔴 HEARTBEAT: ACPX subprocess was killed by timeout")
            logger.error(f"[ACPX] 🔴 HEARTBEAT: This usually means Claude was:")
            logger.error(f"[ACPX] 🔴 HEARTBEAT:   1. Stuck in a long analysis/scanning phase")
            logger.error(f"[ACPX] 🔴 HEARTBEAT:   2. Waiting for tool approval (permissions)")
            logger.error(f"[ACPX] 🔴 HEARTBEAT:   3. Processing too many files")
            logger.error(f"[ACPX] 🔴 HEARTBEAT: Permission flag was used, so #2 should not happen")
            logger.error(f"[ACPX] 🔴 HEARTBEAT: Consider reducing AI scope further")
            return {
                "success": False,
                "message": "Claude/acpx timed out after 30 minutes"
            }
        except Exception as e:
            logger.error(f"[ACPX] 🔴 HEARTBEAT: ❌ EXCEPTION occurred")
            logger.error(f"[ACPX] 🔴 HEARTBEAT: Exception type: {type(e).__name__}")
            logger.error(f"[ACPX] 🔴 HEARTBEAT: Exception message: {str(e)}")
            return {
                "success": False,
                "message": f"Failed to generate changes: {e}"
            }

        # Now apply the received changes
        return self.apply_changes(changes, execution_id)

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
