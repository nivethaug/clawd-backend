#!/usr/bin/env python3
"""
ACP Frontend Editor v2 - Filesystem Diff Architecture

Implements safe, validated frontend editing using filesystem diffing:
- Snapshot before changes
- Run ACPX (lets AI edit files naturally)
- Detect changes via filesystem comparison
- Validate paths and file limits
- Build gate and rollback on failure

This is the correct architecture for tool-using AI agents like Claude.
"""

import os
import shutil
import subprocess
import logging
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set

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

# File limits - Increased for reliable multi-page execution
MAX_NEW_FILES = 50  # Allow enough pages without early termination

# Build settings
BUILD_TIMEOUT = 1800  # 30 minutes

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
        path = Path(file_path).resolve()

        # Check 1: Forbidden backend path
        try:
            if FORBIDDEN_BACKEND in str(path) or str(path).startswith(FORBIDDEN_BACKEND):
                return False, f"Forbidden: Cannot modify backend files ({path})"
        except (ValueError, RuntimeError):
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
            pass

        # All checks passed
        return True, "Allowed"


# =============================================================================
# FILESYSTEM SNAPSHOT
# =============================================================================

def _file_hash(file_path: Path) -> str:
    """
    Compute SHA1 hash of a file.

    Args:
        file_path: Path to file

    Returns:
        Hex digest string
    """
    h = hashlib.sha1()
    with open(file_path, 'rb') as f:
        h.update(f.read())
    return h.hexdigest()

class FilesystemSnapshot:
    """Captures and compares filesystem state using file hashes."""

    @staticmethod
    def get_file_hashes(base_path: Path) -> Dict[str, str]:
        """
        Get dict of file hashes in directory (recursively).

        Args:
            base_path: Base directory to scan

        Returns:
            Dict mapping file path (relative to base) to hash
        """
        hashes = {}
        if not base_path.exists():
            return hashes

        for path in base_path.rglob("*"):
            if path.is_file():
                # Exclude node_modules, dist, build directories
                if not any(excluded in str(path) for excluded in ['node_modules', '.git', 'dist', 'build']):
                    rel_path = str(path.relative_to(base_path))
                    hashes[rel_path] = _file_hash(path)

        return hashes

    @staticmethod
    def compute_diff(before: Dict[str, str], after: Dict[str, str]) -> Dict[str, List[str]]:
        """
        Compute difference between two file hash states.

        Args:
            before: File hashes before changes
            after: File hashes after changes

        Returns:
            Dict with 'added', 'removed', 'modified' file lists
        """
        before_paths = set(before.keys())
        after_paths = set(after.keys())

        added = list(after_paths - before_paths)
        removed = list(before_paths - after_paths)

        # Modified: exists in both but hash changed
        modified = []
        for path in before_paths & after_paths:
            if before[path] != after[path]:
                modified.append(path)

        return {
            'added': added,
            'removed': removed,
            'modified': modified
        }


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
            logger.info(f"[Snapshot] Creating snapshot at {self.backup_dir}")
            self.backup_dir.mkdir(parents=True, exist_ok=True)

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
                (self.backup_dir / "frontend").mkdir(parents=True)

            logger.info(f"[Snapshot] ✓ Snapshot created successfully")
            return True, str(self.backup_dir)

        except Exception as e:
            logger.error(f"[Snapshot] ❌ Failed to create snapshot: {e}")
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

            if self.frontend_path.exists():
                shutil.rmtree(self.frontend_path)

            shutil.copytree(backup_frontend, self.frontend_path)

            logger.info(f"[Snapshot] ✓ Restored snapshot from {self.backup_dir}")
            return True, "Snapshot restored successfully"

        except Exception as e:
            logger.error(f"[Snapshot] ❌ Failed to restore snapshot: {e}")
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
                logger.info(f"[Snapshot] ✓ Cleaned up snapshot at {self.backup_dir}")
            return True
        except Exception as e:
            logger.error(f"[Snapshot] ❌ Failed to cleanup snapshot: {e}")
            return False


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
# MAIN ACP EDITOR V2
# =============================================================================

class ACPFrontendEditorV2:
    """
    ACP Frontend Editor v2 using filesystem diffing.

    Workflow:
    1. Capture filesystem snapshot
    2. Run ACPX (AI edits files naturally)
    3. Detect changes via filesystem comparison
    4. Validate paths and file limits
    5. Run build gate
    6. On failure: rollback
    """

    def __init__(self, frontend_src_path: str, project_name: str):
        """
        Initialize ACP Frontend Editor v2.

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
        self.build_gate = ACPBuildGate(str(self.frontend_path))

    def apply_changes_via_acpx(
        self,
        goal_description: str,
        execution_id: str
    ) -> Dict[str, Any]:
        """
        Apply frontend changes by running ACPX and detecting filesystem changes.

        Args:
            goal_description: Natural language description of changes
            execution_id: Unique ID for tracking

        Returns:
            Dict with success, message, files changed, build output, rollback status
        """
        logger.info(f"[ACPX-V2] 🔴 HEARTBEAT: Starting Phase 9 (Filesystem Diff Architecture)")
        logger.info(f"[ACPX-V2] 🔴 HEARTBEAT: Project: {self.project_name}")
        logger.info(f"[ACPX-V2] 🔴 HEARTBEAT: Execution ID: {execution_id}")

        # Step 1: Create snapshot
        logger.info(f"[ACPX-V2] Step 1: Creating filesystem snapshot...")
        snapshot_success, snapshot_msg = self.snapshot_manager.create_snapshot()
        if not snapshot_success:
            return {
                "success": False,
                "message": f"Snapshot creation failed: {snapshot_msg}",
                "rollback": False
            }

        # Step 2: Capture filesystem state BEFORE ACPX
        logger.info(f"[ACPX-V2] Step 2: Capturing filesystem state before ACPX...")
        hashes_before = FilesystemSnapshot.get_file_hashes(self.frontend_src_path)
        logger.info(f"[ACPX-V2]   Found {len(hashes_before)} files before ACPX")

        # Step 3: Build ACPX prompt (no JSON requirement) with completion tracking
        logger.info(f"[ACPX-V2] Step 3: Building ACPX prompt...")
        prompt = self._build_acpx_prompt(goal_description)

        # Step 4: Run ACPX
        logger.info(f"[ACPX-V2] Step 4: Running ACPX...")
        logger.info(f"[ACPX-V2]   Acpx path: /usr/lib/node_modules/openclaw/extensions/acpx/node_modules/acpx/dist/cli.js")
        logger.info(f"[ACPX-V2]   Working directory: {self.frontend_src_path}")
        logger.info(f"[ACPX-V2]   Timeout: {BUILD_TIMEOUT} seconds")

        acpx_bin = "/usr/lib/node_modules/openclaw/extensions/acpx/node_modules/acpx/dist/cli.js"
        cmd = [acpx_bin, "claude", "exec", prompt]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=BUILD_TIMEOUT,
                cwd=self.frontend_src_path
            )

            logger.info(f"[ACPX-V2] 🔴 HEARTBEAT: ACPX subprocess completed (no timeout)")
            logger.info(f"[ACPX-V2]   Return code: {result.returncode}")
            logger.info(f"[ACPX-V2]   Stdout length: {len(result.stdout)} chars")
            logger.info(f"[ACPX-V2]   Stderr length: {len(result.stderr)} chars")

        except subprocess.TimeoutExpired:
            logger.error(f"[ACPX-V2] 🔴 HEARTBEAT: ❌ TIMED OUT after {BUILD_TIMEOUT} seconds")
            self.snapshot_manager.restore_snapshot()
            self.snapshot_manager.cleanup_snapshot()
            return {
                "success": False,
                "message": f"ACPX timed out after {BUILD_TIMEOUT} seconds",
                "rollback": True
            }

        # Step 5: Capture filesystem state AFTER ACPX
        logger.info(f"[ACPX-V2] Step 5: Capturing filesystem state after ACPX...")
        hashes_after = FilesystemSnapshot.get_file_hashes(self.frontend_src_path)
        logger.info(f"[ACPX-V2]   Found {len(hashes_after)} files after ACPX")

        # Step 6: Compute changes (filesystem diff)
        logger.info(f"[ACPX-V2] Step 6: Computing filesystem diff...")
        diff = FilesystemSnapshot.compute_diff(hashes_before, hashes_after)

        files_added = diff['added']
        files_removed = diff['removed']
        files_modified = diff['modified']

        logger.info(f"[ACPX-V2]   Files added: {len(files_added)}")
        for f in files_added[:10]:
            logger.info(f"[ACPX-V2]     + {f}")
        if len(files_added) > 10:
            logger.info(f"[ACPX-V2]     ... and {len(files_added) - 10} more")

        logger.info(f"[ACPX-V2]   Files removed: {len(files_removed)}")
        for f in files_removed[:10]:
            logger.info(f"[ACPX-V2]     - {f}")
        if len(files_removed) > 10:
            logger.info(f"[ACPX-V2]     ... and {len(files_removed) - 10} more")

        logger.info(f"[ACPX-V2]   Files modified: {len(files_modified)}")
        for f in files_modified[:10]:
            logger.info(f"[ACPX-V2]     ~ {f}")
        if len(files_modified) > 10:
            logger.info(f"[ACPX-V2]     ... and {len(files_modified) - 10} more")

        # Step 7: Validate file limits
        logger.info(f"[ACPX-V2] Step 7: Validating file limits...")
        if len(files_added) > MAX_NEW_FILES:
            logger.error(f"[ACPX-V2] ❌ File limit exceeded: {len(files_added)} > {MAX_NEW_FILES}")
            self.snapshot_manager.restore_snapshot()
            self.snapshot_manager.cleanup_snapshot()
            return {
                "success": False,
                "message": f"File limit exceeded: {len(files_added)} new files, max {MAX_NEW_FILES} allowed",
                "rollback": True
            }
        logger.info(f"[ACPX-V2]   ✓ File limit OK ({len(files_added)}/{MAX_NEW_FILES})")

        # Step 8: Validate paths
        logger.info(f"[ACPX-V2] Step 8: Validating paths...")
        for file_path in files_added + files_removed:
            # Convert string to Path object before calling relative_to
            path_obj = Path(file_path)
            rel_path = str(path_obj.relative_to(self.frontend_src_path))
            allowed, reason = self.validator.is_path_allowed(rel_path)
            if not allowed:
                logger.error(f"[ACPX-V2] ❌ Path validation failed: {reason}")
                self.snapshot_manager.restore_snapshot()
                self.snapshot_manager.cleanup_snapshot()
                return {
                    "success": False,
                    "message": f"Path validation failed: {reason}",
                    "rollback": True
                }
        logger.info(f"[ACPX-V2]   ✓ All paths valid")

        # Step 9: Run build gate
        logger.info(f"[ACPX-V2] Step 9: Running build gate (npm install && npm run build)...")
        build_success, build_output = self.build_gate.run_build()

        if not build_success:
            logger.error(f"[ACPX-V2] ❌ Build failed")
            logger.error(f"[ACPX-V2]   Build output (last 500 chars):\n{build_output[-500:]}")
            self.snapshot_manager.restore_snapshot()
            self.snapshot_manager.cleanup_snapshot()
            return {
                "success": False,
                "message": "Build failed",
                "build_output": build_output,
                "rollback": True
            }

        logger.info(f"[ACPX-V2] ✓ Build succeeded!")

        # Step 10: Success - cleanup snapshot
        logger.info(f"[ACPX-V2] Step 10: Cleanup snapshot...")
        self.snapshot_manager.cleanup_snapshot()

        return {
            "success": True,
            "message": "ACPX changes applied successfully",
            "files_added": len(files_added),
            "files_modified": len(files_modified),
            "files_removed": len(files_removed),
            "build_output": build_output,
            "rollback": False
        }

    def _build_acpx_prompt(self, goal_description: str) -> str:
        """
        Build ACPX prompt with explicit required artifacts and completion checklist.

        Args:
            goal_description: Goal for changes

        Returns:
            Prompt string for ACPX
        """
        # Extract required pages from goal description (simple keyword matching)
        required_pages = []
        required_components = []

        # Common page patterns
        desc_lower = goal_description.lower()
        if any(word in desc_lower for word in ['dashboard', 'overview']):
            required_pages.append('Dashboard')
        if any(word in desc_lower for word in ['document', 'docflow', 'panda', 'agreement', 'contract']):
            required_pages.extend(['Documents', 'DocumentEditor', 'Templates', 'Signing'])
        if any(word in desc_lower for word in ['analytics', 'reports', 'metrics']):
            required_pages.append('Analytics')
        if any(word in desc_lower for word in ['contact', 'crm', 'customer', 'lead']):
            required_pages.append('Contacts')
        if any(word in desc_lower for word in ['task', 'todo', 'project', 'kanban']):
            required_pages.append('Tasks')
        if any(word in desc_lower for word in ['setting', 'config', 'preference']):
            required_pages.append('Settings')
        if any(word in desc_lower for word in ['post', 'article', 'blog']):
            required_pages.append('Posts')
        if any(word in desc_lower for word in ['create', 'write', 'compose']):
            required_pages.append('Create')

        # Build required artifacts list
        required_pages_list = list(set(required_pages))
        required_components_list = list(set(required_components))
        
        required_pages_str = "\n".join([f"- src/pages/{page}.tsx" for page in required_pages_list])
        required_components_str = "\n".join([f"- src/components/{comp}.tsx" for comp in required_components_list])

        return f"""You are editing a React + Vite + TypeScript SaaS application.

Project Name: {self.project_name}
Project Description: {goal_description}

YOUR TASK

Transform the existing template into a production-ready application based on the project description above.

STRICT RULES

You may ONLY modify files inside:
src/

DO NOT modify:
- src/components/ui/ (UI primitives only)
- package.json, vite.config.*, node_modules
- backend files, .env files
- Do NOT change project architecture

SCOPE LIMITATION (CRITICAL - Reduces AI scanning time)

ONLY modify files in these directories:
- src/pages/
- src/components/
- src/layout/
- src/features/

DO NOT scan:
- node_modules
- dist
- build
- .git

REQUIRED PAGES (ALL MUST EXIST)

{required_pages_str}

REQUIRED COMPONENTS (IF APPLICABLE)

{required_components_str}

COMPLETION CHECKLIST

✓ All required pages created in src/pages/
✓ All required components created in src/components/
✓ Routing updated in src/App.tsx
✓ Navigation/sidebar updated
✓ Responsive design implemented
✓ Code is production-ready
✓ npm run build succeeds

WORKING METHODOLOGY

You must work systematically through ALL required pages.

1. Read the project description carefully
2. Plan your approach
3. Execute step by step
4. DO NOT STOP until ALL required pages are created
5. After completing a page, move to the next page
6. Continue until the entire checklist is complete

EXECUTION RULES

1. Work through pages ONE AT A TIME
2. Complete each page fully before moving to the next
3. Do not skip any required page
4. Do not stop early - continue until checklist is 100% complete
5. After finishing all pages, run npm run build
6. Only mark task complete when ALL checklist items are done

TECHNICAL REQUIREMENTS

- Keep the code buildable (npm run build must succeed)
- Use existing UI components from src/components/ui/
- Follow existing code patterns and style
- Write clean, production-ready code
- Do not introduce placeholder content unless required

IMPLEMENTATION

Make your changes directly to files.

Do NOT request JSON output or any specific format.

Just implement the changes using your available tools.
"""
