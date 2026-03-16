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
import re
import shutil
import subprocess
import logging
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set

# Page manifest system
from page_manifest import PageManifest, create_page_manifest, scaffold_pages

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

# Allowed directories for ACPX editing (relative to frontend/src - no src/ prefix)
# Changed to allow-all approach: Everything under src/ is allowed except FORBIDDEN paths
ALLOWED_EDIT_PATHS = [
    "*"  # Allow all - actual restriction handled by FORBIDDEN_EDIT_PATHS
]

# Forbidden paths that ACPX must NOT modify
FORBIDDEN_EDIT_PATHS = [
    "node_modules",
    "package.json",
    "package-lock.json",
    "vite.config.ts",
    "vite.config.js",
    "tsconfig.json",
    ".env",
    ".env.local",
    "components/ui"  # UI primitives only - use but don't modify
]

# File limits - Increased for reliable multi-page execution
MAX_NEW_FILES = 15  # Maximum new files per execution

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
        # Handle both absolute and relative paths
        path = Path(file_path)
        
        # If path is relative, join with frontend_src_path
        if not path.is_absolute():
            path = self.frontend_src_path / path
        else:
            path = path.resolve()
        
        # Get relative path from frontend_src_path
        try:
            rel_path = path.relative_to(self.frontend_src_path)
            rel_path_str = str(rel_path)
        except ValueError:
            return False, f"Forbidden: Path outside frontend/src ({path})"

        # Check 1: Forbidden paths (exact path segment matching)
        path_parts = Path(rel_path).parts
        for forbidden in FORBIDDEN_EDIT_PATHS:
            if forbidden in path_parts:
                return False, f"Forbidden: Cannot modify {forbidden} ({rel_path})"

        # Check 2: Specifically block components/ui (exact path segment)
        if "ui" in path_parts and "components" in path_parts:
            return False, f"Forbidden: Cannot modify UI components ({rel_path})"

        # Check 3: Allow all except forbidden (simplified approach)
        # If we reach here, the path is not in forbidden list, so it's allowed
        return True, "Allowed"


# =============================================================================
# FILESYSTEM SNAPSHOT
# =============================================================================

def _file_hash(file_path: Path) -> str:
    """
    Compute file hash using MD5.

    Args:
        file_path: Path to file

    Returns:
        MD5 hexdigest string
    """
    with open(file_path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()

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
                # Exclude node_modules, dist, build directories using path parts
                path_parts = path.parts
                if not any(excluded in path_parts for excluded in ['node_modules', '.git', 'dist', 'build']):
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

    def rollback_and_cleanup(self) -> Tuple[bool, str]:
        """
        Restore snapshot and cleanup in atomic operation.

        Returns:
            Tuple of (success, message)
        """
        success, msg = self.restore_snapshot()
        if success:
            self.cleanup_snapshot()
            return True, "Rollback and cleanup successful"
        return False, f"Rollback failed, backup preserved at {self.backup_dir}: {msg}"


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
        Run npm install and npm run build with output verification.

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

            # Step 2: npm run build with retry logic (max 3 attempts)
            max_retries = 3
            for attempt in range(1, max_retries + 1):
                output.append(f"\n--- Running npm run build (Attempt {attempt}/{max_retries}) ---")

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
                    if attempt < max_retries:
                        output.append(f"Retrying build (attempt {attempt + 1}/{max_retries})...")
                        continue
                    else:
                        return False, "\n".join(output)

                # Build succeeded - verify output
                output.append("npm run build completed successfully")

                # Step 3: Verify build output
                output.append("\n--- Verifying Build Output ---")
                dist_path = self.frontend_path / "dist"

                # Check 1: dist/index.html exists
                index_html = dist_path / "index.html"
                if not index_html.exists():
                    output.append(f"❌ ERROR: dist/index.html not found")
                    output.append(f"dist directory contents: {list(dist_path.iterdir()) if dist_path.exists() else 'dist/ does not exist'}")
                    return False, "\n".join(output)

                index_size = index_html.stat().st_size
                output.append(f"✓ dist/index.html exists ({index_size:,} bytes)")

                # Check 2: dist/assets directory exists
                assets_dir = dist_path / "assets"
                if not assets_dir.exists():
                    output.append(f"❌ ERROR: dist/assets/ directory not found")
                    return False, "\n".join(output)

                output.append(f"✓ dist/assets/ directory exists")

                # Check 3: dist/assets/*.js exists
                js_files = list(assets_dir.glob("*.js"))
                if not js_files:
                    output.append(f"❌ ERROR: No JavaScript files in dist/assets/")
                    output.append(f"dist/assets/ contents: {list(assets_dir.iterdir()) if assets_dir.exists() else 'assets/ does not exist'}")
                    return False, "\n".join(output)

                output.append(f"✓ Found {len(js_files)} JavaScript files")
                for js_file in js_files[:5]:  # List first 5 JS files
                    js_size = js_file.stat().st_size
                    output.append(f"  - {js_file.name} ({js_size:,} bytes)")
                if len(js_files) > 5:
                    output.append(f"  ... and {len(js_files) - 5} more JS files")

                # Check 4: dist/assets/*.css exists (non-fatal, CSS might be inlined)
                css_files = list(assets_dir.glob("*.css"))
                if not css_files:
                    output.append(f"⚠️  WARNING: No CSS files in dist/assets/ (CSS might be inlined in JS)")
                else:
                    output.append(f"✓ Found {len(css_files)} CSS files")
                    for css_file in css_files[:5]:  # List first 5 CSS files
                        css_size = css_file.stat().st_size
                        output.append(f"  - {css_file.name} ({css_size:,} bytes)")
                    if len(css_files) > 5:
                        output.append(f"  ... and {len(css_files) - 5} more CSS files")

                # Check 5: Verify overall dist/ structure
                output.append(f"\n--- Build Output Summary ---")
                output.append(f"dist/ path: {dist_path}")
                output.append(f"Total items in dist/: {len(list(dist_path.rglob('*')))}")
                output.append("--- Build Verification Complete ---")

                # If we got here, build verification passed
                break

            output.append("=== Build Process Complete ===")
            return True, "\n".join(output)

        except subprocess.TimeoutExpired:
            output.append(f"Build timeout after {BUILD_TIMEOUT} seconds")
            return False, "\n".join(output)
        except Exception as e:
            output.append(f"Build error: {e}")
            import traceback
            output.append(traceback.format_exc())
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

    def __init__(self, frontend_src_path: str, project_name: str, max_new_files: int = 15):
        """
        Initialize ACP Frontend Editor v2.

        Args:
            frontend_src_path: Absolute path to frontend/src directory
            project_name: Name of the project for logging
            max_new_files: Maximum number of new files allowed per execution
        """
        self.frontend_src_path = Path(frontend_src_path).resolve()
        self.frontend_path = self.frontend_src_path.parent
        self.project_name = project_name
        self.max_new_files = max_new_files

        # print(f"🔴 ACPX-V2-INIT: frontend_src_path = {self.frontend_src_path}")
        # print(f"🔴 ACPX-V2-INIT: frontend_path = {self.frontend_path}")
        # print(f"🔴 ACPX-V2-INIT: project_root = {self.frontend_path.parent}")

        # Initialize components
        self.validator = ACPPathValidator(frontend_src_path)
        self.snapshot_manager = ACPSnapshotManager(str(self.frontend_path))
        self.build_gate = ACPBuildGate(str(self.frontend_path))

        # Phase 9: Guardrails - Store allowed pages whitelist
        self.allowed_pages: Set[str] = set()

        # Page inference cache to prevent double LLM calls
        self._cached_pages: Optional[List[str]] = None

        # Phase 5: Page Manifest - Initialize manifest manager
        # Pass project root path (parent of frontend), not frontend path
        # to avoid path doubling in PageManifest which appends frontend/src/
        self.manifest_manager = PageManifest(str(self.frontend_path.parent))
        # print(f"🔴 ACPX-V2-INIT: manifest_manager.pages_path = {self.manifest_manager.pages_path}")

    async def apply_changes_via_acpx(
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
        import traceback

        # print("🔴 ACPX-V2-METHOD-START: apply_changes_via_acpx called")
        # print(f"🔴 ACPX-V2-METHOD-START: Goal: {goal_description[:100]}")
        # print(f"🔴 ACPX-V2-METHOD-START: Execution ID: {execution_id}")

        # Clear cache for each new execution to ensure fresh page inference
        self._cached_pages = None
        # print("🔴 ACPX-V2-CACHE-CLEAR: Cleared cached pages for fresh inference")

        try:
            # print("🔴 ACPX-V2-TRY-BLOCK: Starting main logic")
            logger.info(f"[ACPX-V2] 🔴 HEARTBEAT: Starting Phase 9 (Filesystem Diff Architecture)")
            logger.info(f"[ACPX-V2] 🔴 HEARTBEAT: Project: {self.project_name}")
            logger.info(f"[ACPX-V2] 🔴 HEARTBEAT: Execution ID: {execution_id}")

            # Step 1: Create snapshot
            try:
                # print("🔴 ACPX-V2-STEP1: Creating snapshot")
                logger.info(f"[ACPX-V2] Step 1: Creating filesystem snapshot...")
                snapshot_success, snapshot_msg = self.snapshot_manager.create_snapshot()
                # print(f"🔴 ACPX-V2-STEP1-DONE: Snapshot created, success={snapshot_success}")

                if not snapshot_success:
                    # print("🔴 ACPX-V2-EARLY-RETURN: Snapshot creation failed, returning early")
                    result = {
                        "success": False,
                        "message": f"Snapshot creation failed: {snapshot_msg}",
                        "rollback": False
                    }
                    # print(f"🔴 ACPX-V2-RETURN: Success={result.get('success')}, Added={result.get('files_added', 0)}, Modified={result.get('files_modified', 0)}")
                    return result
            except Exception as e:
                # print(f"🔴 ACPX-V2-STEP1-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                return {"success": False, "message": f"Snapshot failed: {str(e)}"}

            # Step 2: Generate page manifest from planner (Phase 5 - NEW)
            try:
                # print("🔴 ACPX-V2-STEP2: Generating manifest")
                logger.info(f"[ACPX-V2] Step 2: Generating page manifest (Phase 5)...")
                required_pages = await self._extract_required_pages_from_prompt(goal_description)
                # print(f"🔴 ACPX-V2-STEP2-INFO: Pages to create: {required_pages}")
                logger.info(f"[ACPX-V2]   Planner detected pages: {required_pages}")

                # Write manifest to project directory
                manifest_success = self.manifest_manager.write_manifest(required_pages)
                if not manifest_success:
                    # print("🔴 ACPX-V2-EARLY-RETURN: Failed to write page manifest, returning early")
                    result = {
                        "success": False,
                        "message": "Failed to write page manifest",
                        "rollback": False
                    }
                    # print(f"🔴 ACPX-V2-RETURN: Success={result.get('success')}, Added={result.get('files_added', 0)}, Modified={result.get('files_modified', 0)}")
                    return result

                # Update allowed_pages with manifest pages (source of truth)
                self.allowed_pages = set(required_pages)
                logger.info(f"[ACPX-V2]   Manifest pages set as allowed: {required_pages}")
                
                # 🎯 FINALIZED PAGES - Clear PM2 log visibility
                print("=" * 80)
                print("🎯 FINALIZED PAGES FOR AI EDITING:")
                for i, page in enumerate(required_pages, 1):
                    print(f"   {i}. {page}.tsx")
                print(f"   Total: {len(required_pages)} pages")
                print("=" * 80)
                logger.info(f"[ACPX-V2] 🎯 FINALIZED PAGES: {required_pages}")
                
                # print("🔴 ACPX-V2-STEP2-DONE: Manifest generated")
            except Exception as e:
                # print(f"🔴 ACPX-V2-STEP2-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                return {"success": False, "message": f"Manifest failed: {str(e)}"}

            # Step 3: Capture filesystem state BEFORE ACPX (moved before scaffold)
            try:
                # print("🔴 ACPX-V2-STEP3: Capturing filesystem state before ACPX")
                logger.info(f"[ACPX-V2] Step 3: Capturing filesystem state before ACPX...")
                hashes_before = FilesystemSnapshot.get_file_hashes(self.frontend_src_path)
                logger.info(f"[ACPX-V2]   Found {len(hashes_before)} files before ACPX")
                # print("🔴 ACPX-V2-STEP3-DONE: Filesystem state captured")
            except Exception as e:
                # print(f"🔴 ACPX-V2-STEP3-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                return {"success": False, "message": f"Failed to capture filesystem state: {str(e)}"}

            # Step 4: Scaffold pages from manifest (Phase 5 - NEW)
            try:
                # print("🔴 ACPX-V2-STEP4: Scaffolding pages")
                logger.info(f"[ACPX-V2] Step 4: Scaffolding pages from manifest...")

                # print(f"🔴 ACPX-V2-STEP4-PAGES: Pages to scaffold = {required_pages}")
                # print("🔴 ACPX-V2-STEP4-PRE: Calling scaffold_pages()")
                scaffold_result = self.manifest_manager.scaffold_pages(required_pages, create_placeholder=True)
                # print(f"🔴 ACPX-V2-STEP4-POST: scaffold_pages() returned")
                # print(f"🔴 ACPX-V2-STEP4-POST-VALUE: {scaffold_result}")

                # Verify files were created
                # print("🔴 ACPX-V2-STEP4-VERIFY: Checking created files...")
                for page in required_pages:
                    page_file = self.frontend_src_path / "pages" / f"{page}.tsx"
                    exists = page_file.exists()
                    # print(f"🔴 ACPX-V2-STEP4-VERIFY: {page}.tsx exists = {exists}")
                    if exists:
                        size = page_file.stat().st_size
                        # print(f"🔴 ACPX-V2-STEP4-VERIFY: {page}.tsx size = {size} bytes")

                # Check return value type
                if isinstance(scaffold_result, bool):
                    # print(f"🔴 ACPX-V2-STEP4-POST-TYPE: bool, value={scaffold_result}")
                    pass
                elif scaffold_result is None:
                    # print("🔴 ACPX-V2-STEP4-POST-TYPE: None (treated as True)")
                    pass

                if not scaffold_result:
                    logger.warning(f"[ACPX-V2]   Some pages failed to scaffold, but continuing...")
                # print("🔴 ACPX-V2-STEP4-DONE: Pages scaffolded")
            except Exception as e:
                # print(f"🔴 ACPX-V2-STEP4-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                return {"success": False, "message": f"Scaffolding failed: {str(e)}"}

            # Step 5: Build ACPX prompt using manifest pages
            try:
                # print("🔴 ACPX-V2-STEP5-PROMPT: Building ACPX prompt")
                logger.info(f"[ACPX-V2] Step 5: Building ACPX prompt (using manifest pages)...")
                prompt = await self._build_acpx_prompt(goal_description)
                # print(f"🔴 ACPX-V2-STEP5-PROMPT-DONE: Prompt built, length={len(prompt)}")
                # print("=" * 60)
                # print("🔴 ACPX_PROMPT_START:")
                # print(prompt[:2000] if len(prompt) > 2000 else prompt)
                # if len(prompt) > 2000:
                #     print(f"... (truncated, total {len(prompt)} chars)")
                # # print("🔴 ACPX_PROMPT_END")
                # print("=" * 60)
            except Exception as e:
                # print(f"🔴 ACPX-V2-STEP5-PROMPT-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                return {"success": False, "message": f"Failed to build ACPX prompt: {str(e)}"}

            # Step 6: Run ACPX with timeout protection
            try:
                print("=" * 60)
                print("PHASE_9_APPLY")
                logger.info(f"[ACPX-V2] Step 5b: Running ACPX with timeout protection...")
                
                # Build command: acpx --format quiet claude exec "<prompt>"
                # cwd is set in Popen, not in command args
                cmd = [
                    "acpx",
                    "--format", "quiet",
                    "claude",
                    "exec",
                    str(prompt)
                ]
                
                HARD_TIMEOUT = 600  # 10 minutes max

                logger.info(f"[ACPX-V2]   Command: acpx --format quiet claude exec <prompt>")
                logger.info(f"[ACPX-V2]   Working directory: {self.frontend_src_path}")
                logger.info(f"[ACPX-V2]   Hard timeout: {HARD_TIMEOUT} seconds")

                # Robust debug logging
                print("ACPX CMD:", " ".join(cmd[:4]) + " <prompt>")
                print("[ACPX] cwd:", str(self.frontend_src_path))
                print("[ACPX] running: acpx --format quiet claude exec (with timeout)")

                import os
                import signal
                
                # Use Popen with process group for clean timeout handling
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    cwd=str(self.frontend_src_path),
                    start_new_session=True  # new process group
                )
                
                watchdog_killed = False
                
                try:
                    # Use communicate with timeout for clean output capture
                    stdout_output, stderr_output = process.communicate(timeout=HARD_TIMEOUT)
                except subprocess.TimeoutExpired:
                    # Kill entire process group (not just parent PID)
                    logger.error(f"[ACPX-V2] 🔴 TIMEOUT: Hard timeout exceeded ({HARD_TIMEOUT}s) — killing process group")
                    print(f"🔴 ACPX-V2-TIMEOUT: Killing process group {process.pid}")
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except (ProcessLookupError, OSError):
                        pass  # Process already dead
                    # Drain pipes after kill
                    stdout_output, stderr_output = process.communicate()
                    watchdog_killed = True
                
                return_code = process.returncode

                # Robust debug logging after execution
                print("ACPX RETURN CODE:", return_code)
                print("ACPX STDOUT:", stdout_output[:500] if stdout_output else "(empty)")
                print("ACPX STDERR:", stderr_output[:500] if stderr_output else "(empty)")
                
                # Handle timeout kills
                if watchdog_killed:
                    self.snapshot_manager.rollback_and_cleanup()
                    result = {
                        "success": False,
                        "message": f"ACPX hard timeout exceeded ({HARD_TIMEOUT}s) — process killed",
                        "rollback": True
                    }
                    return result

                # Tolerant error handling: ignore harmless JSON-RPC notification errors
                should_fail = True
                if "session/update" in stderr_output and "Invalid params" in stderr_output:
                    logger.warning("[ACPX] Ignoring JSON-RPC notification error (session/update Invalid params)")
                    should_fail = False

                if return_code != 0 and should_fail:
                    logger.error(f"[ACPX] ACPX execution failed (code {return_code})")
                    logger.error(f"[ACPX] stderr: {stderr_output[:1000]}")
                    raise RuntimeError(f"ACPX execution failed (code {return_code}): {stderr_output}")

                # Verify edits were actually produced
                edited_files = list(self.frontend_src_path.glob("**/*.tsx"))
                if not edited_files:
                    logger.error("[ACPX] ACPX produced no edits - no .tsx files found")
                    raise RuntimeError("ACPX produced no edits")

                logger.info(f"[ACPX-V2] ACPX subprocess completed successfully")
                logger.info(f"[ACPX-V2]   Return code: {return_code}")
                logger.info(f"[ACPX-V2]   Edited files: {len(edited_files)}")
                logger.info(f"[ACPX-V2]   Stdout length: {len(stdout_output)} chars")
                logger.info(f"[ACPX-V2]   Stderr length: {len(stderr_output)} chars")

                # print("🔴 ACPX-V2-STEP5B-EXEC-DONE: ACPX CLI completed")

            except Exception as e:
                # print(f"🔴 ACPX-V2-STEP5B-EXEC-ERROR: {type(e).__name__}: {str(e)}")
                logger.error(f"[ACPX-V2] ACPX execution error: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                self.snapshot_manager.rollback_and_cleanup()
                return {"success": False, "message": f"ACPX execution failed: {str(e)}"}

            # Step 6: Capture filesystem state AFTER ACPX
            try:
                # print("🔴 ACPX-V2-STEP6: Capturing filesystem state after ACPX")
                logger.info(f"[ACPX-V2] Step 6: Capturing filesystem state after ACPX...")
                hashes_after = FilesystemSnapshot.get_file_hashes(self.frontend_src_path)
                logger.info(f"[ACPX-V2]   Found {len(hashes_after)} files after ACPX")
                # print("🔴 ACPX-V2-STEP6-DONE: Filesystem state captured after ACPX")
            except Exception as e:
                # print(f"🔴 ACPX-V2-STEP6-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                self.snapshot_manager.rollback_and_cleanup()
                return {"success": False, "message": f"Failed to capture post-ACPX state: {str(e)}"}

            # Step 7: Compute changes (filesystem diff)
            try:
                # print("🔴 ACPX-V2-STEP7: Computing filesystem diff")
                logger.info(f"[ACPX-V2] Step 7: Computing filesystem diff...")
                diff = FilesystemSnapshot.compute_diff(hashes_before, hashes_after)

                files_added = diff['added']
                files_removed = diff['removed']
                files_modified = diff['modified']

                logger.info(f"[ACPX-V2]   Files added: {len(files_added)}")
                # print(f"🔴 FILES_ADDED: {files_added}")
                for f in files_added[:10]:
                    logger.info(f"[ACPX-V2]     + {f}")
                if len(files_added) > 10:
                    logger.info(f"[ACPX-V2]     ... and {len(files_added) - 10} more")

                logger.info(f"[ACPX-V2]   Files removed: {len(files_removed)}")
                # print(f"🔴 FILES_REMOVED: {files_removed}")
                for f in files_removed[:10]:
                    logger.info(f"[ACPX-V2]     - {f}")
                if len(files_removed) > 10:
                    logger.info(f"[ACPX-V2]     ... and {len(files_removed) - 10} more")

                logger.info(f"[ACPX-V2]   Files modified: {len(files_modified)}")
                # print(f"🔴 FILES_MODIFIED: {files_modified}")
                for f in files_modified[:10]:
                    logger.info(f"[ACPX-V2]     ~ {f}")
                if len(files_modified) > 10:
                    logger.info(f"[ACPX-V2]     ... and {len(files_modified) - 10} more")

                # print(f"🔴 ACPX-V2-STEP7-DONE: Diff computed - Added={len(files_added)}, Removed={len(files_removed)}, Modified={len(files_modified)}")
            except Exception as e:
                # print(f"🔴 ACPX-V2-STEP7-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                self.snapshot_manager.rollback_and_cleanup()
                return {"success": False, "message": f"Failed to compute diff: {str(e)}"}

            # Step 8: Validate file limits
            try:
                # print("🔴 ACPX-V2-STEP8: Validating file limits")
                logger.info(f"[ACPX-V2] Step 8: Validating file limits...")
                if len(files_added) > self.max_new_files:
                    logger.error(f"[ACPX-V2] ❌ File limit exceeded: {len(files_added)} > {self.max_new_files}")
                    # print("🔴 ACPX-V2-STEP8-ERROR: File limit exceeded, rolling back")
                    self.snapshot_manager.rollback_and_cleanup()
                    result = {
                        "success": False,
                        "message": f"File limit exceeded: {len(files_added)} new files, max {self.max_new_files} allowed",
                        "rollback": True
                    }
                    # print(f"🔴 ACPX-V2-RETURN: Success={result.get('success')}, Added={result.get('files_added', 0)}, Modified={result.get('files_modified', 0)}")
                    return result
                logger.info(f"[ACPX-V2]   ✓ File limit OK ({len(files_added)}/{self.max_new_files})")
                # print("🔴 ACPX-V2-STEP8-DONE: File limits validated")
            except Exception as e:
                # print(f"🔴 ACPX-V2-STEP8-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                self.snapshot_manager.rollback_and_cleanup()
                return {"success": False, "message": f"File limit validation failed: {str(e)}"}

            # Step 9: Validate paths
            try:
                # print("🔴 ACPX-V2-STEP9: Validating paths")
                logger.info(f"[ACPX-V2] Step 9: Validating paths...")
                for file_path in files_added + files_removed:
                    # file_path is already a relative path string from compute_diff
                    # Convert to string in case it's a Path object
                    rel_path = str(file_path) if not isinstance(file_path, str) else file_path
                    # print(f"🔴 ACPX-V2-STEP9-CHECK: Validating '{rel_path}'")
                    allowed, reason = self.validator.is_path_allowed(rel_path)
                    if not allowed:
                        logger.error(f"[ACPX-V2] ❌ Path validation failed for '{rel_path}': {reason}")
                        # print(f"🔴 ACPX-V2-STEP9-ERROR: Path validation failed for '{rel_path}': {reason}")
                        # print(f"🔴 ACPX-V2-STEP9-ERROR: Rolling back to snapshot")
                        self.snapshot_manager.rollback_and_cleanup()
                        result = {
                            "success": False,
                            "message": f"Path validation failed: {reason}",
                            "rollback": True
                        }
                        # print(f"🔴 ACPX-V2-RETURN: Success={result.get('success')}, Added={result.get('files_added', 0)}, Modified={result.get('files_modified', 0)}")
                        return result
                logger.info(f"[ACPX-V2]   ✓ All paths valid")
                # print("🔴 ACPX-V2-STEP9-DONE: All paths validated")
            except Exception as e:
                # print(f"🔴 ACPX-V2-STEP9-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                self.snapshot_manager.rollback_and_cleanup()
                return {"success": False, "message": f"Path validation failed: {str(e)}"}

            # Step 10: Enforce page guardrails (BEFORE build to prevent routing issues)
            try:
                # print("🔴 ACPX-V2-STEP10: Enforcing page guardrails")
                logger.info(f"[ACPX-V2] Step 10: Enforcing page guardrails (BEFORE build)...")
                unauthorized_removed = self._enforce_page_guardrails()

                if unauthorized_removed > 0:
                    logger.info(f"[ACPX-V2]   ⚠️  Removed {unauthorized_removed} unauthorized page(s)")
                    # print(f"🔴 ACPX-V2-STEP10-INFO: Removed {unauthorized_removed} unauthorized pages")
                else:
                    logger.info(f"[ACPX-V2]   ✓ All pages authorized")
                # print("🔴 ACPX-V2-STEP10-DONE: Page guardrails enforced")
            except Exception as e:
                # print(f"🔴 ACPX-V2-STEP10-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                # Don't rollback on guardrail errors, just log
                logger.warning(f"[ACPX-V2] Guardrail enforcement failed but continuing: {str(e)}")

            # Step 10.5: FIX ROUTING - Force Dashboard as default route with Layout wrapper
            try:
                # print("🔴 ACPX-V2-STEP10B: Fixing routing (programmatic)")
                logger.info("[ACPX-V2] Step 10.5: Fixing routing programmatically...")
                
                # Determine default page
                default_page = list(self.allowed_pages)[0] if self.allowed_pages else "Dashboard"
                app_tsx_path = self.frontend_src_path / "App.tsx"
                
                if app_tsx_path.exists():
                    content = app_tsx_path.read_text()
                    original_content = content
                    
                    # print(f"🔴 ACPX-V2-STEP10B-DEBUG: Original content length = {len(content)}")
                    # print(f"🔴 ACPX-V2-STEP10B-DEBUG: Looking for routes at '/'")
                    
                    # Count routes at "/" before fix
                    routes_at_root = re.findall(r'<Route\s+path="/"', content)
                    # print(f"🔴 ACPX-V2-STEP10B-DEBUG: Found {len(routes_at_root)} routes at '/' before fix")
                    
                    # Fix 1: Remove ALL routes at "/" (duplicates cause blank page)
                    # Pattern matches: <Route path="/" element={<Welcome />} />
                    # Also matches: <Route path="/" element={<Dashboard />}/>
                    # Handles inline routes (multiple on same line)
                    # IMPROVED: Handle more variations including self-closing elements
                    content = re.sub(
                        r'<Route\s+path="/"\s+element=\{<[A-Za-z]+\s*/?>\s*\}\s*/>',
                        '',
                        content
                    )
                    # Also handle routes with multi-word components like <DocumentEditor />
                    content = re.sub(
                        r'<Route\s+path="/"\s+element=\{<[A-Za-z]+\s*/?\s*\}\s*/?>',
                        '',
                        content
                    )
                    
                    # Verify removal
                    routes_at_root_after = re.findall(r'<Route\s+path="/"', content)
                    # print(f"🔴 ACPX-V2-STEP10B-DEBUG: Found {len(routes_at_root_after)} routes at '/' after removal")
                    
                    # Fix 2: Remove any /dashboard route (will be at "/" instead)
                    # IMPROVED: Handle more variations
                    content = re.sub(
                        r'<Route\s+path="/dashboard"\s+element=\{<[A-Za-z]+\s*/?\s*\}\s*/?>',
                        '',
                        content
                    )
                    
                    # Fix 3: Check if Layout wrapper exists
                    has_layout = '<Route element={<Layout />' in content or '<Route element={<Layout/>' in content
                    # print(f"🔴 ACPX-V2-STEP10B-DEBUG: Layout wrapper exists = {has_layout}")
                    
                    if has_layout:
                        # Insert "/" route inside existing Layout wrapper
                        layout_pattern = r'(<Route\s+element=\{<Layout\s*/>\}>\s*\n)'
                        layout_match = re.search(layout_pattern, content)
                        if layout_match:
                            insert_pos = layout_match.end()
                            default_route = f'          <Route path="/" element={{<{default_page} />}} />\n'
                            content = content[:insert_pos] + default_route + content[insert_pos:]
                            logger.info(f"[ACPX-V2]   Added {default_page} route inside Layout wrapper")
                    else:
                        # No Layout wrapper - wrap all routes with Layout
                        # Find the Routes content (handles both inline and multiline)
                        routes_pattern = r'<Routes>(.*?)</Routes>'
                        routes_match = re.search(routes_pattern, content, re.DOTALL)
                        
                        if routes_match:
                            routes_content = routes_match.group(1).strip()
                            
                            # Build new routes with Layout wrapper and proper formatting
                            # Parse individual routes and format them nicely
                            route_pattern = r'<Route\s+[^>]+/>'
                            individual_routes = re.findall(route_pattern, routes_content)
                            
                            # Format routes with Layout wrapper
                            formatted_routes = '\n        '.join([f'{r}' for r in individual_routes])
                            
                            new_routes = f'''<Route element={{<Layout />}}>
          <Route path="/" element={{<{default_page} />}} />
        {formatted_routes}
      </Route>'''
                            
                            # Replace the entire Routes content
                            content = content[:routes_match.start(1)] + new_routes + content[routes_match.end(1):]
                            logger.info(f"[ACPX-V2]   Added Layout wrapper with {default_page} at /")
                    
                    if content != original_content:
                        app_tsx_path.write_text(content)
                        logger.info(f"[ACPX-V2]   ✓ Fixed routing: {default_page} is now at / with Layout")
                        # print(f"🔴 ACPX-V2-STEP10B-DONE: Routing fixed - {default_page} at / with Layout")
                    else:
                        logger.info("[ACPX-V2]   Routing appears correct")
                        # print("🔴 ACPX-V2-STEP10B-DONE: Routing already correct")
                else:
                    logger.warning("[ACPX-V2]   App.tsx not found, skipping routing fix")
                    # print("🔴 ACPX-V2-STEP10B-SKIP: App.tsx not found")
                    
            except Exception as e:
                # print(f"🔴 ACPX-V2-STEP10B-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                logger.warning(f"[ACPX-V2] Routing fix failed but continuing: {str(e)}")

            # Step 10.6: Fix Layout components - Replace {children} with <Outlet />
            try:
                # print("🔴 ACPX-V2-STEP10C: Fixing Layout components (Outlet)")
                logger.info("[ACPX-V2] Step 10.6: Fixing Layout components to use Outlet...")
                
                # Find all Layout files
                layout_patterns = [
                    self.frontend_src_path / "layout" / "Layout.tsx",
                    self.frontend_src_path / "layouts" / "Layout.tsx",
                    self.frontend_src_path / "app" / "layouts" / "AppLayout.tsx",
                ]
                
                layout_files = [p for p in layout_patterns if p.exists()]
                # Also search for any file with "Layout" in the name
                for layout_dir in ["layout", "layouts", "app/layouts"]:
                    layout_path = self.frontend_src_path / layout_dir
                    if layout_path.exists():
                        layout_files.extend(layout_path.glob("*Layout*.tsx"))
                
                layout_files = list(set(layout_files))  # Remove duplicates
                
                for layout_file in layout_files:
                    try:
                        content = layout_file.read_text()
                        original = content
                        
                        # Fix 1: Add Outlet import if missing
                        if "Outlet" not in content and "from 'react-router-dom'" in content:
                            content = re.sub(
                                r"import\s+\{([^}]+)\}\s+from\s+'react-router-dom'",
                                r"import {\1, Outlet } from 'react-router-dom'",
                                content
                            )
                        elif "Outlet" not in content:
                            # Add import at top after other imports
                            import_line = "import { Outlet } from 'react-router-dom';\n"
                            # Find last import line
                            import_match = re.search(r"(^import.*?;[\s]*)+", content, re.MULTILINE)
                            if import_match:
                                insert_pos = import_match.end()
                                content = content[:insert_pos] + import_line + content[insert_pos:]
                        
                        # Fix 2: Remove children prop from function signature
                        content = re.sub(
                            r'(\bfunction\s+\w+Layout\s*)\(\s*\{\s*children\s*(?::[^}]+)?\s*\}\s*:\s*[^)]+\)',
                            r'\1()',
                            content
                        )
                        content = re.sub(
                            r'(\bfunction\s+\w+Layout\s*)\(\s*\{\s*children\s*\}\s*:\s*\{\s*children:\s*React\.ReactNode\s*\}\s*\)',
                            r'\1()',
                            content
                        )
                        
                        # Fix 3: Remove children interface
                        content = re.sub(
                            r'interface\s+\w*LayoutProps\s*\{\s*children\s*(?::\s*React\.ReactNode)?\s*\}\s*\n?',
                            '',
                            content,
                            flags=re.IGNORECASE
                        )
                        
                        # Fix 4: Replace {children} with <Outlet />
                        content = re.sub(r'\{children\}', '<Outlet />', content)
                        content = re.sub(r'\{\s*children\s*\}', '<Outlet />', content)
                        
                        if content != original:
                            layout_file.write_text(content)
                            logger.info(f"[ACPX-V2]   ✓ Fixed {layout_file.name}: replaced {{children}} with <Outlet />")
                            # print(f"🔴 ACPX-V2-STEP10C-FIX: {layout_file.name} - children → Outlet")
                    
                    except Exception as e:
                        logger.warning(f"[ACPX-V2]   Failed to fix {layout_file}: {e}")
                        # print(f"🔴 ACPX-V2-STEP10C-WARN: Failed to fix {layout_file.name}: {e}")
                
                # print("🔴 ACPX-V2-STEP10C-DONE: Layout components fixed")
                
            except Exception as e:
                # print(f"🔴 ACPX-V2-STEP10C-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                logger.warning(f"[ACPX-V2] Layout fix failed but continuing: {str(e)}")

            # Step 11: Build gate skipped - build handled by infrastructure pipeline
            try:
                # print("🔴 ACPX-V2-STEP11: Build gate skipped")
                logger.info("[ACPX-V2] Build gate skipped — build handled by infrastructure pipeline")
                # print("🔴 ACPX-V2-STEP11-DONE: Build gate skipped")
            except Exception as e:
                # print(f"🔴 ACPX-V2-STEP11-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                # Don't fail on skip errors
                logger.warning(f"[ACPX-V2] Build gate skip had issues but continuing: {str(e)}")

            # Step 12: Success - cleanup snapshot (in finally to prevent leaks)
            # Cleanup moved to finally block below

            # Step 13: Post-process - Detect empty/placeholder pages (logging only)
            try:
                # print("🔴 ACPX-V2-STEP13: Checking for empty pages")
                logger.info("[ACPX-V2] Step 13: Checking for empty/placeholder pages...")
                
                empty_pages = []
                pages_dir = self.frontend_src_path / "pages"
                
                if pages_dir.exists():
                    for page_file in pages_dir.glob("*.tsx"):
                        content = page_file.read_text()
                        
                        # Check for placeholder content
                        is_empty = (
                            len(content) < 500 or  # Very short file
                            "Page content will be generated by AI" in content or
                            "placeholder" in content.lower() or
                            content.strip().endswith("return <div></div>;") or
                            content.strip().endswith("return null;")
                        )
                        
                        if is_empty:
                            page_name = page_file.stem
                            empty_pages.append(page_name)
                            logger.warning(f"[ACPX-V2]   Empty/placeholder page detected: {page_name}")
                            # print(f"🔴 ACPX-V2-STEP13-EMPTY: {page_name}.tsx is empty/placeholder")
                
                if empty_pages:
                    logger.warning(f"[ACPX-V2]   Found {len(empty_pages)} empty pages: {empty_pages}")
                    # print(f"🔴 ACPX-V2-STEP13-EMPTY-COUNT: {len(empty_pages)} empty pages detected")
                    logger.warning(f"[ACPX-V2]   Empty pages should be populated by ACPX in single execution mode")
                else:
                    logger.info("[ACPX-V2]   ✓ All pages have content")
                    # print("🔴 ACPX-V2-STEP13-DONE: All pages have content")
                    
            except Exception as e:
                # print(f"🔴 ACPX-V2-STEP13-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                logger.warning(f"[ACPX-V2] Empty page check failed but continuing: {str(e)}")

            # Final result
            result = {
                "success": True,
                "message": "ACPX changes applied successfully (build will run in infrastructure pipeline)",
                "files_added": len(files_added),
                "files_modified": len(files_modified),
                "files_removed": len(files_removed),
                "build_output": "Build skipped - handled by infrastructure pipeline",
                "rollback": False
            }
            # print(f"🔴 ACPX-V2-RETURN: Success={result.get('success')}, Added={result.get('files_added')}, Modified={result.get('files_modified')}")
            return result

        except Exception as e:
            # Global exception handler
            # print(f"🔴 ACPX-V2-FATAL-ERROR: {type(e).__name__}: {str(e)}")
            # print("🔴 ACPX-V2-FATAL-ERROR: Traceback:")
            traceback.print_exc()
            # print("🔴 ACPX-V2-FATAL-ERROR: Returning error result")

            # Attempt to rollback if possible
            try:
                self.snapshot_manager.rollback_and_cleanup()
            except Exception as rollback_error:
                # print(f"🔴 ACPX-V2-FATAL-ERROR: Rollback also failed: {rollback_error}")
                pass

            return {
                "success": False,
                "message": f"FATAL ERROR in apply_changes_via_acpx: {str(e)}",
                "files_added": 0,
                "files_modified": 0,
                "files_removed": 0,
                "rollback": False
            }
        finally:
            # Step 12: Always cleanup snapshot to prevent leaks
            try:
                # print("🔴 ACPX-V2-STEP12: Cleaning up snapshot (finally)")
                logger.info(f"[ACPX-V2] Step 12: Cleanup snapshot (finally)...")
                self.snapshot_manager.cleanup_snapshot()
                # print("🔴 ACPX-V2-STEP12-DONE: Snapshot cleaned up")
            except Exception as e:
                # print(f"🔴 ACPX-V2-STEP12-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                # Don't fail on cleanup errors
                logger.warning(f"[ACPX-V2] Snapshot cleanup failed but returning success: {str(e)}")

    async def _extract_required_pages_from_prompt(self, goal_description: str) -> List[str]:
        """
        Extract required pages from goal description using AI inference.

        Detection priority: Groq AI → Default pages

        Args:
            goal_description: Goal for changes

        Returns:
            List of required page names
        """
        # # Return cached pages if available (prevents double LLM calls)
        # if self._cached_pages is not None:
        #     logger.info("[Planner] Returning cached page inference")
        #     # print(f"🔴 PLANNER-CACHE-HIT: Returning cached pages = {self._cached_pages}")
        #     return self._cached_pages
        
        # print("🔴 PLANNER-CACHE-MISS: No cached pages, performing fresh inference")

        logger.info("[Planner] Extracting required pages from prompt...")
        print("\n" + "="*60)
        print("🔍 PAGE INFERENCE START")
        print("="*60)
        # print(f"🔴 PLANNER-INPUT: {goal_description[:200]}...")

        required_pages = []

        # Step 1: Try Groq AI inference
        try:
            from groq_service import GroqService
            # print("🔴 PLANNER-STEP1: Attempting Groq AI inference...")
            groq = GroqService()
                    
            inferred_pages = await groq.infer_pages(goal_description)
            # print(f"🔴 PLANNER-GROQ-RAW: Inferred pages = {inferred_pages}")
            if inferred_pages and len(inferred_pages) >= 3:
                required_pages = inferred_pages
                logger.info(f"[Planner] Groq inferred pages: {inferred_pages}")
                print(f"✅ PLANNER-GROQ-SUCCESS: Using {len(inferred_pages)} pages: {inferred_pages}")
            else:
                print(f"⚠️  PLANNER-GROQ-INSUFFICIENT: Got {len(inferred_pages) if inferred_pages else 0} pages, need >= 3")
        except Exception as e:
            logger.warning(f"[Planner] Groq inference failed: {e}")
            print(f"❌ PLANNER-GROQ-ERROR: {type(e).__name__}: {str(e)}")

        # Step 2: Fallback to default pages
        if len(required_pages) < 3:
            required_pages = ["Dashboard", "Settings", "Overview"]
            logger.info(f"[Planner] Using default pages: {required_pages}")
            print(f"⚠️  PLANNER-DEFAULT: Using default pages = {required_pages}")

        # Remove duplicates while preserving order
        required_pages = list(dict.fromkeys(required_pages))

        print(f"🎯 PLANNER-FINAL: Pages = {required_pages}")
        print(f"📊 PLANNER-COUNT: {len(required_pages)} pages detected")
        print("="*60)
        print("🔍 PAGE INFERENCE COMPLETE")
        print("="*60 + "\n")

        # Phase 9: Store allowed pages whitelist for guardrails
        self.allowed_pages = set(required_pages)
        logger.info(f"[Phase9] Allowed pages: {required_pages}")
        # print(f"🔴 PHASE9-ALLOWED: Whitelist set to: {sorted(self.allowed_pages)}")

        # Planner logging
        logger.info(f"[Planner] Description: {goal_description}")
        logger.info(f"[Planner] Detected pages: {required_pages}")

        # Cache pages to prevent double LLM calls
        self._cached_pages = required_pages

        return required_pages

    async def _build_acpx_prompt(self, goal_description: str) -> str:
        """
        Build ACPX prompt with explicit required artifacts and completion checklist.

        Args:
            goal_description: Goal for changes

        Returns:
            Prompt string for ACPX
        """
        # Extract required pages from goal description
        required_pages = await self._extract_required_pages_from_prompt(goal_description)

        # print(f"🔴 PLANNER-OUTPUT: Required pages = {required_pages}")
        # print(f"🔴 PLANNER-OUTPUT: Page count = {len(required_pages)}")

        # Build required artifacts list
        required_pages_list = required_pages

        required_pages_str = "\n".join([f"- src/pages/{page}.tsx" for page in required_pages_list])

        # Phase 4: Build page specs section (NEW)
        page_specs_section = self._build_page_specs_section(required_pages)

        # Determine which page should be the default route
        default_page = required_pages_list[0] if required_pages_list else "Dashboard"

        return f"""You are editing a React + Vite + TypeScript SaaS application.

Project Name: {self.project_name}
Project Description: {goal_description}

🎨 UI/UX DESIGN REFERENCE - FOLLOW THESE STANDARDS 🎨

For ALL UI/UX design decisions, use the ui-ux-pro-max skill:
📖 Skill Name: ui-ux-pro-max
🔗 GitHub: https://github.com/nextlevelbuilder/ui-ux-pro-max-skill
💡 Invoke with: /ui-ux-pro-max [your request]

Examples:
- /ui-ux-pro-max review my dashboard component
- /ui-ux-pro-max create a glassmorphism button
- /ui-ux-pro-max improve the accessibility of my form

This skill provides expert guidance on:
- Modern UI component patterns
- Responsive design best practices
- Accessibility standards (WCAG 2.1)
- Color theory and typography
- Layout composition and spacing
- Interactive states and micro-interactions
- Mobile-first design approach
- Professional UI polish techniques

Before implementing ANY UI component:
1. Consider the UI/UX Pro Max principles
2. Apply modern design patterns (not outdated Bootstrap-style layouts)
3. Ensure mobile-responsive implementation
4. Use proper visual hierarchy and spacing
5. Implement smooth transitions and micro-interactions
6. Follow accessibility best practices

YOUR TASK

Transform the existing template into a production-ready application based on the project description above.

🚨🚨🚨 CRITICAL ROUTING FIX - MUST DO FIRST 🚨🚨🚨

BEFORE YOU DO ANYTHING ELSE, FIX THE ROUTING:

1. READ src/App.tsx
2. FIND the Welcome route at path="/"
3. DELETE or REPLACE it with {default_page} at path="/"

REQUIRED STATE (FIXED):
```tsx
<Routes>
  <Route element={{<Layout />}}>
    <Route path="/" element={{<{default_page} />}} />  ← ONLY ONE route at "/"
    <Route path="/team" element={{<Team />}} />
    ...
  </Route>
</Routes>
```

⚠️ ROUTING RULES (MANDATORY):
1. DELETE ALL routes with path="/" (there may be MULTIPLE duplicates)
2. Keep only ONE route at path="/" for {default_page}
3. All routes MUST be inside <Route element={{<Layout />}}> wrapper
4. If no Layout wrapper exists, ADD IT
5. DO NOT leave Welcome at path="/"
6. DO NOT create duplicate routes at path="/"

FAILURE TO FIX ROUTING = BROKEN APP (blank page)

Verify routing is correct BEFORE creating pages!

PHASE 9 STRICT PAGE GENERATION RULES (ENFORCED)

⚠️  CRITICAL: EXACT PAGE CREATION REQUIRED ⚠️

1. ONLY create the pages listed below:
{required_pages_str}

2. File names must match EXACTLY:
   - Use this pattern: src/pages/{{PageName}}.tsx
   - Examples: src/pages/Dashboard.tsx, src/pages/Contacts.tsx, src/pages/Settings.tsx
   - DO NOT add "Page" suffix: ✗ DashboardPage.tsx → ✓ Dashboard.tsx
   - DO NOT add "Overview" suffix: ✗ AnalyticsOverview.tsx → ✓ Analytics.tsx
   - DO NOT use variations: ✗ ReportsPage.tsx → ✓ Reports.tsx

3. ABSOLUTELY FORBIDDEN:
   - DO NOT create any additional pages beyond the list
   - DO NOT create variations like: Account.tsx, Activity.tsx, Users.tsx, Team.tsx, Billing.tsx
   - DO NOT rename pages - use exact names from REQUIRED PAGES list
   - DO NOT generate default SaaS pages when explicit pages are provided

4. FINAL VERIFICATION CHECKLIST:
   Before marking task complete, verify:
   - [ ] ROUTING FIXED: Welcome route removed, {default_page} at "/" (ONLY ONE)
   - [ ] ROUTING FIXED: All routes inside Layout wrapper
   - [ ] ONLY pages from REQUIRED PAGES list exist in src/pages/
   - [ ] NO unauthorized pages were created
   - [ ] All required pages are complete
   - [ ] File names match exactly with REQUIRED PAGES list

PAGE SPECIFICATIONS (Phase 4 - Enhanced UI Quality)
{page_specs_section}

⚠️ CRITICAL: NAVIGATION MENU REQUIREMENTS ⚠️

YOU MUST CREATE OR UPDATE A NAVIGATION MENU THAT IS MOBILE RESPONSIVE:

1. CREATE/UPDATE src/layout/Navbar.tsx or src/components/Navbar.tsx with:
   - Desktop view: Horizontal menu with links to all required pages
   - Mobile view: Hamburger menu (☰) that toggles navigation
   - Use React state for mobile menu toggle: `const [isOpen, setIsOpen] = useState(false)`
   - Include links to: {', '.join(required_pages_list)}
   - Use Lucide icons for menu icons: Menu, X, Home, Settings, etc.

2. MOBILE RESPONSIVE REQUIREMENTS:
   - Use Tailwind responsive classes: `hidden md:flex` for desktop menu
   - Hamburger button visible on mobile: `md:hidden`
   - Mobile menu with full-screen overlay or slide-in sidebar
   - Touch-friendly tap targets (min 44px height)
   - Smooth transitions for menu open/close

3. INTEGRATE WITH LAYOUT:
   - Import Navbar in Layout.tsx
   - Place Navbar in Layout header section
   - Ensure Navbar works with existing Layout structure

4. NAVIGATION LINKS MUST INCLUDE:
   - All required pages: {', '.join(required_pages_list)}
   - Active link highlighting (use NavLink from react-router-dom)
   - Proper routing to each page

EXAMPLE NAVBAR STRUCTURE:
```tsx
import {{ useState }} from 'react';
import {{ NavLink }} from 'react-router-dom';
import {{ Menu, X }} from 'lucide-react';

export default function Navbar() {{
  const [isOpen, setIsOpen] = useState(false);
  
  const links = [
    {{ to: '/', label: '{required_pages_list[0] if required_pages_list else 'Dashboard'}', icon: Home }},
    // ... add other page links
  ];

  return (
    <nav className="bg-white border-b">
      {{/* Desktop Menu */}}
      <div className="hidden md:flex">
        {{links.map(link => <NavLink key={{link.to}} to={{link.to}}>...)}}
      </div>
      
      {{/* Mobile Hamburger */}}
      <button className="md:hidden" onClick={{() => setIsOpen(!isOpen)}}>
        {{isOpen ? <X /> : <Menu />}}
      </button>
      
      {{/* Mobile Menu Overlay */}}
      {{isOpen && (
        <div className="md:hidden fixed inset-0 bg-white z-50">
          {{/* Mobile menu links */}}
        </div>
      )}}
    </nav>
  );
}}
```

⚠️ NAVIGATION IS NOT OPTIONAL - Every app MUST have a working mobile-responsive menu!

CHECKLIST (complete in order)
1. Fix routing — remove Welcome at "/", single {default_page} route at "/" inside Layout wrapper
2. Create src/layout/Navbar.tsx — mobile hamburger menu, NavLink to all required pages
3. Integrate Navbar into Layout.tsx header
4. Create each required page one at a time (exact filenames):
{required_pages_str}
5. Verify no unauthorized pages exist in src/pages/
6. Run npm run build and confirm it succeeds

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

DO NOT modify:
- src/components/ui/ (UI primitives only)
- package.json, vite.config.*, node_modules
- backend files, .env files
- Do NOT change project architecture

TECHNICAL REQUIREMENTS

- Fix routing BEFORE creating pages
- Keep the code buildable (npm run build must succeed)
- Use existing UI components from src/components/ui/
- Follow existing code patterns and style
- Write clean, production-ready code
- Do not introduce placeholder content unless required
- Follow page specifications for professional UI
- Ensure all UI elements from page specs are implemented

⚠️ CRITICAL: LAYOUT COMPONENT RULES ⚠️

The project uses a Layout component with React Router nested routes.

App.tsx routing structure:
```tsx
<Routes>
  <Route element={{<Layout />}}>
    <Route path="/" element={{<Dashboard />}} />
    <Route path="/settings" element={{<Settings />}} />
    <Route path="*" element={{<NotFound />}} />
  </Route>
</Routes>
```

CRITICAL RULES:
1. Layout MUST use <Outlet />, NOT children prop
2. All page routes MUST be nested inside <Route element={{<Layout />}}>
3. Pages render at <Outlet />, not via children prop
4. Layout uses flex for full-screen layout with overflow handling

⚠️ CRITICAL: LINK/NAVIGATION COMPONENTS ⚠️

When creating navigation links, ALWAYS wrap multiple children in a single element:

❌ WRONG - Multiple children cause React.Children.only error:
```tsx
<Link to="/dashboard">
  <Icon />
  Dashboard
</Link>
```

✅ CORRECT - Single wrapper element:
```tsx
<Link to="/dashboard">
  <span className="flex items-center gap-2">
    <Icon />
    Dashboard
  </span>
</Link>
```

Same rule applies to: Button, NavLink, and any component expecting single child.

IMPLEMENTATION

Make your changes directly to files.

Do NOT request JSON output or any specific format.

Just implement the changes using your available tools.
"""

    def _build_page_templates_section(self, required_pages: List[str], goal_description: str) -> str:
        """
        Build page templates section for ACPX prompt.

        Args:
            required_pages: List of required page names
            goal_description: Project goal description

        Returns:
            Page templates section for prompt
        """
        template_sections = []

        for page_name in required_pages:
            template_content = get_page_template_for_prompt(page_name, goal_description)
            template_sections.append(template_content)

        return "\n".join(template_sections)

    def _build_page_specs_section(self, required_pages: List[str]) -> str:
        """
        Build page specifications section for ACPX prompt (Phase 4).

        Args:
            required_pages: List of required page names

        Returns:
            Page specs section for prompt
        """
        try:
            from page_specs import format_page_spec_list
            specs = format_page_spec_list(required_pages)
            specs_section = "\n".join(specs)
            logger.info(f"[Phase4] Page specs built for {len(required_pages)} pages")
            return specs_section
        except Exception as e:
            logger.error(f"[Phase4] Error loading page specs: {e}")
            # Fallback: return empty section
            return "\n## Page Specifications\n\nNote: Page specs not available, using page templates only.\n"

    def _enforce_page_guardrails(self) -> int:
        """
        Enforce page guardrails by removing unauthorized pages.

        Scans src/pages/ and removes any pages not in the allowed_pages whitelist.

        Returns:
            Number of unauthorized pages removed
        """
        pages_dir = self.frontend_src_path / "pages"

        if not pages_dir.exists():
            logger.warning(f"[Guardrail] Pages directory not found: {pages_dir}")
            return 0

        # Always allowed pages (system pages)
        always_allowed = {"NotFound", "Welcome", "_app", "_layout", "index", "Error", "Loading"}

        unauthorized_removed = 0

        for page_file in pages_dir.glob("*.tsx"):
            # Extract page name (remove .tsx extension)
            page_name = page_file.stem

            # Skip always-allowed pages
            if page_name in always_allowed:
                continue

            # Remove pages starting with conjunctions (e.g., "AndAudience", "OrSettings")
            conjunctions = ['And', 'Or', '&']
            if any(page_name.startswith(conj) for conj in conjunctions):
                logger.warning(f"[Guardrail] Removing page with leading conjunction: {page_name}")
                try:
                    page_file.unlink()
                    unauthorized_removed += 1
                except Exception as e:
                    logger.error(f"[Guardrail] Failed to remove {page_name}: {e}")
                    # Do not increment — file was NOT removed
                continue

            # Check if page is in allowed whitelist
            if page_name not in self.allowed_pages:
                logger.warning(f"[Guardrail] Removing unauthorized page: {page_name}")
                try:
                    page_file.unlink()
                    unauthorized_removed += 1
                except Exception as e:
                    logger.error(f"[Guardrail] Failed to remove {page_name}: {e}")
                    # Do not increment — file was NOT removed

        if unauthorized_removed > 0:
            logger.info(f"[Guardrail] Removed {unauthorized_removed} unauthorized page(s)")
            logger.info(f"[Guardrail] Remaining allowed pages: {sorted(self.allowed_pages)}")
        else:
            logger.info(f"[Guardrail] ✓ All pages are authorized")

        logger.info(f"[Phase9] Final validated pages: {sorted(self.allowed_pages)}")

        return unauthorized_removed



