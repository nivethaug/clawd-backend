#!/usr/bin/env python3
"""
ACP Frontend Editor v2 - Filesystem Diff Architecture

Implements safe, validated frontend editing using filesystem diffing:
- Snapshot before changes
- Run Claude Code Agent (lets AI edit files naturally)
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

# Claude Code Agent - direct Claude CLI wrapper (replaces ACPX)
try:
    from claude_code_agent import ClaudeCodeAgent
    CLAUDE_AGENT_AVAILABLE = True
except ImportError:
    CLAUDE_AGENT_AVAILABLE = False

# Configure logging - WARNING level to suppress INFO messages
# Set root logger to WARNING to suppress INFO from all modules
logging.getLogger().setLevel(logging.WARNING)
logging.basicConfig(
    level=logging.WARNING,
    format='[%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)  # Explicitly set level for this logger


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
    "services",
    "api-config.ts",
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

# Claude Code Agent settings
CLAUDE_TIMEOUT = int(os.getenv("CLAUDE_TIMEOUT", "900"))  # 15 minutes default

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
            # logger.info(f"[Snapshot] Creating snapshot at {self.backup_dir}")
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

            # logger.info(f"[Snapshot] ✓ Snapshot created successfully")
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
                # logger.info(f"[Snapshot] ✓ Cleaned up snapshot at {self.backup_dir}")
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
        output = []
        output.append("=== Starting Build Process ===")
        output.append(f"Working directory: {self.frontend_path}")

        # ⚡ Skip build if dist already exists (ACPX may have built it)
        dist_path = self.frontend_path / "dist"
        if dist_path.exists():
            index_html = dist_path / "index.html"
            assets_dir = dist_path / "assets"
            js_files = list(assets_dir.glob("*.js")) if assets_dir.exists() else []
            
            if index_html.exists() and js_files:
                output.append(f"⚡ Skipping build (dist already exists)")
                output.append(f"✓ dist/index.html: {index_html.stat().st_size:,} bytes")
                output.append(f"✓ dist/assets/*.js: {len(js_files)} files")
                
                # Cleanup node_modules to save disk space
                output.append("\n--- Optional Cleanup ---")
                node_modules = self.frontend_path / "node_modules"
                if node_modules.exists():
                    try:
                        shutil.rmtree(node_modules)
                        output.append("🧹 node_modules removed (disk optimization)")
                        logger.info("🧹 node_modules removed (disk optimization)")
                    except Exception as e:
                        output.append(f"⚠️ Could not remove node_modules: {e}")
                else:
                    output.append("node_modules not found, skipping cleanup")
                
                output.append("=== Build Process Complete (skipped) ===")
                logger.info("⚡ Skipping build (dist already exists)")
                return True, "\n".join(output)

        valid, message = self.validate_environment()
        if not valid:
            return False, f"Environment validation failed: {message}"

        try:
            # Step 1: Install dependencies (npm only - pnpm disabled for consistency)
            output.append("\n--- Installing Dependencies ---")
            install_success, install_msg = install_dependencies(self.frontend_path)
            output.append(install_msg)
            
            if not install_success:
                output.append(f"❌ Dependency installation failed: {install_msg}")
                return False, "\n".join(output)

            output.append("✅ Dependencies installed successfully")

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

                # Step 4: Optional cleanup - remove node_modules to save disk space
                output.append("\n--- Optional Cleanup ---")
                node_modules = self.frontend_path / "node_modules"
                if node_modules.exists():
                    try:
                        import shutil
                        shutil.rmtree(node_modules)
                        output.append("🧹 node_modules removed (disk optimization)")
                    except Exception as e:
                        output.append(f"⚠️ Could not remove node_modules: {e}")
                else:
                    output.append("node_modules not found, skipping cleanup")

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
# HELPER FUNCTIONS FOR PARTIAL COMMIT SYSTEM
# =============================================================================

def install_dependencies(frontend_path: Path) -> Tuple[bool, str]:
    """
    Install frontend dependencies using npm ci (pnpm disabled for consistency).
    
    Args:
        frontend_path: Path to frontend directory containing package.json
        
    Returns:
        Tuple of (success, message)
    """
    print("=" * 60, flush=True)
    print("📦 DEPENDENCY INSTALLATION", flush=True)
    print("=" * 60, flush=True)

    # ⚡ Skip install if node_modules already exists (cached)
    node_modules = Path(frontend_path) / "node_modules"
    if node_modules.exists():
        logger.info("⚡ Skipping npm install (node_modules exists)")
        print("⚡ [DEPS] Skipping install (dependencies already installed)", flush=True)
        print("=" * 60, flush=True)
        return True, "Dependencies already installed (cached)"

    # Detect PM2 environment
    is_pm2 = bool(os.environ.get("PM2_USAGE")) or bool(os.environ.get("PM2_HOME"))

    # 🚨 PM2 ENVIRONMENT → FORCE NPM (skip pnpm due to SIGABRT)
    if is_pm2:
        logger.warning("⚠️ PM2 detected - using optimized npm ci")
        print("⚠️  [DEPS] PM2 detected → optimized npm ci", flush=True)

        try:
            result = subprocess.run(
                ["npm", "ci", "--prefer-offline", "--no-audit", "--progress=false"],
                cwd=str(frontend_path),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=BUILD_TIMEOUT
            )

            if result.returncode == 0:
                logger.info("✅ npm ci successful (optimized)")
                print("✅ [DEPS] npm ci successful (optimized)", flush=True)
                print("=" * 60, flush=True)
                return True, "npm ci successful (optimized)"

            logger.error(f"❌ npm ci failed with code {result.returncode}")
            print(f"❌ [DEPS] npm ci failed with code {result.returncode}", flush=True)
            if result.stderr:
                print(f"    [DEPS] stderr: {result.stderr[:200]}", flush=True)
            print("=" * 60)
            return False, f"npm ci failed: {result.stderr}"

        except Exception as e:
            logger.error(f"❌ npm ci error: {e}")
            print(f"❌ [DEPS] npm ci error: {e}", flush=True)
            print("=" * 60)
            return False, f"npm ci error: {e}"

    # ⚡ NON-PM2 → TRY PNPM FIRST (DISABLED - using npm only for consistency)
    # try:
    #     logger.info("⚡ Trying pnpm install (non-PM2 mode)...")
    #     print("⚡ [DEPS] Trying pnpm install (non-PM2 mode)...", flush=True)
    # 
    #     result = subprocess.run(
    #         ["pnpm", "install", "--prefer-offline"],
    #         cwd=str(frontend_path),
    #         stdin=subprocess.DEVNULL,
    #         stdout=subprocess.DEVNULL,
    #         stderr=subprocess.PIPE,
    #         text=True,
    #         timeout=BUILD_TIMEOUT
    #     )
    # 
    #     if result.returncode == 0:
    #         logger.info("✅ pnpm install successful")
    #         print("✅ [DEPS] pnpm install successful", flush=True)
    #         print("=" * 60, flush=True)
    #         return True, "pnpm install successful"
    # 
    #     logger.warning(f"⚠️ pnpm install failed (code {result.returncode}), falling back to npm")
    #     print(f"⚠️  [DEPS] pnpm failed (code {result.returncode}), falling back to npm", flush=True)
    #     if result.stderr:
    #         print(f"    [DEPS] stderr: {result.stderr[:200]}")
    # 
    # except FileNotFoundError:
    #     logger.warning("⚠️ pnpm not found, falling back to npm")
    #     print("⚠️  [DEPS] pnpm not found, falling back to npm", flush=True)
    # except Exception as e:
    #     logger.warning(f"⚠️ pnpm error: {e}, falling back to npm")
    #     print(f"⚠️  [DEPS] pnpm error: {e}, falling back to npm", flush=True)

    # 🔁 USE NPM (pnpm disabled for consistency with infrastructure_manager.py)
    try:
        logger.info("📦 Running optimized npm ci...")
        print("📦 [DEPS] Running optimized npm ci...", flush=True)

        result = subprocess.run(
            ["npm", "ci", "--prefer-offline", "--no-audit", "--progress=false"],
            cwd=str(frontend_path),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=BUILD_TIMEOUT
        )

        if result.returncode == 0:
            logger.info("✅ npm ci successful (optimized)")
            print("✅ [DEPS] npm ci successful (optimized)", flush=True)
            print("=" * 60, flush=True)
            return True, "npm ci successful (optimized)"

        logger.error(f"❌ npm ci failed with code {result.returncode}")
        print(f"❌ [DEPS] npm ci failed with code {result.returncode}")
        if result.stderr:
            print(f"    [DEPS] stderr: {result.stderr[:200]}")
        print("=" * 60)
        return False, f"npm ci failed: {result.stderr}"

    except Exception as e:
        logger.error(f"❌ npm ci error: {e}")
        print(f"❌ [DEPS] npm ci error: {e}", flush=True)
        print("=" * 60, flush=True)
        return False, f"npm ci error: {e}"


def safe_snapshot(snapshot_manager: ACPSnapshotManager, max_retries: int = 1) -> Tuple[bool, str]:
    """
    Safely create a snapshot with retry logic.
    
    Args:
        snapshot_manager: ACPSnapshotManager instance
        max_retries: Number of retry attempts (default 1)
        
    Returns:
        Tuple of (success, message) - On failure, returns (True, warning) to allow continuation
    """
    attempts = 0
    last_error = None
    
    while attempts <= max_retries:
        try:
            success, msg = snapshot_manager.create_snapshot()
            if success:
                logger.info(f"[SafeSnapshot] ✓ Snapshot created successfully")
                return True, msg
            last_error = msg
        except Exception as e:
            last_error = str(e)
            logger.warning(f"[SafeSnapshot] ⚠️ Snapshot attempt {attempts + 1} failed: {e}")
        
        attempts += 1
        if attempts <= max_retries:
            logger.info(f"[SafeSnapshot] Retrying snapshot (attempt {attempts + 1}/{max_retries + 1})...")
    
    # Snapshot failed but we continue - return soft failure
    logger.warning(f"[SafeSnapshot] ⚠️ Snapshot creation failed after {max_retries + 1} attempts, continuing without backup")
    return True, f"Snapshot warning: {last_error}"


def safe_diff(
    hashes_before: Dict[str, str],
    hashes_after: Dict[str, str]
) -> Dict[str, List[str]]:
    """
    Safely compute filesystem diff with fallback to empty diff.
    
    Args:
        hashes_before: File hashes before changes
        hashes_after: File hashes after changes
        
    Returns:
        Dict with 'added', 'removed', 'modified' lists - empty on failure
    """
    try:
        diff = FilesystemSnapshot.compute_diff(hashes_before, hashes_after)
        logger.info(f"[SafeDiff] ✓ Diff computed: {len(diff['added'])} added, {len(diff['modified'])} modified, {len(diff['removed'])} removed")
        return diff
    except Exception as e:
        logger.warning(f"[SafeDiff] ⚠️ Diff computation failed: {e}, returning empty diff")
        return {"added": [], "removed": [], "modified": []}


def filter_valid_paths(
    file_paths: List[str],
    validator: ACPPathValidator
) -> Tuple[List[str], List[Tuple[str, str]]]:
    """
    Filter files into valid and invalid paths.
    
    Args:
        file_paths: List of file paths to validate
        validator: ACPPathValidator instance
        
    Returns:
        Tuple of (valid_paths, invalid_paths_with_reasons)
    """
    valid_paths = []
    invalid_paths = []
    
    for file_path in file_paths:
        try:
            is_allowed, reason = validator.is_path_allowed(str(file_path))
            if is_allowed:
                valid_paths.append(str(file_path))
            else:
                invalid_paths.append((str(file_path), reason))
                logger.warning(f"[FilterPaths] ⚠️ Invalid path detected: {file_path} - {reason}")
        except Exception as e:
            logger.warning(f"[FilterPaths] ⚠️ Path validation error for {file_path}: {e}")
            invalid_paths.append((str(file_path), f"Validation error: {e}"))
    
    logger.info(f"[FilterPaths] ✓ Filtered: {len(valid_paths)} valid, {len(invalid_paths)} invalid")
    return valid_paths, invalid_paths


def enforce_file_limit(
    files_added: List[str],
    max_new_files: int,
    frontend_src_path: Path
) -> Tuple[List[str], List[str]]:
    """
    Enforce file limit by keeping only first max_new_files.
    
    Args:
        files_added: List of newly added files
        max_new_files: Maximum allowed new files
        frontend_src_path: Path to frontend src for file deletion
        
    Returns:
        Tuple of (kept_files, removed_files)
    """
    if len(files_added) <= max_new_files:
        logger.info(f"[FileLimit] ✓ Within limit: {len(files_added)}/{max_new_files}")
        return files_added, []
    
    # Keep first max_new_files, remove the rest
    kept_files = files_added[:max_new_files]
    excess_files = files_added[max_new_files:]
    removed_files = []
    
    for file_path in excess_files:
        try:
            full_path = frontend_src_path / file_path
            if full_path.exists():
                full_path.unlink()
                removed_files.append(file_path)
                logger.warning(f"[FileLimit] 🗑️ Removed excess file: {file_path}")
        except Exception as e:
            logger.warning(f"[FileLimit] ⚠️ Failed to remove excess file {file_path}: {e}")
    
    logger.warning(f"[FileLimit] ⚠️ Trimmed {len(removed_files)} excess files (limit: {max_new_files})")
    return kept_files, removed_files


def delete_invalid_files(
    invalid_paths: List[Tuple[str, str]],
    frontend_src_path: Path
) -> int:
    """
    Delete files at invalid paths.
    
    Args:
        invalid_paths: List of (path, reason) tuples
        frontend_src_path: Path to frontend src
        
    Returns:
        Number of files successfully deleted
    """
    deleted_count = 0
    
    for file_path, reason in invalid_paths:
        try:
            full_path = frontend_src_path / file_path
            if full_path.exists():
                full_path.unlink()
                deleted_count += 1
                logger.warning(f"[DeleteInvalid] 🗑️ Deleted invalid file: {file_path} ({reason})")
        except Exception as e:
            logger.warning(f"[DeleteInvalid] ⚠️ Failed to delete {file_path}: {e}")
    
    return deleted_count


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

    async def apply_changes(
        self,
        goal_description: str,
        execution_id: str
    ) -> Dict[str, Any]:
        """
        Apply frontend changes by running Claude Code Agent and detecting filesystem changes.

        Implements 3-state outcome system:
        - "success": All validations passed, clean execution
        - "partial_success": Some issues but usable output preserved
        - "failed": Fatal error, rollback performed

        Args:
            goal_description: Natural language description of changes
            execution_id: Unique ID for tracking

        Returns:
            Dict with status, message, files changed, build output, rollback status
        """
        import traceback

        # Clear cache for each new execution to ensure fresh page inference
        self._cached_pages = None

        # Track issues for partial_success determination
        issues: List[str] = []
        status = "success"  # Default to success, downgrade as needed

        try:
            logger.info(f"[CLAUDE-AGENT] 🔴 HEARTBEAT: Starting Phase 9 (Claude Code Agent)")
            logger.info(f"[CLAUDE-AGENT] 🔴 HEARTBEAT: Project: {self.project_name}")
            logger.info(f"[CLAUDE-AGENT] 🔴 HEARTBEAT: Execution ID: {execution_id}")

            # Step 1: Create snapshot (safe - continues on failure)
            logger.info(f"[CLAUDE-AGENT] Step 1: Creating filesystem snapshot...")
            snapshot_success, snapshot_msg = safe_snapshot(self.snapshot_manager, max_retries=1)
            if not snapshot_success or "warning" in snapshot_msg.lower():
                issues.append(f"Snapshot warning: {snapshot_msg}")
                logger.warning(f"[CLAUDE-AGENT] ⚠️ Snapshot issue (continuing): {snapshot_msg}")
            else:
                logger.info(f"[CLAUDE-AGENT] ✓ Snapshot created")

            # Step 2: Generate page manifest from planner (Phase 5 - NEW)
            logger.info(f"[CLAUDE-AGENT] Step 2: Generating page manifest (Phase 5)...")
            required_pages = await self._extract_required_pages_from_prompt(goal_description)
            logger.info(f"[CLAUDE-AGENT]   Planner detected pages: {required_pages}")

            # Write manifest to project directory
            manifest_success = self.manifest_manager.write_manifest(required_pages)
            if not manifest_success:
                issues.append("Failed to write page manifest")
                logger.warning(f"[CLAUDE-AGENT] ⚠️ Failed to write page manifest (continuing)")

            # Update allowed_pages with manifest pages (source of truth)
            self.allowed_pages = set(required_pages)
            logger.info(f"[CLAUDE-AGENT]   Manifest pages set as allowed: {required_pages}")
            
            # 🎯 FINALIZED PAGES - Clear PM2 log visibility
            print("=" * 80)
            print("🎯 FINALIZED PAGES FOR AI EDITING:")
            for i, page in enumerate(required_pages, 1):
                print(f"   {i}. {page}.tsx")
            print(f"   Total: {len(required_pages)} pages")
            print("=" * 80)
            logger.info(f"[CLAUDE-AGENT] 🎯 FINALIZED PAGES: {required_pages}")

            # Step 3: Capture filesystem state BEFORE execution (moved before scaffold)
            logger.info(f"[CLAUDE-AGENT] Step 3: Capturing filesystem state before execution...")
            try:
                hashes_before = FilesystemSnapshot.get_file_hashes(self.frontend_src_path)
                logger.info(f"[CLAUDE-AGENT]   Found {len(hashes_before)} files before execution")
            except Exception as e:
                logger.warning(f"[CLAUDE-AGENT] ⚠️ Failed to capture pre-execution state: {e}")
                hashes_before = {}
                issues.append(f"Pre-execution snapshot failed: {e}")

            # Step 4: Scaffold pages from manifest (Phase 5 - NEW)
            logger.info(f"[CLAUDE-AGENT] Step 4: Scaffolding pages from manifest...")
            scaffold_result = self.manifest_manager.scaffold_pages(required_pages, create_placeholder=True)
            if not scaffold_result:
                issues.append("Some pages failed to scaffold")
                logger.warning(f"[CLAUDE-AGENT] ⚠️ Some pages failed to scaffold, continuing...")

            # Step 5: Build prompt using manifest pages
            logger.info(f"[CLAUDE-AGENT] Step 5: Building prompt (using manifest pages)...")
            prompt = await self._build_acpx_prompt(goal_description)

            # Step 6: Run Claude Code Agent (replaces ACPX subprocess)
            try:
                print("=" * 60)
                print("PHASE_9_APPLY")
                logger.info(f"[CLAUDE-AGENT] Step 6: Running Claude Code Agent...")

                logger.info(f"[CLAUDE-AGENT]   Working directory: {self.frontend_src_path}")
                logger.info(f"[CLAUDE-AGENT]   Timeout: {CLAUDE_TIMEOUT}s")

                # Robust debug logging
                print("[CLAUDE-AGENT] cwd:", str(self.frontend_src_path))
                print(f"[CLAUDE-AGENT] timeout: {CLAUDE_TIMEOUT}s")

                # Execute Claude Code Agent
                return_code, stdout_output, stderr_output = await self._run_claude_agent(prompt)

                # Robust debug logging after execution - FULL OUTPUT
                print("=" * 80, flush=True)
                print("CLAUDE-AGENT RETURN CODE:", return_code, flush=True)
                print("=" * 80, flush=True)
                print("CLAUDE-AGENT STDOUT:", flush=True)
                print(stdout_output if stdout_output else "(empty)", flush=True)
                print("=" * 80, flush=True)
                print("CLAUDE-AGENT STDERR:", flush=True)
                print(stderr_output if stderr_output else "(empty)", flush=True)
                print("=" * 80, flush=True)
                
                # =============================================
                # PARTIAL COMMIT: Timeout/error handling (NO ROLLBACK if files exist)
                # =============================================
                
                # Handle timeout (return code 124) or error (non-zero return code)
                if return_code != 0:
                    # Check if any files were created
                    created_files = list(self.frontend_src_path.glob("**/*.tsx"))
                    if created_files:
                        if return_code == 124:
                            issues.append(f"Timeout exceeded ({CLAUDE_TIMEOUT}s)")
                            logger.warning(f"[CLAUDE-AGENT] ⚠️ Timeout ({CLAUDE_TIMEOUT}s) — keeping {len(created_files)} generated files")
                            print(f"⚠️ CLAUDE-AGENT-TIMEOUT: Keeping {len(created_files)} generated files (partial success)", flush=True)
                        else:
                            issues.append(f"Claude Agent exited with code {return_code}")
                            logger.warning(f"[CLAUDE-AGENT] ⚠️ Non-zero exit ({return_code}) — keeping {len(created_files)} generated files")
                            print(f"⚠️ CLAUDE-AGENT-ERROR: Keeping {len(created_files)} generated files (partial success)", flush=True)
                        status = "partial_success"
                    else:
                        logger.error(f"[CLAUDE-AGENT] 🔴 Execution failed (code {return_code}) and NO files created — rollback")
                        print(f"🔴 CLAUDE-AGENT-FAILED: No files created, rolling back", flush=True)
                        self.snapshot_manager.rollback_and_cleanup()
                        return {
                            "status": "failed",
                            "success": False,
                            "message": f"Claude Agent failed (code {return_code}): {stderr_output}",
                            "rollback": True
                        }

            except RuntimeError as e:
                # Claude Agent execution exception - ROLLBACK
                logger.error(f"[CLAUDE-AGENT] 🔴 Execution CRASHED: {e}")
                traceback.print_exc()
                self.snapshot_manager.rollback_and_cleanup()
                return {
                    "status": "failed",
                    "success": False,
                    "message": f"Claude Agent execution crashed: {str(e)}",
                    "rollback": True
                }

            # Step 7: Capture filesystem state AFTER Claude Agent (safe - continues on failure)
            logger.info(f"[CLAUDE-AGENT] Step 7: Capturing filesystem state after execution...")
            try:
                hashes_after = FilesystemSnapshot.get_file_hashes(self.frontend_src_path)
                logger.info(f"[CLAUDE-AGENT]   Found {len(hashes_after)} files after execution")
            except Exception as e:
                logger.warning(f"[CLAUDE-AGENT] ⚠️ Failed to capture post-execution state: {e}")
                hashes_after = {}
                issues.append(f"Post-execution snapshot failed: {e}")

            # Step 8: Compute changes (safe_diff - returns empty on failure)
            logger.info(f"[CLAUDE-AGENT] Step 8: Computing filesystem diff...")
            diff = safe_diff(hashes_before, hashes_after)

            files_added = diff['added']
            files_removed = diff['removed']
            files_modified = diff['modified']

            logger.info(f"[CLAUDE-AGENT]   Files added: {len(files_added)}")
            for f in files_added[:10]:
                logger.info(f"[CLAUDE-AGENT]     + {f}")
            if len(files_added) > 10:
                logger.info(f"[CLAUDE-AGENT]     ... and {len(files_added) - 10} more")

            logger.info(f"[CLAUDE-AGENT]   Files removed: {len(files_removed)}")
            for f in files_removed[:10]:
                logger.info(f"[CLAUDE-AGENT]     - {f}")
            if len(files_removed) > 10:
                logger.info(f"[CLAUDE-AGENT]     ... and {len(files_removed) - 10} more")

            logger.info(f"[CLAUDE-AGENT]   Files modified: {len(files_modified)}")
            for f in files_modified[:10]:
                logger.info(f"[CLAUDE-AGENT]     ~ {f}")
            if len(files_modified) > 10:
                logger.info(f"[CLAUDE-AGENT]     ... and {len(files_modified) - 10} more")

            # =============================================
            # FINAL RESULT (3-state outcome)
            # =============================================
            
            # Determine final message based on status
            if status == "success":
                message = "Claude Agent changes applied successfully"
            else:
                message = f"Claude Agent changes applied with issues: {'; '.join(issues[:5])}"
            
            result = {
                "status": status,
                "success": True,  # Both success and partial_success return success=True
                "message": message,
                "issues": issues,
                "files_added": len(files_added),
                "files_modified": len(files_modified),
                "files_removed": len(files_removed),
                "build_output": "Build skipped - handled by infrastructure pipeline",
                "rollback": False
            }
            
            logger.info(f"[CLAUDE-AGENT] ✅ Final status: {status}")
            if issues:
                logger.info(f"[CLAUDE-AGENT]   Issues: {issues}")
            logger.info(f"[CLAUDE-AGENT]   Files: +{len(files_added)} ~{len(files_modified)} -{len(files_removed)}")
            
            return result

        except Exception as e:
            # =============================================
            # GLOBAL EXCEPTION HANDLER (ONLY case for rollback)
            # =============================================
            logger.error(f"[CLAUDE-AGENT] 🔴 FATAL ERROR: {type(e).__name__}: {str(e)}")
            traceback.print_exc()

            # Attempt to rollback
            try:
                self.snapshot_manager.rollback_and_cleanup()
                logger.info("[CLAUDE-AGENT] Rollback completed")
            except Exception as rollback_error:
                logger.warning(f"[CLAUDE-AGENT] Rollback also failed: {rollback_error}")

            return {
                "status": "failed",
                "success": False,
                "message": f"FATAL ERROR in apply_changes: {str(e)}",
                "issues": [str(e)],
                "files_added": 0,
                "files_modified": 0,
                "files_removed": 0,
                "rollback": True
            }
        finally:
            # Cleanup snapshot to prevent leaks
            try:
                logger.info(f"[CLAUDE-AGENT] Step 13: Cleanup snapshot...")
                self.snapshot_manager.cleanup_snapshot()
            except Exception as e:
                logger.warning(f"[CLAUDE-AGENT] Snapshot cleanup failed: {str(e)}")

    # Backwards compatibility alias (deprecated - use apply_changes instead)
    async def apply_changes_via_acpx(self, goal_description: str, execution_id: str) -> Dict[str, Any]:
        """Deprecated: Use apply_changes() instead."""
        logger.warning("[DEPRECATED] apply_changes_via_acpx() is deprecated, use apply_changes()")
        return await self.apply_changes(goal_description, execution_id)

    async def _extract_required_pages_from_prompt(self, goal_description: str) -> List[str]:
        """
        Extract required pages from goal description using AI inference.

        Detection priority: Groq AI → Default pages

        Args:
            goal_description: Goal for changes

        Returns:
            List of required page names
        """
        print("\n" + "="*60, flush=True)
        print("🔍 PAGE INFERENCE START", flush=True)
        print("="*60, flush=True)

        required_pages = []

        # Step 1: Try Groq AI inference
        try:
            from groq_service import GroqService
            groq = GroqService()
                    
            inferred_pages = await groq.infer_pages(goal_description)
            if inferred_pages and len(inferred_pages) >= 3:
                required_pages = inferred_pages
                print(f"✅ PLANNER-GROQ-SUCCESS: Using {len(inferred_pages)} pages: {inferred_pages}", flush=True)
            else:
                print(f"⚠️  PLANNER-GROQ-INSUFFICIENT: Got {len(inferred_pages) if inferred_pages else 0} pages, need >= 3", flush=True)
        except Exception as e:
            logger.warning(f"[Planner] Groq inference failed: {e}")
            print(f"❌ PLANNER-GROQ-ERROR: {type(e).__name__}: {str(e)}", flush=True)

        # Step 2: Fallback to default pages
        if len(required_pages) < 3:
            required_pages = ["Dashboard", "Settings", "Overview"]
            print(f"⚠️  PLANNER-DEFAULT: Using default pages = {required_pages}", flush=True)

        # Remove duplicates while preserving order
        required_pages = list(dict.fromkeys(required_pages))

        print(f"🎯 PLANNER-FINAL: Pages = {required_pages}", flush=True)
        print(f"📊 PLANNER-COUNT: {len(required_pages)} pages detected", flush=True)
        print("="*60, flush=True)
        print("🔍 PAGE INFERENCE COMPLETE", flush=True)
        print("="*60 + "\n", flush=True)

        # Phase 9: Store allowed pages whitelist for guardrails
        self.allowed_pages = set(required_pages)

        # Cache pages to prevent double LLM calls
        self._cached_pages = required_pages

        return required_pages

    async def _run_claude_agent(self, prompt: str) -> Tuple[int, str, str]:
        """
        Run Claude Code Agent to execute the prompt.

        This replaces the ACPX subprocess call with direct Claude CLI integration.

        Args:
            prompt: The prompt to send to Claude

        Returns:
            Tuple of (return_code, stdout, stderr)

        Raises:
            RuntimeError: If ClaudeCodeAgent is not available or execution fails
        """
        if not CLAUDE_AGENT_AVAILABLE:
            raise RuntimeError("ClaudeCodeAgent not available - check claude_code_agent.py import")

        import asyncio

        stdout_lines = []
        stderr_lines = []

        def on_text(text: str) -> None:
            """Callback for streaming text output (persisted to DB)."""
            stdout_lines.append(text)
            # Also print to stdout for PM2 logs
            print(text, flush=True)

        def on_progress(progress: str) -> None:
            """Callback for progress updates (UI only - NOT persisted)."""
            # Print progress to stdout for PM2 visibility
            print(f"[CLAUDE-PROGRESS] {progress}", flush=True)

        logger.info(f"[CLAUDE-AGENT] Starting Claude Code Agent execution...")
        logger.info(f"[CLAUDE-AGENT] Working directory: {self.frontend_src_path}")
        logger.info(f"[CLAUDE-AGENT] Timeout: {CLAUDE_TIMEOUT}s")

        print("=" * 80, flush=True)
        print("🤖 CLAUDE CODE AGENT - STARTING", flush=True)
        print(f"   Working directory: {self.frontend_src_path}", flush=True)
        print(f"   Timeout: {CLAUDE_TIMEOUT}s", flush=True)
        print("=" * 80, flush=True)

        try:
            # Create Claude Code Agent instance
            async with ClaudeCodeAgent(
                repo_path=str(self.frontend_src_path),
                on_text=on_text,
                on_progress=on_progress,
            ) as agent:
                # Execute the query with timeout
                result = await agent.query(prompt, timeout=CLAUDE_TIMEOUT)

                # Determine return code based on result
                return_code = 0 if result is not None else 1

                logger.info(f"[CLAUDE-AGENT] Execution completed with return code: {return_code}")
                if result:
                    logger.info(f"[CLAUDE-AGENT] Result length: {len(result)} chars")

                print("=" * 80, flush=True)
                print("✅ CLAUDE CODE AGENT - COMPLETED", flush=True)
                print(f"   Return code: {return_code}", flush=True)
                print(f"   Output lines: {len(stdout_lines)}", flush=True)
                print("=" * 80, flush=True)

                return (return_code, '\n'.join(stdout_lines), '\n'.join(stderr_lines))

        except asyncio.TimeoutError:
            logger.error(f"[CLAUDE-AGENT] Timeout after {CLAUDE_TIMEOUT}s")
            print(f"🔴 CLAUDE-AGENT-TIMEOUT: Exceeded {CLAUDE_TIMEOUT}s", flush=True)
            # Return timeout as non-zero exit code
            return (124, '\n'.join(stdout_lines), f"Timeout after {CLAUDE_TIMEOUT}s")

        except Exception as e:
            logger.error(f"[CLAUDE-AGENT] Execution failed: {e}")
            print(f"🔴 CLAUDE-AGENT-ERROR: {type(e).__name__}: {str(e)}", flush=True)
            # Return error as non-zero exit code
            return (1, '\n'.join(stdout_lines), str(e))

        # Phase 9: Store allowed pages whitelist for guardrails
        self.allowed_pages = set(required_pages)

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

---

## EXECUTION ORDER — FOLLOW THIS EXACTLY

1. Fix routing (remove Welcome route, set `{default_page}` at `"/"`)
2. Create `src/layout/Navbar.tsx` with mobile hamburger menu
3. Integrate Navbar into `Layout.tsx`
4. Create each required page (fully implemented, 800+ chars)
5. Run `npm run build` — fix all errors until it succeeds
6. Serve dist: `npx serve dist -l 3000`
7. Verify with Chrome DevTools MCP — snapshot, console, routes, screenshot
8. Update AI index files (symbols, files, dependencies, summaries)

---

## CONSTRAINTS

**Never do:**
- Install new npm packages or modify `package.json`
- Run `npm install`, `npm add`, or `npm update`
- Modify files in `src/components/ui/` (use them, don't change them)
- Modify `vite.config.*`, `tsconfig.json`, or any backend/env files
- Create pages not in the required list
- Leave any page as a stub, placeholder, or under 800 characters
- Change project architecture

**Only modify files in:**
- `src/pages/`
- `src/components/` (custom components here, NOT in `src/components/ui/`)
- `src/layout/`
- `src/features/`
- `agent/` (AI index files and agent configuration)

**Do NOT scan:** `node_modules/`, `dist/`, `build/`, `.git/`

**Available UI components** (from `src/components/ui/`):
Button, Card, Input, Label, Select, Textarea, Dialog, Sheet, Dropdown, Popover, Table, Badge, Avatar, Separator — and more. Check the folder for the full list.

**Icons:** `import {{ IconName }} from 'lucide-react'`

---

## STEP 1 — FIX ROUTING

Read `src/App.tsx`. Delete ALL routes at `path="/"`. Add exactly one. Do this BEFORE creating any pages.

```tsx
<Routes>
  <Route element={{<Layout />}}>
    <Route path="/" element={{<{default_page} />}} />   {{/* ONLY ONE route at "/" */}}
    <Route path="/team" element={{<Team />}} />
    {{/* other routes */}}
  </Route>
</Routes>
```

Rules:
- Exactly ONE route at `"/"` — there may be multiple duplicates in the file, delete them all
- All routes nested inside `<Route element={{<Layout />}}>`
- If no Layout wrapper exists, add it
- Layout MUST use `<Outlet />`, not a `children` prop
- Pages render at `<Outlet />`, not via children prop
- Layout uses flex for full-screen layout with overflow handling
- Do not leave Welcome at `"/"`

Verify routing is correct BEFORE creating pages. Wrong routing = blank page.

---

## STEP 2 — NAVBAR

Create `src/layout/Navbar.tsx`:

```tsx
import {{ useState }} from 'react';
import {{ NavLink }} from 'react-router-dom';
import {{ Menu, X, Home }} from 'lucide-react';

export default function Navbar() {{
  const [isOpen, setIsOpen] = useState(false);

  const links = [
    {{ to: '/', label: '{required_pages_list[0] if required_pages_list else "Dashboard"}', icon: Home }},
    // add remaining page links
  ];

  return (
    <nav className="bg-white border-b">
      {{/* Desktop Menu */}}
      <div className="hidden md:flex">
        {{links.map(link => (
          <NavLink key={{link.to}} to={{link.to}}>
            <span className="flex items-center gap-2">
              <link.icon className="w-4 h-4" />
              {{link.label}}
            </span>
          </NavLink>
        ))}}
      </div>

      {{/* Mobile Hamburger */}}
      <button className="md:hidden" onClick={{() => setIsOpen(!isOpen)}}>
        {{isOpen ? <X /> : <Menu />}}
      </button>

      {{/* Mobile Menu Overlay */}}
      {{isOpen && (
        <div className="md:hidden fixed inset-0 bg-white z-50">
          {{/* mobile menu links */}}
        </div>
      )}}
    </nav>
  );
}}
```

Requirements:
- Desktop: horizontal menu (`hidden md:flex`) with links to all required pages
- Mobile: hamburger (`md:hidden`) toggles full-screen overlay or slide-in sidebar
- Use `NavLink` from `react-router-dom` for active link highlighting
- Include links to: {', '.join(required_pages_list)}
- Touch-friendly tap targets (min 44px height)
- Smooth open/close transitions
- Import Navbar in `Layout.tsx` and place it in the header section

**Navigation link rule** — always wrap multiple children in a single element:

```tsx
// Wrong — causes React.Children.only error
<Link to="/dashboard">
  <Icon />
  Dashboard
</Link>

// Correct
<Link to="/dashboard">
  <span className="flex items-center gap-2">
    <Icon />
    Dashboard
  </span>
</Link>
```

Same rule applies to: Button, NavLink, and any component expecting a single child.

---

## STEP 3 — REQUIRED PAGES

Create exactly these pages, no more, no less:

{required_pages_str}

**Naming rules:**
- Pattern: `src/pages/{{PageName}}.tsx`
- No `Page` suffix: `Dashboard.tsx` ✓ not `DashboardPage.tsx` ✗
- No `Overview` suffix: `Analytics.tsx` ✓ not `AnalyticsOverview.tsx` ✗
- No variations: `Reports.tsx` ✓ not `ReportsPage.tsx` ✗
- Do NOT create extras like: `Account.tsx`, `Activity.tsx`, `Users.tsx`, `Team.tsx`, `Billing.tsx`

**Every page must have ALL of the following:**
- Proper imports (React, hooks, Lucide icons)
- State management (`useState`, `useEffect` as needed)
- Real UI components — cards, tables, forms, data displays
- Tailwind CSS responsive layout with `md:` breakpoints
- Functional interactions (clicks, forms, modals)
- Loading states and error handling
- Mobile-responsive design
- TypeScript types properly defined
- 800+ characters — no stubs, no TODOs, no "coming soon", no placeholders

**Forbidden patterns — will cause build failure:**
```
return <div></div>
return null
return <div>Dashboard</div>
return <div className="p-4">Page content coming soon</div>
// TODO: Add content
// Page content will be generated by AI
```

**Reference implementation — copy this pattern:**

```tsx
import {{ useState, useEffect }} from 'react';
import {{ Users, DollarSign, TrendingUp, Activity }} from 'lucide-react';

interface StatCardProps {{
  title: string;
  value: string | number;
  icon: React.ReactNode;
  trend?: string;
}}

function StatCard({{ title, value, icon, trend }}: StatCardProps) {{
  return (
    <div className="bg-white p-6 rounded-lg shadow-sm border">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-gray-600">{{title}}</p>
          <p className="text-2xl font-bold mt-1">{{value}}</p>
          {{trend && <p className="text-sm text-green-600 mt-1">{{trend}}</p>}}
        </div>
        <div className="p-3 bg-blue-50 rounded-full">{{icon}}</div>
      </div>
    </div>
  );
}}

export default function Dashboard() {{
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState({{ users: 0, revenue: 0, growth: 0, activity: 0 }});

  useEffect(() => {{
    setTimeout(() => {{
      setStats({{ users: 1234, revenue: 50000, growth: 12.5, activity: 89 }});
      setLoading(false);
    }}, 500);
  }}, []);

  if (loading) return <div className="p-6">Loading...</div>;

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Dashboard</h1>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard title="Total Users" value={{stats.users.toLocaleString()}} icon={{<Users className="w-6 h-6 text-blue-500" />}} trend="+12%" />
        <StatCard title="Revenue" value={{`$${{stats.revenue.toLocaleString()}}`}} icon={{<DollarSign className="w-6 h-6 text-green-500" />}} trend="+8%" />
        <StatCard title="Growth" value={{`${{stats.growth}}%`}} icon={{<TrendingUp className="w-6 h-6 text-purple-500" />}} />
        <StatCard title="Activity" value={{stats.activity}} icon={{<Activity className="w-6 h-6 text-orange-500" />}} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white p-6 rounded-lg shadow-sm border">
          <h2 className="font-semibold mb-4">Recent Activity</h2>
          <div className="space-y-3">
            {{[1, 2, 3].map(i => (
              <div key={{i}} className="flex items-center gap-3 p-3 bg-gray-50 rounded">
                <div className="w-2 h-2 bg-blue-500 rounded-full" />
                <span className="text-sm">Activity item {{i}}</span>
              </div>
            ))}}
          </div>
        </div>

        <div className="bg-white p-6 rounded-lg shadow-sm border">
          <h2 className="font-semibold mb-4">Quick Actions</h2>
          <div className="grid grid-cols-2 gap-3">
            <button className="p-3 bg-blue-50 text-blue-600 rounded-lg hover:bg-blue-100">Add User</button>
            <button className="p-3 bg-green-50 text-green-600 rounded-lg hover:bg-green-100">New Report</button>
            <button className="p-3 bg-purple-50 text-purple-600 rounded-lg hover:bg-purple-100">Settings</button>
            <button className="p-3 bg-orange-50 text-orange-600 rounded-lg hover:bg-orange-100">Help</button>
          </div>
        </div>
      </div>
    </div>
  );
}}
```

---

## STEP 4 — PAGE SPECIFICATIONS

{page_specs_section}

---

## STEP 5 — UI/UX QUALITY STANDARDS

This is an initial UI build — focus on SPEED + visual completeness. Static/mock data is fine.

**For all UI/UX decisions, use the ui-ux-pro-max skill:**
- Skill name: `ui-ux-pro-max`
- GitHub: https://github.com/nextlevelbuilder/ui-ux-pro-max-skill
- Invoke with: `/ui-ux-pro-max [your request]`
- Examples:
  - `/ui-ux-pro-max review my dashboard component`
  - `/ui-ux-pro-max create a glassmorphism button`
  - `/ui-ux-pro-max improve the accessibility of my form`

This skill covers: modern component patterns, responsive design, WCAG 2.1 accessibility, color theory, typography, layout composition, micro-interactions, mobile-first design, professional polish.

**Before implementing any UI component:**
1. Apply ui-ux-pro-max principles
2. Use modern design patterns (not Bootstrap-style layouts)
3. Ensure mobile-responsive implementation
4. Use proper visual hierarchy and spacing
5. Implement smooth transitions and micro-interactions
6. Follow accessibility best practices

**Premium UI — apply to all pages:**
- glassmorphism: `backdrop-blur-xl` + semi-transparent backgrounds
- depth: soft shadows, `hover:shadow-xl`, `hover:scale-[1.02]` on cards
- gradient accents: blue → purple headers and icon backgrounds
- transitions: `transition-all duration-300` on all interactive elements
- Stripe / Linear aesthetic — not flat or plain white sections

**Per page:** 2–3 main UI sections max. No over-engineering, no edge cases, no deeply nested layouts.

**Avoid:** flat UI, plain white sections without depth, static non-interactive components.

**For complex features, build UI shell only:**
- Block editor → UI layout only
- Canvas → static visual layout
- Charts → static UI with sample data

---

## STEP 6 — BUILD VERIFICATION

```bash
npm run build
```

If it fails, fix ALL TypeScript and build errors. Re-run until it passes.

Verify before serving:
- Each page file is 800+ characters
- No files contain "placeholder", "TODO", or "coming soon"

Then serve. Multiple Claude Code sessions may be running in parallel — always check if the port is in use before serving:

```bash
# Check if 3000 is in use; if so, find a free port in the 4000–5000 range
lsof -i :3000 && echo "Port 3000 in use" || npx serve dist -l 3000

# If 3000 is taken, run this instead:
for port in 4000 4001 4002 4003 4004 4005; do
  lsof -i :$port > /dev/null 2>&1 || {{ echo "Using port $port"; npx serve dist -l $port; break; }}
done
```

Note the port you end up using — you need it in the next step.

---

## STEP 7 — BROWSER VERIFICATION WITH CHROME DEVTOOLS MCP

After serving, use Chrome DevTools MCP to verify the running app. Do NOT skip this step.

**1. Open the app**
```
navigate to: http://localhost:PORT   ← use the actual port from Step 6
```

**2. Take a snapshot**
Use DevTools MCP `snapshot` to capture the page state. Confirm:
- Page is not blank or white
- Layout renders correctly (navbar + content area visible)
- No loading spinners stuck indefinitely

**3. Check console for errors**
Use DevTools MCP `console` to inspect logs. Fix any errors found:
- No React runtime errors
- No `Cannot read properties of undefined`
- No failed imports or missing modules
- No TypeScript/JSX errors leaked to runtime

**4. Verify every route**
Click through each required page using DevTools MCP `click`:
- Navigate to each route in {', '.join(required_pages_list) if required_pages_list else 'all required pages'}
- After each navigation: take a snapshot to confirm the page rendered
- Confirm no blank screens, no 404s, no white pages

**5. Check network tab**
Use DevTools MCP `network` to verify:
- All JS/CSS chunks loaded (no 404s)
- No failed API calls blocking render

**6. Take final screenshot**
Use DevTools MCP `screenshot` to capture the final confirmed state. This is the proof of completion.

**If any check fails:** fix the issue, rebuild (`npm run build`), re-serve, and re-verify.

**7. Stop the server**
Once verification is complete, stop the serve process to free the port:

```bash
kill $(lsof -t -i:PORT)
```

Do not leave the server running after verification is done.

---

## STEP 8 — UPDATE AI INDEX

After a successful build, update all four AI index files:

**`agent/ai_index/symbols.json`** — add new components/pages with file path and line numbers:
```json
"NewPage": {{
  "type": "component",
  "file": "src/pages/NewPage.tsx",
  "start_line": 1,
  "end_line": 50,
  "module": "pages",
  "description": "New page description"
}}
```

**`agent/ai_index/files.json`** — add new file entries with line count and purpose; update routes array in App.tsx entry.

**`agent/ai_index/dependencies.json`** — add new import relationships.

**`agent/ai_index/summaries.json`** — add brief description for each new file.

AI index keeps the codebase navigable for future AI edits.

---

## FINAL CHECKLIST

Complete in order before marking task complete:

- [ ] Routing fixed — Welcome removed, single `{default_page}` at `"/"`, all routes inside Layout wrapper
- [ ] `src/layout/Navbar.tsx` created — mobile hamburger, NavLink to all required pages: {', '.join(required_pages_list)}
- [ ] Navbar integrated into `Layout.tsx` header
- [ ] All required pages created with exact filenames, 800+ chars, real content, no placeholders:
      {required_pages_str}
- [ ] No unauthorized pages exist in `src/pages/`
- [ ] `npm run build` succeeds with zero errors
- [ ] Any TypeScript or build errors fixed and `npm run build` re-run to confirm
- [ ] Port checked — free port selected (3000 or 4000–5000 range), app serving
- [ ] Chrome DevTools MCP verification complete:
  - [ ] Navigated to http://localhost:PORT (the port confirmed free in Step 6)
  - [ ] Snapshot taken — layout visible, not blank/white
  - [ ] Console checked — no runtime errors
  - [ ] Every required page route clicked and snapshot confirmed
  - [ ] Network tab checked — no 404s on JS/CSS chunks
  - [ ] Final screenshot taken as proof of completion
  - [ ] Server stopped (`kill $(lsof -t -i:PORT)`)
- [ ] AI index files updated (symbols, files, dependencies, summaries)
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
            # logger.info(f"[Phase4] Page specs built for {len(required_pages)} pages")
            return specs_section
        except Exception as e:
            logger.error(f"[Phase4] Error loading page specs: {e}")
            # Fallback: return empty section
            return "\n## Page Specifications\n\nNote: Page specs not available, using page templates only.\n"



