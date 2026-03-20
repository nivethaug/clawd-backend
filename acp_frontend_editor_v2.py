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

# Configure logging - WARNING level to suppress INFO messages
logging.basicConfig(
    level=logging.WARNING,
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
            # Step 1: Install dependencies (pnpm first, npm fallback)
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
    Install frontend dependencies using pnpm (fast) with npm fallback (safe).
    
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

    # ⚡ NON-PM2 → TRY PNPM FIRST
    try:
        logger.info("⚡ Trying pnpm install (non-PM2 mode)...")
        print("⚡ [DEPS] Trying pnpm install (non-PM2 mode)...", flush=True)

        result = subprocess.run(
            ["pnpm", "install", "--prefer-offline"],
            cwd=str(frontend_path),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=BUILD_TIMEOUT
        )

        if result.returncode == 0:
            logger.info("✅ pnpm install successful")
            print("✅ [DEPS] pnpm install successful", flush=True)
            print("=" * 60, flush=True)
            return True, "pnpm install successful"

        logger.warning(f"⚠️ pnpm install failed (code {result.returncode}), falling back to npm")
        print(f"⚠️  [DEPS] pnpm failed (code {result.returncode}), falling back to npm", flush=True)
        if result.stderr:
            print(f"    [DEPS] stderr: {result.stderr[:200]}")

    except FileNotFoundError:
        logger.warning("⚠️ pnpm not found, falling back to npm")
        print("⚠️  [DEPS] pnpm not found, falling back to npm", flush=True)
    except Exception as e:
        logger.warning(f"⚠️ pnpm error: {e}, falling back to npm")
        print(f"⚠️  [DEPS] pnpm error: {e}, falling back to npm", flush=True)

    # 🔁 FALLBACK TO NPM
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
            logger.info(f"[ACPX-V2] 🔴 HEARTBEAT: Starting Phase 9 (Partial Commit System)")
            logger.info(f"[ACPX-V2] 🔴 HEARTBEAT: Project: {self.project_name}")
            logger.info(f"[ACPX-V2] 🔴 HEARTBEAT: Execution ID: {execution_id}")

            # Step 1: Create snapshot (safe - continues on failure)
            logger.info(f"[ACPX-V2] Step 1: Creating filesystem snapshot...")
            snapshot_success, snapshot_msg = safe_snapshot(self.snapshot_manager, max_retries=1)
            if not snapshot_success or "warning" in snapshot_msg.lower():
                issues.append(f"Snapshot warning: {snapshot_msg}")
                logger.warning(f"[ACPX-V2] ⚠️ Snapshot issue (continuing): {snapshot_msg}")
            else:
                logger.info(f"[ACPX-V2] ✓ Snapshot created")

            # Step 2: Generate page manifest from planner (Phase 5 - NEW)
            logger.info(f"[ACPX-V2] Step 2: Generating page manifest (Phase 5)...")
            required_pages = await self._extract_required_pages_from_prompt(goal_description)
            logger.info(f"[ACPX-V2]   Planner detected pages: {required_pages}")

            # Write manifest to project directory
            manifest_success = self.manifest_manager.write_manifest(required_pages)
            if not manifest_success:
                issues.append("Failed to write page manifest")
                logger.warning(f"[ACPX-V2] ⚠️ Failed to write page manifest (continuing)")

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

            # Step 3: Capture filesystem state BEFORE ACPX (moved before scaffold)
            logger.info(f"[ACPX-V2] Step 3: Capturing filesystem state before ACPX...")
            try:
                hashes_before = FilesystemSnapshot.get_file_hashes(self.frontend_src_path)
                logger.info(f"[ACPX-V2]   Found {len(hashes_before)} files before ACPX")
            except Exception as e:
                logger.warning(f"[ACPX-V2] ⚠️ Failed to capture pre-ACPX state: {e}")
                hashes_before = {}
                issues.append(f"Pre-ACPX snapshot failed: {e}")

            # Step 4: Scaffold pages from manifest (Phase 5 - NEW)
            logger.info(f"[ACPX-V2] Step 4: Scaffolding pages from manifest...")
            scaffold_result = self.manifest_manager.scaffold_pages(required_pages, create_placeholder=True)
            if not scaffold_result:
                issues.append("Some pages failed to scaffold")
                logger.warning(f"[ACPX-V2] ⚠️ Some pages failed to scaffold, continuing...")

            # Step 5: Build ACPX prompt using manifest pages
            logger.info(f"[ACPX-V2] Step 5: Building ACPX prompt (using manifest pages)...")
            prompt = await self._build_acpx_prompt(goal_description)

            # Step 6: Run ACPX with Idle + Hard Timeout Protection
            try:
                print("=" * 60)
                print("PHASE_9_APPLY")
                logger.info(f"[ACPX-V2] Step 5b: Running ACPX with idle + hard timeout protection...")
                
                # Build command: acpx --format quiet claude exec "<prompt>"
                # cwd is set in Popen, not in command args
                cmd = [
                    "acpx",
                    "--format", "quiet",
                    "claude",
                    "exec",
                    str(prompt)
                ]
                
                HARD_TIMEOUT = 900  # 15 minutes max (strict failure)
                IDLE_TIMEOUT = 450  # 7.5 minutes without output (tolerant - check edits)

                logger.info(f"[ACPX-V2]   Command: acpx --format quiet claude exec <prompt>")
                logger.info(f"[ACPX-V2]   Working directory: {self.frontend_src_path}")
                logger.info(f"[ACPX-V2]   Hard timeout: {HARD_TIMEOUT}s, Idle timeout: {IDLE_TIMEOUT}s")

                # Robust debug logging
                print("ACPX CMD:", " ".join(cmd[:4]) + " <prompt>")
                print("[ACPX] cwd:", str(self.frontend_src_path))
                print(f"[ACPX] running with idle={IDLE_TIMEOUT}s, hard={HARD_TIMEOUT}s timeouts")

                import os
                import signal
                import time
                import threading
                
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
                
                stdout_lines = []
                stderr_lines = []
                last_output_time = time.time()
                start_time = time.time()
                hard_timeout_killed = False
                idle_timeout_killed = False
                
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
                
                # Watchdog loop
                prev_stdout_len = 0
                prev_stderr_len = 0
                
                while process.poll() is None:
                    current_time = time.time()
                    elapsed = current_time - start_time
                    
                    # Check for NEW output (length changed)
                    current_stdout_len = len(stdout_lines)
                    current_stderr_len = len(stderr_lines)
                    
                    if current_stdout_len > prev_stdout_len or current_stderr_len > prev_stderr_len:
                        last_output_time = current_time
                        prev_stdout_len = current_stdout_len
                        prev_stderr_len = current_stderr_len
                    
                    idle_time = current_time - last_output_time
                    
                    # Hard timeout check (STRICT FAILURE)
                    if elapsed > HARD_TIMEOUT:
                        logger.error(f"[ACPX-V2] 🔴 HARD TIMEOUT: {elapsed:.1f}s > {HARD_TIMEOUT}s — killing process group")
                        print(f"🔴 ACPX-V2-HARD-TIMEOUT: Killing process group {process.pid}", flush=True)
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                            # Reap process to avoid zombies
                            stdout_remain, stderr_remain = process.communicate()
                            stdout_lines.append(stdout_remain or '')
                            stderr_lines.append(stderr_remain or '')
                        except (ProcessLookupError, OSError, AttributeError) as e:
                            logger.warning(f"[ACPX-V2] Process group kill failed: {e}")
                        hard_timeout_killed = True
                        break
                    
                    # Idle timeout check (TOLERANT - check if edits succeeded)
                    if idle_time > IDLE_TIMEOUT:
                        logger.warning(f"[ACPX-V2] ⚠️ IDLE TIMEOUT: {idle_time:.1f}s > {IDLE_TIMEOUT}s — killing process group")
                        print(f"⚠️ ACPX-V2-IDLE-TIMEOUT: Killing process group {process.pid}", flush=True)
                        try:
                            # Send SIGTERM to process group
                            os.killpg(process.pid, signal.SIGTERM)
                            # Wait 5 seconds for graceful shutdown
                            try:
                                stdout_remain, stderr_remain = process.communicate(timeout=5)
                                stdout_lines.append(stdout_remain or '')
                                stderr_lines.append(stderr_remain or '')
                                logger.info(f"[ACPX-V2] Process group exited after SIGTERM")
                            except subprocess.TimeoutExpired:
                                # Escalate to SIGKILL
                                logger.warning(f"[ACPX-V2] Process still alive after 5s, sending SIGKILL")
                                print(f"🔴 ACPX-V2-SIGKILL: Escalating to SIGKILL for process group {process.pid}", flush=True)
                                try:
                                    os.killpg(process.pid, signal.SIGKILL)
                                except (ProcessLookupError, OSError, AttributeError):
                                    pass
                                # Final communicate() to reap process
                                stdout_remain, stderr_remain = process.communicate()
                                stdout_lines.append(stdout_remain or '')
                                stderr_lines.append(stderr_remain or '')
                        except (ProcessLookupError, OSError, AttributeError) as e:
                            logger.warning(f"[ACPX-V2] Process group kill failed: {e}")
                        
                        # Verify process actually died
                        try:
                            # Check if process still exists
                            os.kill(process.pid, 0)  # Doesn't actually kill, just checks
                            logger.warning(f"[ACPX-V2] Process {process.pid} still alive after kill, using aggressive cleanup")
                            self._kill_process_tree(process.pid)
                        except (ProcessLookupError, OSError):
                            # Process is dead, good
                            pass
                        
                        idle_timeout_killed = True
                        break
                    
                    time.sleep(0.5)
                
                # Wait for reader threads to finish
                stdout_thread.join(timeout=2)
                stderr_thread.join(timeout=2)
                
                # Collect output
                stdout_output = ''.join(stdout_lines)
                stderr_output = ''.join(stderr_lines)
                return_code = process.returncode

                # Robust debug logging after execution - FULL OUTPUT
                print("=" * 80, flush=True)
                print("ACPX RETURN CODE:", return_code, flush=True)
                print("=" * 80, flush=True)
                print("ACPX STDOUT:", flush=True)
                print(stdout_output if stdout_output else "(empty)", flush=True)
                print("=" * 80, flush=True)
                print("ACPX STDERR:", flush=True)
                print(stderr_output if stderr_output else "(empty)", flush=True)
                print("=" * 80, flush=True)
                
                # =============================================
                # PARTIAL COMMIT: Timeout handling (NO ROLLBACK)
                # =============================================
                
                # Handle HARD timeout kills (PARTIAL_SUCCESS - keep files if any exist)
                if hard_timeout_killed:
                    self._kill_process_tree(process.pid)
                    # Check if any files were created
                    created_files = list(self.frontend_src_path.glob("**/*.tsx"))
                    if created_files:
                        issues.append(f"Hard timeout exceeded ({HARD_TIMEOUT}s)")
                        logger.warning(f"[ACPX-V2] ⚠️ Hard timeout ({HARD_TIMEOUT}s) — keeping {len(created_files)} generated files")
                        print(f"⚠️ ACPX-HARD-TIMEOUT: Keeping {len(created_files)} generated files (partial success)", flush=True)
                        status = "partial_success"
                    else:
                        logger.error(f"[ACPX-V2] 🔴 Hard timeout and NO files created — rollback")
                        print(f"🔴 ACPX-HARD-TIMEOUT: No files created, rolling back", flush=True)
                        self.snapshot_manager.rollback_and_cleanup()
                        return {
                            "status": "failed",
                            "success": False,
                            "message": f"Hard timeout ({HARD_TIMEOUT}s) and no files created",
                            "rollback": True
                        }
                
                # Handle IDLE timeout kills (PARTIAL_SUCCESS - keep files if any exist)
                elif idle_timeout_killed:
                    # Check if any files were created
                    created_files = list(self.frontend_src_path.glob("**/*.tsx"))
                    if created_files:
                        issues.append(f"Idle timeout exceeded ({IDLE_TIMEOUT}s)")
                        logger.warning(f"[ACPX-V2] ⚠️ Idle timeout — keeping {len(created_files)} generated files")
                        print(f"⚠️ ACPX-IDLE-TIMEOUT: Keeping {len(created_files)} generated files (partial success)", flush=True)
                        status = "partial_success"
                    else:
                        logger.error(f"[ACPX-V2] 🔴 Idle timeout and NO files created — rollback")
                        print(f"🔴 ACPX-IDLE-TIMEOUT: No files created, rolling back", flush=True)
                        self.snapshot_manager.rollback_and_cleanup()
                        return {
                            "status": "failed",
                            "success": False,
                            "message": f"Idle timeout ({IDLE_TIMEOUT}s) and no files created",
                            "rollback": True
                        }
                    print(f"⚠️ ACPX-IDLE-TIMEOUT: Keeping generated files (partial success)", flush=True)
                    status = "partial_success"

            except RuntimeError as e:
                # ACPX execution exception - THIS IS THE ONLY CASE FOR ROLLBACK
                logger.error(f"[ACPX-V2] 🔴 ACPX execution CRASHED: {e}")
                traceback.print_exc()
                self.snapshot_manager.rollback_and_cleanup()
                return {
                    "status": "failed",
                    "success": False,
                    "message": f"ACPX execution crashed: {str(e)}",
                    "rollback": True
                }

            # Step 6: Capture filesystem state AFTER ACPX (safe - continues on failure)
            logger.info(f"[ACPX-V2] Step 6: Capturing filesystem state after ACPX...")
            try:
                hashes_after = FilesystemSnapshot.get_file_hashes(self.frontend_src_path)
                logger.info(f"[ACPX-V2]   Found {len(hashes_after)} files after ACPX")
            except Exception as e:
                logger.warning(f"[ACPX-V2] ⚠️ Failed to capture post-ACPX state: {e}")
                hashes_after = {}
                issues.append(f"Post-ACPX snapshot failed: {e}")

            # Step 7: Compute changes (safe_diff - returns empty on failure)
            logger.info(f"[ACPX-V2] Step 7: Computing filesystem diff...")
            diff = safe_diff(hashes_before, hashes_after)

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

            # Step 8: Enforce file limits (trim excess, NO rollback)
            logger.info(f"[ACPX-V2] Step 8: Enforcing file limits...")
            kept_files, removed_files = enforce_file_limit(files_added, self.max_new_files, self.frontend_src_path)
            if removed_files:
                issues.append(f"Trimmed {len(removed_files)} excess files (limit: {self.max_new_files})")
                status = "partial_success"
                files_added = kept_files  # Update for final count
            else:
                logger.info(f"[ACPX-V2]   ✓ File limit OK ({len(files_added)}/{self.max_new_files})")

            # Step 9: Validate and filter paths (remove invalid, NO rollback)
            logger.info(f"[ACPX-V2] Step 9: Validating paths...")
            valid_paths, invalid_paths = filter_valid_paths(files_added, self.validator)
            
            if invalid_paths:
                deleted_count = delete_invalid_files(invalid_paths, self.frontend_src_path)
                issues.append(f"Removed {deleted_count} files at invalid paths")
                status = "partial_success"
                files_added = valid_paths  # Update for final count
                logger.warning(f"[ACPX-V2]   ⚠️ Removed {deleted_count} invalid files")
            else:
                logger.info(f"[ACPX-V2]   ✓ All paths valid")

            # Step 10: Enforce page guardrails (BEFORE build to prevent routing issues)
            logger.info(f"[ACPX-V2] Step 10: Enforcing page guardrails (BEFORE build)...")
            try:
                unauthorized_removed = self._enforce_page_guardrails()
                if unauthorized_removed > 0:
                    issues.append(f"Removed {unauthorized_removed} unauthorized page(s)")
                    logger.info(f"[ACPX-V2]   ⚠️  Removed {unauthorized_removed} unauthorized page(s)")
                else:
                    logger.info(f"[ACPX-V2]   ✓ All pages authorized")
            except Exception as e:
                logger.warning(f"[ACPX-V2] ⚠️ Guardrail enforcement failed but continuing: {str(e)}")

            # Step 10.5: Routing fix DISABLED - ACPX handles routing
            #     logger.info("[ACPX-V2] Step 10.5: Fixing routing programmatically...")
            #     
            #     # Determine default page (first allowed page)
            #     default_page = list(self.allowed_pages)[0] if self.allowed_pages else "Dashboard"
            #     app_tsx_path = self.frontend_src_path / "App.tsx"
            #     
            #     if app_tsx_path.exists():
            #         content = app_tsx_path.read_text()
            #         original_content = content
            #         
            #         # Count routes at "/" before fix
            #         routes_at_root = re.findall(r'<Route\s+path="/"', content)
            #         logger.info(f"[ACPX-V2]   Found {len(routes_at_root)} routes at '/' before fix")
            #         
            #         # Fix 1: Remove ALL routes at "/" (duplicates and misplaced routes)
            #         content = re.sub(
            #             r'<Route\s+path="/"\s+element=\{<[A-Za-z]+\s*/?>\s*\}\s*/>\s*',
            #             '',
            #             content
            #         )
            #         content = re.sub(
            #             r'<Route\s+path="/"\s+element=\{<[A-Za-z]+[^>]*>\s*\}\s*/?>\s*',
            #             '',
            #             content,
            #             flags=re.DOTALL
            #         )
            #         
            #         # Fix 2: Remove any /dashboard route
            #         content = re.sub(
            #             r'<Route\s+path="/dashboard"\s+element=\{<[A-Za-z]+\s*/?\s*\}\s*/?>\s*',
            #             '',
            #             content
            #         )
            #         
            #         # Fix 3: Remove orphaned routes outside Layout wrapper
            #         content = re.sub(
            #             r'(</Route>)\s*<Route\s+[^>]+/?>\s*(</Routes>)',
            #             r'\1\n          \2',
            #             content
            #         )
            #         
            #         routes_at_root_after = re.findall(r'<Route\s+path="/"', content)
            #         logger.info(f"[ACPX-V2]   Found {len(routes_at_root_after)} routes at '/' after removal")
            #         
            #         # Fix 4: Add default route inside Layout wrapper
            #         has_layout = '<Route element={<Layout />' in content or '<Route element={<Layout/>' in content
            #         
            #         if has_layout:
            #             layout_pattern = r'(<Route\s+element=\{<Layout\s*/>\}>\s*\n)'
            #             layout_match = re.search(layout_pattern, content)
            #             if layout_match:
            #                 insert_pos = layout_match.end()
            #                 default_route = f'          <Route path="/" element={{<{default_page} />}} />\n'
            #                 content = content[:insert_pos] + default_route + content[insert_pos:]
            #                 logger.info(f"[ACPX-V2]   Added {default_page} route inside Layout wrapper")
            #         else:
            #             routes_pattern = r'<Routes>(.*?)</Routes>'
            #             routes_match = re.search(routes_pattern, content, re.DOTALL)
            #             
            #             if routes_match:
            #                 routes_content = routes_match.group(1).strip()
            #                 route_pattern = r'<Route\s+[^>]+/>'
            #                 individual_routes = re.findall(route_pattern, routes_content)
            #                 formatted_routes = '\n        '.join([f'{r}' for r in individual_routes])
            #                 
            #                 new_routes = f'''<Route element={{<Layout />}}>
            #           <Route path="/" element={{<{default_page} />}} />
            #         {formatted_routes}
            #       </Route>'''
            #                 
            #                 content = content[:routes_match.start(1)] + new_routes + content[routes_match.end(1):]
            #                 logger.info(f"[ACPX-V2]   Added Layout wrapper with {default_page} at /")
            #         
            #         if content != original_content:
            #             app_tsx_path.write_text(content)
            #             logger.info(f"[ACPX-V2]   ✓ Fixed routing: {default_page} is now at / with Layout")
            #         else:
            #             logger.info("[ACPX-V2]   Routing appears correct")
            #     else:
            #         logger.warning("[ACPX-V2]   App.tsx not found, skipping routing fix")
            #                 
            # except Exception as e:
            #     traceback.print_exc()
            #     logger.warning(f"[ACPX-V2] Routing fix failed but continuing: {str(e)}")
            logger.info("[ACPX-V2] Step 10.5: Routing fix DISABLED - ACPX handles routing")

            # Step 10.6: Fix Layout components - Replace {children} with <Outlet />
            logger.info("[ACPX-V2] Step 10.6: Fixing Layout components to use Outlet...")
            try:
                # Find all Layout files
                layout_patterns = [
                    self.frontend_src_path / "layout" / "Layout.tsx",
                    self.frontend_src_path / "layouts" / "Layout.tsx",
                    self.frontend_src_path / "app" / "layouts" / "AppLayout.tsx",
                ]
                
                layout_files = [p for p in layout_patterns if p.exists()]
                for layout_dir in ["layout", "layouts", "app/layouts"]:
                    layout_path = self.frontend_src_path / layout_dir
                    if layout_path.exists():
                        layout_files.extend(layout_path.glob("*Layout*.tsx"))
                
                layout_files = list(set(layout_files))
                
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
                            import_line = "import { Outlet } from 'react-router-dom';\n"
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
                    
                    except Exception as e:
                        logger.warning(f"[ACPX-V2]   Failed to fix {layout_file}: {e}")
                
            except Exception as e:
                logger.warning(f"[ACPX-V2] ⚠️ Layout fix failed but continuing: {str(e)}")

            # Step 11: Build gate skipped - build handled by infrastructure pipeline
            logger.info("[ACPX-V2] Step 11: Build gate skipped — build handled by infrastructure pipeline")

            # Step 12: Post-process - Detect empty/placeholder pages (remove if found)
            logger.info("[ACPX-V2] Step 12: Checking for empty/placeholder pages...")
            try:
                empty_pages = []
                pages_dir = self.frontend_src_path / "pages"
                
                if pages_dir.exists():
                    for page_file in pages_dir.glob("*.tsx"):
                        content = page_file.read_text()
                        
                        # Check for placeholder content
                        is_empty = (
                            len(content) < 800 or
                            "Page content will be generated by AI" in content or
                            "placeholder" in content.lower() or
                            "will be generated" in content.lower() or
                            content.strip().endswith("return <div></div>;") or
                            content.strip().endswith("return null;") or
                            (content.count("return") == 1 and len(content) < 1000)
                        )
                        
                        if is_empty:
                            page_name = page_file.stem
                            empty_pages.append(page_name)
                            logger.warning(f"[ACPX-V2]   ⚠️  Empty/placeholder page detected: {page_name}")
                            
                            try:
                                page_file.unlink()
                                logger.warning(f"[ACPX-V2]   🗑️  Removed placeholder page: {page_name}")
                            except Exception as remove_error:
                                logger.error(f"[ACPX-V2]   Failed to remove placeholder page {page_name}: {remove_error}")
                
                if empty_pages:
                    issues.append(f"Removed {len(empty_pages)} placeholder pages: {empty_pages}")
                    status = "partial_success"
                    logger.warning(f"[ACPX-V2]   ⚠️ Removed {len(empty_pages)} placeholder pages")
                else:
                    logger.info("[ACPX-V2]   ✓ All pages have substantial content")
                    
            except Exception as e:
                logger.warning(f"[ACPX-V2] ⚠️ Empty page check failed but continuing: {str(e)}")

            # =============================================
            # FINAL RESULT (3-state outcome)
            # =============================================
            
            # Determine final message based on status
            if status == "success":
                message = "ACPX changes applied successfully"
            else:
                message = f"ACPX changes applied with issues: {'; '.join(issues[:5])}"
            
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
            
            logger.info(f"[ACPX-V2] ✅ Final status: {status}")
            if issues:
                logger.info(f"[ACPX-V2]   Issues: {issues}")
            logger.info(f"[ACPX-V2]   Files: +{len(files_added)} ~{len(files_modified)} -{len(files_removed)}")
            
            return result

        except Exception as e:
            # =============================================
            # GLOBAL EXCEPTION HANDLER (ONLY case for rollback)
            # =============================================
            logger.error(f"[ACPX-V2] 🔴 FATAL ERROR: {type(e).__name__}: {str(e)}")
            traceback.print_exc()

            # Attempt to rollback
            try:
                self.snapshot_manager.rollback_and_cleanup()
                logger.info("[ACPX-V2] Rollback completed")
            except Exception as rollback_error:
                logger.warning(f"[ACPX-V2] Rollback also failed: {rollback_error}")

            return {
                "status": "failed",
                "success": False,
                "message": f"FATAL ERROR in apply_changes_via_acpx: {str(e)}",
                "issues": [str(e)],
                "files_added": 0,
                "files_modified": 0,
                "files_removed": 0,
                "rollback": True
            }
        finally:
            # Cleanup snapshot to prevent leaks
            try:
                logger.info(f"[ACPX-V2] Step 13: Cleanup snapshot...")
                self.snapshot_manager.cleanup_snapshot()
            except Exception as e:
                logger.warning(f"[ACPX-V2] Snapshot cleanup failed: {str(e)}")

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

        # logger.info("[Planner] Extracting required pages from prompt...")
        print("\n" + "="*60, flush=True)
        print("🔍 PAGE INFERENCE START", flush=True)
        print("="*60, flush=True)
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
                # logger.info(f"[Planner] Groq inferred pages: {inferred_pages}")
                print(f"✅ PLANNER-GROQ-SUCCESS: Using {len(inferred_pages)} pages: {inferred_pages}", flush=True)
            else:
                print(f"⚠️  PLANNER-GROQ-INSUFFICIENT: Got {len(inferred_pages) if inferred_pages else 0} pages, need >= 3", flush=True)
        except Exception as e:
            logger.warning(f"[Planner] Groq inference failed: {e}")
            print(f"❌ PLANNER-GROQ-ERROR: {type(e).__name__}: {str(e)}", flush=True)

        # Step 2: Fallback to default pages
        if len(required_pages) < 3:
            required_pages = ["Dashboard", "Settings", "Overview"]
            # logger.info(f"[Planner] Using default pages: {required_pages}")
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
        # logger.info(f"[Phase9] Allowed pages: {required_pages}")
        # print(f"🔴 PHASE9-ALLOWED: Whitelist set to: {sorted(self.allowed_pages)}")

        # Planner logging
        # logger.info(f"[Planner] Description: {goal_description}")
        # logger.info(f"[Planner] Detected pages: {required_pages}")

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

🚨🚨🚨 CRITICAL: NO NEW PACKAGES - USE EXISTING COMPONENTS ONLY 🚨🚨🚨

This is an INITIAL BUILD with pre-installed dependencies.

⚠️ STRICT RULES:
1. DO NOT install any new npm packages
2. DO NOT modify package.json
3. DO NOT run npm install or npm add
4. USE ONLY existing UI components from src/components/ui/
5. BUILD all custom UI using Tailwind CSS + Lucide icons
6. If a component doesn't exist, CREATE it in src/components/ (NOT in src/components/ui/)

Available UI components (check src/components/ui/ for full list):
- Button, Card, Input, Label, Select, Textarea
- Dialog, Sheet, Dropdown, Popover
- Table, Badge, Avatar, Separator
- And more...

Use Lucide icons: import {{ IconName }} from 'lucide-react'

IMPORTANT:
Do not analyze the entire project deeply.
Focus only on required pages and layout files.

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

🎨 PREMIUM UI MODE

Enhance UI using:
- glassmorphism (backdrop blur + transparency)
- soft shadows and depth
- subtle hover animations
- gradient accents (blue → purple)
- modern SaaS styling (Stripe / Linear inspired)

Apply:
- backdrop-blur-xl + semi-transparent backgrounds
- hover:scale-[1.02] + hover:shadow-xl on cards
- gradient headers and icon accents
- smooth transitions (transition-all duration-300)

Avoid:
- flat UI
- plain white sections without depth
- static non-interactive components

YOUR TASK

Transform the existing template into a production-ready application based on the project description above.

� FAST EXECUTION MODE (UI-FIRST SCAFFOLD)

This is an INITIAL BUILD phase.

PRIORITY:
- Focus on HIGH-QUALITY UI
- Use STATIC / MOCK DATA
- Build visually COMPLETE pages quickly

DO NOT:
- implement complex logic
- implement real backend integrations
- implement full feature engines (editor, canvas, drag-drop)

FOR COMPLEX FEATURES:
- block editor → UI layout only
- canvas → static visual layout
- charts → static UI with sample data

TIME OPTIMIZATION RULES:
- Do NOT over-engineer
- Do NOT spend time on edge cases
- Do NOT try to perfect every detail
- Limit each page to 2–3 main UI sections
- Avoid deeply nested or overly complex layouts

SUCCESS CRITERIA:
- Pages must LOOK complete (not logically complete)
- No blank or placeholder pages
- UI should feel production-ready visually

This is NOT the final implementation — focus on SPEED + UI QUALITY.

�🚨🚨🚨 CRITICAL ROUTING FIX - MUST DO FIRST 🚨🚨🚨

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

🚨🚨🚨 CRITICAL: NO EMPTY/PLACEHOLDER PAGES - BUILD MUST SUCCEED 🚨🚨🚨

This is the INITIAL UI BUILD phase. Focus on visual completeness. Further improvements can be done later.

EVERY PAGE MUST BE FULLY IMPLEMENTED OR THE BUILD WILL FAIL:

1. MINIMUM CONTENT REQUIREMENTS (MANDATORY):
   - Each page must contain meaningful UI with multiple sections (no empty or placeholder content)
   - Each page MUST include ACTUAL content (not stubs/placeholders)
   - Each page MUST have REAL functionality (working components, data displays)
   - Each page MUST compile without TypeScript errors

2. FORBIDDEN PATTERNS (DO NOT CREATE - WILL CAUSE BUILD FAILURE):
   ❌ return <div></div>
   ❌ return null
   ❌ return <div>Dashboard</div>
   ❌ return <div className="p-4">Page content coming soon</div>
   ❌ // TODO: Add content
   ❌ // Page content will be generated by AI
   ❌ Any file under 800 characters
   ❌ Any placeholder text whatsoever

3. REQUIRED CONTENT FOR EACH PAGE (ALL REQUIRED):
   ✅ Proper imports (React, hooks, icons from lucide-react)
   ✅ State management (useState, useEffect as needed)
   ✅ Real UI components (cards, tables, forms, charts)
   ✅ Styled with Tailwind CSS (responsive layouts with md: breakpoints)
   ✅ Functional interactions (clicks, forms, modals)
   ✅ Loading states and error handling
   ✅ Mobile-responsive design
   ✅ TypeScript types properly defined

4. EXAMPLE FULL PAGE IMPLEMENTATION (Dashboard - COPY THIS PATTERN):
```tsx
import {{ useState, useEffect }} from 'react';
import {{ LayoutDashboard, Users, TrendingUp, Activity, DollarSign }} from 'lucide-react';

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
  const [stats, setStats] = useState({{
    users: 0,
    revenue: 0,
    growth: 0,
    activity: 0
  }});

  useEffect(() => {{
    // Simulate data fetch
    setTimeout(() => {{
      setStats({{ users: 1234, revenue: 50000, growth: 12.5, activity: 89 }});
      setLoading(false);
    }}, 500);
  }}, []);

  if (loading) {{
    return <div className="p-6">Loading...</div>;
  }}

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Dashboard</h1>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard title="Total Users" value={{stats.users.toLocaleString()}} icon={{<Users className="w-6 h-6 text-blue-500" />}} trend="+12%" />
        <StatCard title="Revenue" value=${{stats.revenue.toLocaleString()}} icon={{<DollarSign className="w-6 h-6 text-green-500" />}} trend="+8%" />
        <StatCard title="Growth" value={{`${{stats.growth}}%`}} icon={{<TrendingUp className="w-6 h-6 text-purple-500" />}} />
        <StatCard title="Activity" value={{stats.activity}} icon={{<Activity className="w-6 h-6 text-orange-500" />}} />
      </div>
      
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white p-6 rounded-lg shadow-sm border">
          <h2 className="font-semibold mb-4">Recent Activity</h2>
          <div className="space-y-3">
            {{[1, 2, 3].map(i => (
              <div key={{i}} className="flex items-center gap-3 p-3 bg-gray-50 rounded">
                <div className="w-2 h-2 bg-blue-500 rounded-full"></div>
                <span className="text-sm">Activity item {{{{i}}}}</span>
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

5. MANDATORY FINAL VERIFICATION (YOU MUST DO THIS):
   
   STEP 1: Run `npm run build` in the frontend directory
   STEP 2: Check that build succeeds with NO errors
   STEP 3: If build fails, FIX ALL ERRORS before marking complete
   STEP 4: Verify each page file is 800+ characters
   STEP 5: Verify NO files contain "placeholder", "TODO", or "coming soon"

🚨 IF npm run build FAILS, YOUR TASK IS INCOMPLETE - FIX ALL ERRORS 🚨
   NOTE:
   Focus on generating clean, correct UI code.

CHECKLIST (complete in order - ALL STEPS REQUIRED)
1. [ ] Fix routing — remove Welcome at "/", single {default_page} route at "/" inside Layout wrapper
2. [ ] Create src/layout/Navbar.tsx — mobile hamburger menu, NavLink to all required pages
3. [ ] Integrate Navbar into Layout.tsx header
4. [ ] Create each required page FULLY IMPLEMENTED (800+ chars, real content):
{required_pages_str}
5. [ ] Verify no unauthorized pages exist in src/pages/
6. [ ] Verify each page is 800+ characters (NO placeholders)
7. [ ] Run npm run build and VERIFY IT SUCCEEDS
8. [ ] Fix any TypeScript or build errors
9. [ ] RE-RUN npm run build to confirm success
10. [ ] SERVE dist folder: `npx serve dist -l 3000` (or available port)
11. [ ] VERIFY with Chrome DevTools MCP:
    - Open browser page at http://localhost:3000
    - Take snapshot to confirm page loads correctly
    - Check for console errors
    - Verify all routes work (click through each page)
    - Confirm no blank/white screens
    - Screenshot final result for confirmation

SCOPE LIMITATION (CRITICAL - Reduces AI scanning time)

ONLY modify files in these directories:
- src/pages/
- src/components/ (create custom components here, NOT in src/components/ui/)
- src/layout/
- src/features/

DO NOT scan:
- node_modules
- dist
- build
- .git

🚨 DO NOT MODIFY (STRICT):
- package.json (NO new packages)
- src/components/ui/ (UI primitives - use but don't modify)
- vite.config.*, tsconfig.json
- node_modules
- backend files, .env files
- Do NOT change project architecture
- Do NOT run npm install/add/update

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

🚨 POST-BUILD: UPDATE AI INDEX (MANDATORY) 🚨

After npm run build succeeds, you MUST update the AI index files:

1. Update agent/ai_index/symbols.json:
   - Add new components/pages with file path and line numbers
   - Update line numbers for modified files

2. Update agent/ai_index/files.json:
   - Add new file entries with line count and purpose
   - Update routes array in App.tsx entry

3. Update agent/ai_index/dependencies.json:
   - Add new import relationships

4. Update agent/ai_index/summaries.json:
   - Add brief description for new files

Quick update example for symbols.json:
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

AI index keeps the codebase navigable for future AI edits.
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

    def _enforce_page_guardrails(self) -> int:
        """
        Enforce page guardrails by removing unauthorized pages.

        Scans src/pages/ and removes any pages not in the allowed_pages whitelist.

        Returns:
            Number of unauthorized pages removed
        """
        pages_dir = self.frontend_src_path / "pages"

        if not pages_dir.exists():
            # logger.warning(f"[Guardrail] Pages directory not found: {pages_dir}")
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
                # logger.warning(f"[Guardrail] Removing page with leading conjunction: {page_name}")
                try:
                    page_file.unlink()
                    unauthorized_removed += 1
                except Exception as e:
                    logger.error(f"[Guardrail] Failed to remove {page_name}: {e}")
                    # Do not increment — file was NOT removed
                continue

            # Check if page is in allowed whitelist
            if page_name not in self.allowed_pages:
                # logger.warning(f"[Guardrail] Removing unauthorized page: {page_name}")
                try:
                    page_file.unlink()
                    unauthorized_removed += 1
                except Exception as e:
                    logger.error(f"[Guardrail] Failed to remove {page_name}: {e}")
                    # Do not increment — file was NOT removed

        if unauthorized_removed > 0:
            # logger.info(f"[Guardrail] Removed {unauthorized_removed} unauthorized page(s)")
            # logger.info(f"[Guardrail] Remaining allowed pages: {sorted(self.allowed_pages)}")
            pass
        else:
            # logger.info(f"[Guardrail] ✓ All pages are authorized")
            pass

        # logger.info(f"[Phase9] Final validated pages: {sorted(self.allowed_pages)}")

        return unauthorized_removed

    def _kill_process_tree(self, pid: int):
        """
        Kill a process and all its children aggressively.
        Handles npx child processes that may be in different process groups.
        
        Args:
            pid: Process ID to kill (will also kill all children)
        """
        import signal
        
        try:
            # Step 1: Get all descendant PIDs (recursive, not just direct children)
            all_pids = []
            try:
                # Use pgrep -P recursively to find all descendants
                result = subprocess.run(
                    ["pgrep", "-P", str(pid)],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                if result.returncode == 0:
                    direct_children = [int(p.strip()) for p in result.stdout.strip().split('\n') if p.strip()]
                    all_pids.extend(direct_children)
                    
                    # Recursively find children of children
                    for child_pid in direct_children:
                        try:
                            child_result = subprocess.run(
                                ["pgrep", "-P", str(child_pid)],
                                capture_output=True,
                                text=True,
                                timeout=1
                            )
                            if child_result.returncode == 0:
                                grandchildren = [int(p.strip()) for p in child_result.stdout.strip().split('\n') if p.strip()]
                                all_pids.extend(grandchildren)
                        except Exception:
                            pass
                    
                    logger.info(f"[ACPX-V2] Found {len(all_pids)} descendant processes to kill")
            except Exception as e:
                logger.warning(f"[ACPX-V2] Failed to get descendant PIDs: {e}")
            
            # Step 2: Kill process group first (most reliable for spawned processes)
            try:
                os.killpg(pid, signal.SIGKILL)
                logger.info(f"[ACPX-V2] Killed process group {pid}")
            except (ProcessLookupError, OSError, AttributeError) as e:
                logger.debug(f"[ACPX-V2] Process group kill skipped: {e}")
            
            # Step 3: Kill all descendants (SIGKILL)
            for child_pid in all_pids:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                    logger.info(f"[ACPX-V2] Killed descendant process {child_pid}")
                except (ProcessLookupError, OSError) as e:
                    logger.debug(f"[ACPX-V2] Descendant process {child_pid} already dead: {e}")
            
            # Step 4: Kill main process (SIGKILL)
            try:
                os.kill(pid, signal.SIGKILL)
                logger.info(f"[ACPX-V2] Killed main process {pid}")
            except (ProcessLookupError, OSError) as e:
                logger.debug(f"[ACPX-V2] Main process {pid} already dead: {e}")
            
            # Step 5: Use pkill as fallback for claude-agent-acp processes
            try:
                result = subprocess.run(
                    ["pkill", "-9", "-f", "claude-agent-acp"],
                    capture_output=True,
                    text=True,
                    timeout=3
                )
                if result.returncode == 0:
                    logger.info(f"[ACPX-V2] Killed orphan claude-agent-acp processes via pkill")
            except Exception as e:
                logger.debug(f"[ACPX-V2] pkill fallback skipped: {e}")
            
            # Step 6: Verify all processes are dead
            time.sleep(0.5)
            check_pids = [pid] + all_pids
            for check_pid in check_pids:
                try:
                    os.kill(check_pid, 0)  # Check if process exists
                    logger.error(f"[ACPX-V2] ⚠️  Process {check_pid} STILL ALIVE after SIGKILL!")
                except (ProcessLookupError, OSError):
                    logger.debug(f"[ACPX-V2] ✓ Process {check_pid} confirmed dead")
            
        except Exception as e:
            logger.error(f"[ACPX-V2] Failed to kill process tree: {e}")



