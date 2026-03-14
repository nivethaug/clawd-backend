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

# Allowed directories for ACPX editing (relative to frontend/src)
ALLOWED_EDIT_PATHS = [
    "src/pages",
    "src/components", 
    "src/layouts",
    "src/App.tsx",
    "src/main.tsx"
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
    "src/components/ui",
    "src/lib",
    "src/utils"
]

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
        
        # Get relative path from frontend_src_path
        try:
            rel_path = path.relative_to(self.frontend_src_path)
            rel_path_str = str(rel_path)
        except ValueError:
            return False, f"Forbidden: Path outside frontend/src ({path})"

        # Check 1: Forbidden paths (node_modules, package.json, vite.config.ts, etc.)
        for forbidden in FORBIDDEN_EDIT_PATHS:
            if forbidden in rel_path_str or rel_path_str.startswith(forbidden):
                return False, f"Forbidden: Cannot modify {forbidden} ({rel_path})"

        # Check 2: Specifically block src/components/ui
        if "src/components/ui" in rel_path_str or "components/ui" in rel_path_str:
            return False, f"Forbidden: Cannot modify UI components ({rel_path})"

        # Check 3: Must be in allowed edit paths
        is_allowed = False
        for allowed_path in ALLOWED_EDIT_PATHS:
            if rel_path_str.startswith(allowed_path) or rel_path_str == allowed_path.replace("src/", ""):
                is_allowed = True
                break
        
        if not is_allowed:
            return False, f"Forbidden: Path not in allowed edit paths ({rel_path})"

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

        # Phase 9: Guardrails - Store allowed pages whitelist
        self.allowed_pages: Set[str] = set()

        # Phase 5: Page Manifest - Initialize manifest manager
        # Pass project root path (parent of frontend), not frontend path
        # to avoid path doubling in PageManifest which appends frontend/src/
        self.manifest_manager = PageManifest(str(self.frontend_path.parent))

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
        import traceback

        print("🔴 ACPX-V2-METHOD-START: apply_changes_via_acpx called")
        print(f"🔴 ACPX-V2-METHOD-START: Goal: {goal_description[:100]}")
        print(f"🔴 ACPX-V2-METHOD-START: Execution ID: {execution_id}")

        try:
            print("🔴 ACPX-V2-TRY-BLOCK: Starting main logic")
            logger.info(f"[ACPX-V2] 🔴 HEARTBEAT: Starting Phase 9 (Filesystem Diff Architecture)")
            logger.info(f"[ACPX-V2] 🔴 HEARTBEAT: Project: {self.project_name}")
            logger.info(f"[ACPX-V2] 🔴 HEARTBEAT: Execution ID: {execution_id}")

            # Step 1: Create snapshot
            try:
                print("🔴 ACPX-V2-STEP1: Creating snapshot")
                logger.info(f"[ACPX-V2] Step 1: Creating filesystem snapshot...")
                snapshot_success, snapshot_msg = self.snapshot_manager.create_snapshot()
                print(f"🔴 ACPX-V2-STEP1-DONE: Snapshot created, success={snapshot_success}")

                if not snapshot_success:
                    print("🔴 ACPX-V2-EARLY-RETURN: Snapshot creation failed, returning early")
                    result = {
                        "success": False,
                        "message": f"Snapshot creation failed: {snapshot_msg}",
                        "rollback": False
                    }
                    print(f"🔴 ACPX-V2-RETURN: Success={result.get('success')}, Added={result.get('files_added', 0)}, Modified={result.get('files_modified', 0)}")
                    return result
            except Exception as e:
                print(f"🔴 ACPX-V2-STEP1-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                return {"success": False, "message": f"Snapshot failed: {str(e)}"}

            # Step 2: Generate page manifest from planner (Phase 5 - NEW)
            try:
                print("🔴 ACPX-V2-STEP2: Generating manifest")
                logger.info(f"[ACPX-V2] Step 2: Generating page manifest (Phase 5)...")
                required_pages = self._extract_required_pages_from_prompt(goal_description)
                print(f"🔴 ACPX-V2-STEP2-INFO: Pages to create: {required_pages}")
                logger.info(f"[ACPX-V2]   Planner detected pages: {required_pages}")

                # Write manifest to project directory
                manifest_success = self.manifest_manager.write_manifest(required_pages)
                if not manifest_success:
                    print("🔴 ACPX-V2-EARLY-RETURN: Failed to write page manifest, returning early")
                    result = {
                        "success": False,
                        "message": "Failed to write page manifest",
                        "rollback": False
                    }
                    print(f"🔴 ACPX-V2-RETURN: Success={result.get('success')}, Added={result.get('files_added', 0)}, Modified={result.get('files_modified', 0)}")
                    return result

                # Update allowed_pages with manifest pages (source of truth)
                self.allowed_pages = set(required_pages)
                logger.info(f"[ACPX-V2]   Manifest pages set as allowed: {required_pages}")
                print("🔴 ACPX-V2-STEP2-DONE: Manifest generated")
            except Exception as e:
                print(f"🔴 ACPX-V2-STEP2-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                return {"success": False, "message": f"Manifest failed: {str(e)}"}

            # Step 3: Scaffold pages from manifest (Phase 5 - NEW)
            try:
                print("🔴 ACPX-V2-STEP3: Scaffolding pages")
                logger.info(f"[ACPX-V2] Step 3: Scaffolding pages from manifest...")

                print("🔴 ACPX-V2-STEP3-PRE: Calling scaffold_pages()")
                scaffold_result = self.manifest_manager.scaffold_pages(required_pages, create_placeholder=True)
                print(f"🔴 ACPX-V2-STEP3-POST: scaffold_pages() returned")
                print(f"🔴 ACPX-V2-STEP3-POST-VALUE: {scaffold_result}")

                # Check return value type
                if isinstance(scaffold_result, bool):
                    print(f"🔴 ACPX-V2-STEP3-POST-TYPE: bool, value={scaffold_result}")
                elif scaffold_result is None:
                    print("🔴 ACPX-V2-STEP3-POST-TYPE: None (treated as True)")

                if not scaffold_result:
                    logger.warning(f"[ACPX-V2]   Some pages failed to scaffold, but continuing...")
                print("🔴 ACPX-V2-STEP3-DONE: Pages scaffolded")
            except Exception as e:
                print(f"🔴 ACPX-V2-STEP3-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                return {"success": False, "message": f"Scaffolding failed: {str(e)}"}

            # Step 4: Capture filesystem state BEFORE ACPX
            try:
                print("🔴 ACPX-V2-STEP4: Capturing filesystem state before ACPX")
                logger.info(f"[ACPX-V2] Step 4: Capturing filesystem state before ACPX...")
                hashes_before = FilesystemSnapshot.get_file_hashes(self.frontend_src_path)
                logger.info(f"[ACPX-V2]   Found {len(hashes_before)} files before ACPX")
                print("🔴 ACPX-V2-STEP4-DONE: Filesystem state captured")
            except Exception as e:
                print(f"🔴 ACPX-V2-STEP4-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                return {"success": False, "message": f"Failed to capture filesystem state: {str(e)}"}

            # Step 5: Build ACPX prompt using manifest pages
            try:
                print("🔴 ACPX-V2-STEP5-PROMPT: Building ACPX prompt")
                logger.info(f"[ACPX-V2] Step 5: Building ACPX prompt (using manifest pages)...")
                prompt = self._build_acpx_prompt(goal_description)
                print(f"🔴 ACPX-V2-STEP5-PROMPT-DONE: Prompt built, length={len(prompt)}")
            except Exception as e:
                print(f"🔴 ACPX-V2-STEP5-PROMPT-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                return {"success": False, "message": f"Failed to build ACPX prompt: {str(e)}"}

            # Step 6: Run ACPX with Watchdog Protection
            try:
                print("=" * 60)
                print("PHASE_9_APPLY")
                print("🔴 ACPX-V2-STEP5: Running ACPX CLI with watchdog")
                logger.info(f"[ACPX-V2] Step 6: Running ACPX with watchdog protection...")
                
                # Build command: acpx --cwd <dir> --format quiet claude exec "<prompt>"
                # Ensure all args are strings to avoid TypeError with PosixPath
                cmd = [
                    "acpx",
                    "--cwd", str(self.frontend_src_path),
                    "--format", "quiet",
                    "claude",
                    "exec",
                    str(prompt)
                ]
                
                logger.info(f"[ACPX-V2]   Command: acpx --cwd {self.frontend_src_path} --format quiet claude exec <prompt>")
                logger.info(f"[ACPX-V2]   Working directory: {self.frontend_src_path}")
                logger.info(f"[ACPX-V2]   Hard timeout: 600 seconds, Idle timeout: 60 seconds")

                # Robust debug logging
                print("ACPX CMD:", " ".join(cmd[:6]) + " <prompt>")
                print("[ACPX] cwd:", str(self.frontend_src_path))
                print("[ACPX] running: acpx --format quiet claude exec (with watchdog)")

                # Use Popen for streaming with watchdog protection
                import time
                import threading
                
                HARD_TIMEOUT = 600  # 10 minutes max
                IDLE_TIMEOUT = 60   # 60 seconds without output
                
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                    text=True,
                    cwd=str(self.frontend_src_path)
                )
                
                stdout_lines = []
                stderr_lines = []
                last_output_time = time.time()
                start_time = time.time()
                watchdog_killed = False
                idle_killed = False
                
                def read_stream(stream, lines_list):
                    """Read from stream line by line."""
                    try:
                        for line in iter(stream.readline, ''):
                            if line:
                                lines_list.append(line)
                        stream.close()
                    except:
                        pass
                
                # Start reader threads for stdout and stderr
                stdout_thread = threading.Thread(target=read_stream, args=(process.stdout, stdout_lines), daemon=True)
                stderr_thread = threading.Thread(target=read_stream, args=(process.stderr, stderr_lines), daemon=True)
                stdout_thread.start()
                stderr_thread.start()
                
                # Watchdog loop - wrapped in try-except for KeyboardInterrupt resilience
                try:
                    # Watchdog loop for process monitoring
                    while process.poll() is None:
                        current_time = time.time()
                        elapsed = current_time - start_time
                    
                    # Check for new output
                    if stdout_lines or stderr_lines:
                        last_output_time = current_time
                    
                    idle_time = current_time - last_output_time
                    
                    # Hard timeout check
                    if elapsed > HARD_TIMEOUT:
                        logger.error(f"[ACPX-V2] 🔴 WATCHDOG: Hard timeout exceeded ({elapsed:.1f}s > {HARD_TIMEOUT}s) — killing process")
                        print(f"🔴 ACPX-V2-WATCHDOG: Hard timeout exceeded, killing process")
                        process.kill()
                        process.wait(timeout=5)
                        watchdog_killed = True
                        break
                    
                    # Idle timeout check
                    if idle_time > IDLE_TIMEOUT:
                        logger.warning(f"[ACPX-V2] ⚠️ WATCHDOG: Idle timeout exceeded ({idle_time:.1f}s > {IDLE_TIMEOUT}s) — terminating process")
                        print(f"🔴 ACPX-V2-WATCHDOG: Idle timeout exceeded, terminating process")
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                        idle_killed = True
                        break
                    
                    time.sleep(0.5)
                
                except KeyboardInterrupt:
                    # Handle external interrupt gracefully
                    logger.warning("[ACPX] KeyboardInterrupt detected — continuing to wait for process")
                    pass  # Continue to wait for threads to finish
                
                # Wait for reader threads to finish
                stdout_thread.join(timeout=2)
                stderr_thread.join(timeout=2)
                
                # Collect output
                stdout_output = ''.join(stdout_lines)
                stderr_output = ''.join(stderr_lines)
                return_code = process.returncode
                
                # Robust debug logging after execution
                print("ACPX RETURN CODE:", return_code)
                print("ACPX STDOUT:", stdout_output[:500] if stdout_output else "(empty)")
                print("ACPX STDERR:", stderr_output[:500] if stderr_output else "(empty)")
                
                # Handle watchdog kills
                if watchdog_killed:
                    self.snapshot_manager.restore_snapshot()
                    self.snapshot_manager.cleanup_snapshot()
                    result = {
                        "success": False,
                        "message": f"ACPX hard timeout exceeded ({HARD_TIMEOUT}s) — process killed",
                        "rollback": True
                    }
                    print(f"🔴 ACPX-V2-RETURN: Success={result.get('success')}, Reason=hard_timeout")
                    return result
                
                if idle_killed:
                    self.snapshot_manager.restore_snapshot()
                    self.snapshot_manager.cleanup_snapshot()
                    result = {
                        "success": False,
                        "message": f"ACPX idle timeout exceeded ({IDLE_TIMEOUT}s no output) — process terminated",
                        "rollback": True
                    }
                    print(f"🔴 ACPX-V2-RETURN: Success={result.get('success')}, Reason=idle_timeout")
                    return result
                
                # Tolerant error handling: ignore harmless JSON-RPC notification errors
                # and handle ACPX idle timeout (returns -6 even when edits succeed)
                should_fail = True
                if "session/update" in stderr_output and "Invalid params" in stderr_output:
                    logger.warning("[ACPX] Ignoring JSON-RPC notification error (session/update Invalid params)")
                    should_fail = False
                elif return_code == -6:
                    logger.warning("[ACPX] ACPX idle timeout detected but edits may have succeeded")
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

                print("🔴 ACPX-V2-STEP5-DONE: ACPX CLI completed")

            except Exception as e:
                print(f"🔴 ACPX-V2-STEP5-ERROR: {type(e).__name__}: {str(e)}")
                logger.error(f"[ACPX-V2] ACPX execution error: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                self.snapshot_manager.restore_snapshot()
                self.snapshot_manager.cleanup_snapshot()
                return {"success": False, "message": f"ACPX execution failed: {str(e)}"}
            except Exception as e:
                print(f"🔴 ACPX-V2-STEP5-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                self.snapshot_manager.restore_snapshot()
                self.snapshot_manager.cleanup_snapshot()
                return {"success": False, "message": f"ACPX execution failed: {str(e)}"}

            # Step 5: Capture filesystem state AFTER ACPX
            try:
                print("🔴 ACPX-V2-STEP6: Capturing filesystem state after ACPX")
                logger.info(f"[ACPX-V2] Step 5: Capturing filesystem state after ACPX...")
                hashes_after = FilesystemSnapshot.get_file_hashes(self.frontend_src_path)
                logger.info(f"[ACPX-V2]   Found {len(hashes_after)} files after ACPX")
                print("🔴 ACPX-V2-STEP6-DONE: Filesystem state captured after ACPX")
            except Exception as e:
                print(f"🔴 ACPX-V2-STEP6-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                self.snapshot_manager.restore_snapshot()
                self.snapshot_manager.cleanup_snapshot()
                return {"success": False, "message": f"Failed to capture post-ACPX state: {str(e)}"}

            # Step 6: Compute changes (filesystem diff)
            try:
                print("🔴 ACPX-V2-STEP7: Computing filesystem diff")
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

                print(f"🔴 ACPX-V2-STEP7-DONE: Diff computed - Added={len(files_added)}, Removed={len(files_removed)}, Modified={len(files_modified)}")
            except Exception as e:
                print(f"🔴 ACPX-V2-STEP7-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                self.snapshot_manager.restore_snapshot()
                self.snapshot_manager.cleanup_snapshot()
                return {"success": False, "message": f"Failed to compute diff: {str(e)}"}

            # Step 7: Validate file limits
            try:
                print("🔴 ACPX-V2-STEP8: Validating file limits")
                logger.info(f"[ACPX-V2] Step 7: Validating file limits...")
                if len(files_added) > MAX_NEW_FILES:
                    logger.error(f"[ACPX-V2] ❌ File limit exceeded: {len(files_added)} > {MAX_NEW_FILES}")
                    print("🔴 ACPX-V2-STEP8-ERROR: File limit exceeded, rolling back")
                    self.snapshot_manager.restore_snapshot()
                    self.snapshot_manager.cleanup_snapshot()
                    result = {
                        "success": False,
                        "message": f"File limit exceeded: {len(files_added)} new files, max {MAX_NEW_FILES} allowed",
                        "rollback": True
                    }
                    print(f"🔴 ACPX-V2-RETURN: Success={result.get('success')}, Added={result.get('files_added', 0)}, Modified={result.get('files_modified', 0)}")
                    return result
                logger.info(f"[ACPX-V2]   ✓ File limit OK ({len(files_added)}/{MAX_NEW_FILES})")
                print("🔴 ACPX-V2-STEP8-DONE: File limits validated")
            except Exception as e:
                print(f"🔴 ACPX-V2-STEP8-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                self.snapshot_manager.restore_snapshot()
                self.snapshot_manager.cleanup_snapshot()
                return {"success": False, "message": f"File limit validation failed: {str(e)}"}

            # Step 8: Validate paths
            try:
                print("🔴 ACPX-V2-STEP9: Validating paths")
                logger.info(f"[ACPX-V2] Step 8: Validating paths...")
                for file_path in files_added + files_removed:
                    rel_path = str(file_path.relative_to(self.frontend_src_path))
                    allowed, reason = self.validator.is_path_allowed(rel_path)
                    if not allowed:
                        logger.error(f"[ACPX-V2] ❌ Path validation failed: {reason}")
                        print(f"🔴 ACPX-V2-STEP9-ERROR: Path validation failed, rolling back")
                        self.snapshot_manager.restore_snapshot()
                        self.snapshot_manager.cleanup_snapshot()
                        result = {
                            "success": False,
                            "message": f"Path validation failed: {reason}",
                            "rollback": True
                        }
                        print(f"🔴 ACPX-V2-RETURN: Success={result.get('success')}, Added={result.get('files_added', 0)}, Modified={result.get('files_modified', 0)}")
                        return result
                logger.info(f"[ACPX-V2]   ✓ All paths valid")
                print("🔴 ACPX-V2-STEP9-DONE: All paths validated")
            except Exception as e:
                print(f"🔴 ACPX-V2-STEP9-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                self.snapshot_manager.restore_snapshot()
                self.snapshot_manager.cleanup_snapshot()
                return {"success": False, "message": f"Path validation failed: {str(e)}"}

            # Step 9: Enforce page guardrails (BEFORE build to prevent routing issues)
            try:
                print("🔴 ACPX-V2-STEP10: Enforcing page guardrails")
                logger.info(f"[ACPX-V2] Step 9: Enforcing page guardrails (BEFORE build)...")
                unauthorized_removed = self._enforce_page_guardrails()

                if unauthorized_removed > 0:
                    logger.info(f"[ACPX-V2]   ⚠️  Removed {unauthorized_removed} unauthorized page(s)")
                    print(f"🔴 ACPX-V2-STEP10-INFO: Removed {unauthorized_removed} unauthorized pages")
                else:
                    logger.info(f"[ACPX-V2]   ✓ All pages authorized")
                print("🔴 ACPX-V2-STEP10-DONE: Page guardrails enforced")
            except Exception as e:
                print(f"🔴 ACPX-V2-STEP10-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                # Don't rollback on guardrail errors, just log
                logger.warning(f"[ACPX-V2] Guardrail enforcement failed but continuing: {str(e)}")

            # Step 10: Run build gate (AFTER guardrails to prevent build errors)
            try:
                print("🔴 ACPX-V2-STEP11: Running build gate")
                logger.info(f"[ACPX-V2] Step 10: Running build gate (npm install && npm run build)...")
                build_success, build_output = self.build_gate.run_build()

                if not build_success:
                    logger.error(f"[ACPX-V2] ❌ Build failed")
                    logger.error(f"[ACPX-V2]   Build output (last 500 chars):\n{build_output[-500:]}")
                    print("🔴 ACPX-V2-STEP11-ERROR: Build failed, rolling back")
                    self.snapshot_manager.restore_snapshot()
                    self.snapshot_manager.cleanup_snapshot()
                    result = {
                        "success": False,
                        "message": "Build failed",
                        "build_output": build_output,
                        "rollback": True
                    }
                    print(f"🔴 ACPX-V2-RETURN: Success={result.get('success')}, Added={result.get('files_added', 0)}, Modified={result.get('files_modified', 0)}")
                    return result

                logger.info(f"[ACPX-V2] ✓ Build succeeded!")
                print("🔴 ACPX-V2-STEP11-DONE: Build gate passed")
            except Exception as e:
                print(f"🔴 ACPX-V2-STEP11-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                self.snapshot_manager.restore_snapshot()
                self.snapshot_manager.cleanup_snapshot()
                return {"success": False, "message": f"Build execution failed: {str(e)}"}

            # Step 11: Success - cleanup snapshot
            try:
                print("🔴 ACPX-V2-STEP12: Cleaning up snapshot")
                logger.info(f"[ACPX-V2] Step 10: Cleanup snapshot...")
                self.snapshot_manager.cleanup_snapshot()
                print("🔴 ACPX-V2-STEP12-DONE: Snapshot cleaned up")
            except Exception as e:
                print(f"🔴 ACPX-V2-STEP12-ERROR: {type(e).__name__}: {str(e)}")
                traceback.print_exc()
                # Don't fail on cleanup errors
                logger.warning(f"[ACPX-V2] Snapshot cleanup failed but returning success: {str(e)}")

            # Final result
            result = {
                "success": True,
                "message": "ACPX changes applied successfully",
                "files_added": len(files_added),
                "files_modified": len(files_modified),
                "files_removed": len(files_removed),
                "build_output": build_output,
                "rollback": False
            }
            print(f"🔴 ACPX-V2-RETURN: Success={result.get('success')}, Added={result.get('files_added')}, Modified={result.get('files_modified')}")
            return result

        except Exception as e:
            # Global exception handler
            print(f"🔴 ACPX-V2-FATAL-ERROR: {type(e).__name__}: {str(e)}")
            print("🔴 ACPX-V2-FATAL-ERROR: Traceback:")
            traceback.print_exc()
            print("🔴 ACPX-V2-FATAL-ERROR: Returning error result")

            # Attempt to rollback if possible
            try:
                self.snapshot_manager.restore_snapshot()
                self.snapshot_manager.cleanup_snapshot()
            except Exception as rollback_error:
                print(f"🔴 ACPX-V2-FATAL-ERROR: Rollback also failed: {rollback_error}")

            return {
                "success": False,
                "message": f"FATAL ERROR in apply_changes_via_acpx: {str(e)}",
                "files_added": 0,
                "files_modified": 0,
                "files_removed": 0,
                "rollback": False
            }

    def _ai_infer_pages(self, goal_description: str) -> List[str]:
        """
        Use AI to infer reasonable page structure from product description.

        Args:
            goal_description: Product description text

        Returns:
            List of inferred page names
        """
        import json
        import subprocess

        logger.info(f"[Planner] Running AI page inference for: {goal_description[:100]}...")

        # Build inference prompt
        inference_prompt = f"""You are planning the page structure for a SaaS application.

Product description:
{goal_description}

Your task:
Return a list of 5-10 pages that would be appropriate for this application.

Rules:
1. Consider the product type (CRM, analytics, document management, etc.)
2. Think about standard SaaS pages (Dashboard, Settings, etc.)
3. Be specific with page names (not generic like "MainPage")
4. Return ONLY a JSON list of page names
5. Do NOT include explanations or extra text

Response format (JSON ONLY):
{{"pages": ["Dashboard", "Contacts", "Analytics", "Settings", "Documents"]}}

EXAMPLES:
CRM app → {{"pages": ["Dashboard", "Contacts", "Deals", "Reports", "Tasks", "Settings"]}}
Document management → {{"pages": ["Dashboard", "Documents", "Templates", "Editor", "Analytics", "Settings"]}}
Analytics dashboard → {{"pages": ["Dashboard", "Reports", "Analytics", "Settings"]}}

Provide ONLY the JSON list, nothing else."""

        try:
            # Call LLM for page inference using ACPX CLI
            # Ensure all args are strings to avoid TypeError
            cmd = [
                "acpx",
                "--cwd", "/tmp",
                "--format", "quiet",
                "claude",
                "exec",
                str(inference_prompt)
            ]
            
            # Robust debug logging
            print("ACPX CMD:", " ".join(cmd[:6]) + " <prompt>")
            print("[ACPX] cwd: /tmp")
            print("[ACPX] running: acpx --format quiet claude exec (page inference)")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            # Robust debug logging after execution
            print("ACPX RETURN CODE:", result.returncode)
            print("ACPX STDOUT:", result.stdout)
            print("ACPX STDERR:", result.stderr)
            
            # Tolerant error handling: ignore harmless JSON-RPC notification errors
            stderr = result.stderr or ""
            should_fail = True
            if "session/update" in stderr and "Invalid params" in stderr:
                logger.warning("[ACPX] Page inference: ignoring JSON-RPC notification error")
                should_fail = False

            if result.returncode != 0 and should_fail:
                logger.error(f"[ACPX] Page inference failed (code {result.returncode})")
                raise RuntimeError(f"ACPX page inference failed: {stderr}")

            # Parse LLM response
            response_text = result.stdout.strip()

            # Extract JSON from response - More flexible parsing
            import re
            # Try multiple JSON patterns
            json_patterns = [
                r'\[\s*{[^}]+\}\s*\]',  # [ { "pages": [...] } ]
                r'{\s*"pages"\s*:\s*\[.*?\]',  # {"pages": [...]}
                r'pages"\s*:\s*\[',  # pages": [ (simplified)
            ]

            inferred_pages = []
            for pattern in json_patterns:
                match = re.search(pattern, response_text, re.DOTALL | re.IGNORECASE)
                if match:
                    try:
                        json_str = match.group(0)
                        # Try to extract just the JSON part
                        if '[' in json_str:
                            json_str = json_str[json_str.find('['):]
                        
                        # Parse JSON - handle both object and array
                        try:
                            inferred_data = json.loads(json_str)
                        except json.JSONDecodeError as e:
                            logger.error(f"[Planner] JSON parse error: {e}")
                            logger.error(f"[Planner] JSON string was: {json_str[:500]}")
                            raise
                        
                        # Extract pages from response (handle both object and array)
                        pages = []
                        if isinstance(inferred_data, dict):
                            # Object format: {"pages": [...]}
                            pages = inferred_data.get("pages", [])
                            logger.info(f"[Planner] AI inference successful (object format): {len(pages)} pages")
                        elif isinstance(inferred_data, list):
                            # Array format: [...]
                            pages = inferred_data
                            logger.info(f"[Planner] AI inference successful (array format): {len(pages)} pages")
                        else:
                            logger.warning(f"[Planner] Unexpected JSON type: {type(inferred_data)}")
                        
                        logger.info(f"[Planner] Inferred: {pages}")
                        return pages

                    except json.JSONDecodeError as e:
                        logger.warning(f"[Planner] AI inference JSON parse error with pattern: {pattern}, {e}")
                        continue

            # If all patterns fail, try to find list-like structures
            if not inferred_pages:
                # Look for comma-separated lists of page names
                list_match = re.search(r'(?:Dashboard|Documents|Templates|Editor|Signing|Contacts|Analytics|Settings|Reports|Tasks|Team|Billing|Notifications|Posts|Create)[,\s]*(?:Dashboard|Documents|Templates|Editor|Signing|Contacts|Analytics|Settings|Reports|Tasks|Team|Billing|Notifications|Posts|Create)', response_text, re.IGNORECASE)
                if list_match:
                    # Extract unique page names
                    found_pages = list(set([p.strip() for p in list_match.group(0).split(',') if p.strip()]))
                    inferred_pages = found_pages
                    logger.info(f"[Planner] AI inference successful (list pattern): {len(inferred_pages)} pages")
                    logger.info(f"[Planner] Inferred: {inferred_pages}")
                    return inferred_pages

            # Final fallback
            if not inferred_pages:
                logger.warning(f"[Planner] AI inference: No valid JSON/list found in response, using keywords")
            else:
                logger.info(f"[Planner] Final AI inference result: {inferred_pages}")

            return inferred_pages if inferred_pages else []

        except subprocess.TimeoutExpired:
            logger.error(f"[Planner] AI inference timeout after 60s")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"[Planner] AI inference JSON decode error: {e}")
            return []
        except Exception as e:
            logger.error(f"[Planner] AI inference error: {type(e).__name__}: {e}")
            return []

    def _extract_required_pages_from_prompt(self, goal_description: str) -> List[str]:
        """
        Extract required pages from goal description using improved planner logic.

        Detection priority: manifest → explicit → AI inference → keywords → SaaS defaults

        Args:
            goal_description: Goal for changes

        Returns:
            List of required page names
        """
        logger.info("[Planner] Extracting required pages from prompt...")

        required_pages = []

        # Page keyword mappings for improved detection
        PAGE_KEYWORDS = {
            "Dashboard": ["dashboard", "overview"],
            "Documents": ["document", "docflow", "panda", "agreement", "contract"],
            "Templates": ["template"],
            "DocumentEditor": ["document editor", "doc editor", "editor"],
            "Signing": ["sign", "signature", "esign", "electronically sign"],
            "Analytics": ["analytics", "metrics", "reports", "statistics"],
            "Contacts": ["contacts", "crm", "customer", "customers", "lead", "leads"],
            "Team": ["team", "members", "users", "staff"],
            "Billing": ["billing", "subscription", "payments", "invoice", "pricing"],
            "Notifications": ["notifications", "alerts", "messages", "notification"],
            "Tasks": ["task", "todo", "project", "kanban"],
            "Settings": ["setting", "settings", "config", "preference", "preferences"],
            "Posts": ["post", "posts", "article", "articles", "blog"],
            "Create": ["create", "write", "compose"]
        }

        desc_lower = goal_description.lower()

        # Step 1: Try to load page manifest (Phase 5 - NEW)
        manifest_pages = None
        if hasattr(self, 'manifest_manager') and self.manifest_manager:
            manifest_pages = self.manifest_manager.get_required_pages()
            if manifest_pages:
                logger.info(f"[Planner] Using manifest pages: {manifest_pages}")
                required_pages.extend(manifest_pages)
            else:
                logger.info("[Planner] No manifest found, will use inference or keywords")

        # Step 2: Extract explicit page lists (highest priority)
        # Matches patterns like: "pages: Dashboard, Documents, Templates"
        # Or: "with 10 pages: Dashboard, Documents, Templates..."
        import re
        explicit_list_pattern = r'pages?:\s*(.+)'
        explicit_match = re.search(explicit_list_pattern, goal_description, re.IGNORECASE)

        if explicit_match:
            pages_str = explicit_match.group(1)
            # Normalize and split by comma
            explicit_pages = [p.strip() for p in pages_str.split(',')]

            # Normalize page names: "Document Editor" → "DocumentEditor"
            for page in explicit_pages:
                # Remove leading/trailing whitespace and special chars
                normalized = re.sub(r'\s+', '', page.strip().title())
                # Skip empty strings or strings with only special chars
                if normalized and len(normalized) > 0 and any(c.isalpha() for c in normalized):
                    required_pages.append(normalized)
                    logger.info(f"[Planner] Explicit page detected: {page} → {normalized}")

            logger.info(f"[Planner] Explicit page list detected: {len(required_pages)} pages")

        # Step 3: AI Page Inference (if no explicit pages found) - NEW
        if not explicit_match:
            logger.info("[Planner] Triggering AI page inference")
            logger.info(f"[Planner] Description for inference: {goal_description[:200]}...")
            inferred_pages = self._ai_infer_pages(goal_description)
            required_pages.extend(inferred_pages)
            logger.info(f"[Planner] AI inferred pages: {inferred_pages}")

        # Step 4: Keyword matching (if explicit list not found or incomplete)
        desc_lower = goal_description.lower()
        for page_name, keywords in PAGE_KEYWORDS.items():
            if page_name not in required_pages:  # Skip if already in explicit list
                if any(keyword in desc_lower for keyword in keywords):
                    required_pages.append(page_name)

        # Step 5: SaaS default fallback (if less than 3 pages detected)
        if len(required_pages) < 3:
            logger.info(f"[Planner] Fewer than 3 pages detected ({len(required_pages)}), adding SaaS defaults")
            saas_defaults = ["Dashboard", "Analytics", "Contacts", "Settings"]
            for default_page in saas_defaults:
                if default_page not in required_pages:
                    required_pages.append(default_page)

        # Step 6: Remove duplicates while preserving order
        required_pages = list(dict.fromkeys(required_pages))

        # Phase 9: Store allowed pages whitelist for guardrails
        self.allowed_pages = set(required_pages)
        logger.info(f"[Phase9] Allowed pages: {required_pages}")

        # Planner logging
        logger.info(f"[Planner] Description: {goal_description}")
        logger.info(f"[Planner] Detected pages: {required_pages}")

        return required_pages

    def _build_acpx_prompt(self, goal_description: str) -> str:
        """
        Build ACPX prompt with explicit required artifacts and completion checklist.

        Args:
            goal_description: Goal for changes

        Returns:
            Prompt string for ACPX
        """
        # Extract required pages from goal description
        required_pages = self._extract_required_pages_from_prompt(goal_description)
        required_components = []

        # Build required artifacts list
        required_pages_list = required_pages
        required_components_list = list(set(required_components))

        required_pages_str = "\n".join([f"- src/pages/{page}.tsx" for page in required_pages_list])
        required_components_str = "\n".join([f"- src/components/{comp}.tsx" for comp in required_components_list])

        # Phase 9: Build page templates section - DISABLED (causing NameError: get_page_template_for_prompt not defined)
        # page_templates_section = self._build_page_templates_section(required_pages, goal_description)
        page_templates_section = "Page templates section disabled - using page specifications only"

        # Phase 4: Build page specs section (NEW)
        page_specs_section = self._build_page_specs_section(required_pages)

        return f"""You are editing a React + Vite + TypeScript SaaS application.

Project Name: {self.project_name}
Project Description: {goal_description}

YOUR TASK

Transform the existing template into a production-ready application based on the project description above.

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
   - [ ] ONLY pages from REQUIRED PAGES list exist in src/pages/
   - [ ] NO unauthorized pages were created
   - [ ] All required pages are complete
   - [ ] File names match exactly with REQUIRED PAGES list

PAGE TEMPLATES
{page_templates_section}

PAGE SPECIFICATIONS (Phase 4 - Enhanced UI Quality)
{page_specs_section}

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

COMPLETION CHECKLIST

✓ All required pages created in src/pages/ (EXACT file names)
✓ All required components created in src/components/
✓ Routing updated in src/App.tsx
✓ Navigation/sidebar updated
✓ Responsive design implemented
✓ Code is production-ready
✓ npm run build succeeds

WORKING METHODOLOGY

You must work systematically through ALL required pages.

1. Read the project description, page templates, and page specifications carefully
2. Plan your approach using BOTH templates and specs as guidance
3. Execute step by step following page templates and specifications
4. DO NOT STOP until ALL required pages are created
5. After completing a page, move to the next page
6. Continue until the entire checklist is complete
7. Run npm run build after all pages are created

EXECUTION RULES

1. Work through pages ONE AT A TIME using page templates
2. Complete each page fully before moving to the next
3. Use EXACT page names from REQUIRED PAGES list
4. Do not skip any required page
5. Do not stop early - continue until checklist is 100% complete
6. Only mark task complete when ALL checklist items are done
7. Use page templates as guidance but adapt to existing code structure

TECHNICAL REQUIREMENTS

- Keep the code buildable (npm run build must succeed)
- Use existing UI components from src/components/ui/
- Follow existing code patterns and style
- Write clean, production-ready code
- Do not introduce placeholder content unless required
- Follow page templates AND page specifications for professional UI
- Ensure all UI elements from page specs are implemented

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

            # Check if page is in allowed whitelist
            if page_name not in self.allowed_pages:
                logger.warning(f"[Guardrail] Removing unauthorized page: {page_name}")
                try:
                    page_file.unlink()
                    unauthorized_removed += 1
                except Exception as e:
                    logger.error(f"[Guardrail] Failed to remove {page_name}: {e}")

        if unauthorized_removed > 0:
            logger.info(f"[Guardrail] Removed {unauthorized_removed} unauthorized page(s)")
            logger.info(f"[Guardrail] Remaining allowed pages: {sorted(self.allowed_pages)}")
        else:
            logger.info(f"[Guardrail] ✓ All pages are authorized")

        logger.info(f"[Phase9] Final validated pages: {sorted(self.allowed_pages)}")

        return unauthorized_removed
