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
from workflow_prompt_meta import build_workflow_meta_block

# Claude Code Agent - direct Claude CLI wrapper (replaces ACPX)
try:
    from claude_code_agent import ClaudeCodeAgent
    CLAUDE_AGENT_AVAILABLE = True
except ImportError:
    CLAUDE_AGENT_AVAILABLE = False

# Configure logging - only set level for THIS module's logger
# DO NOT modify root logger as it affects the entire process (including openclaw_wrapper)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # Allow INFO for this module's logs


# =============================================================================
# CONSTANTS
# =============================================================================

# Forbidden paths (backend source must never be exposed to user code)
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
BUILD_TIMEOUT = 3000  # 30 minutes

# Claude Code Agent settings
CLAUDE_TIMEOUT = int(os.getenv("CLAUDE_TIMEOUT", "3000"))  # 21 minutes default

PROMPT_API_SOURCE_GATE = """\
## API SOURCE AND ACCESSIBILITY GATE - MANDATORY

Before adding, changing, or using ANY external API, image, video, iframe, script, CDN asset, or third-party URL, classify it first.

### 1. Public API / Public Asset

Use this only when the resource is intentionally public and does not require private credentials.

Examples:
- Public JSON APIs from `llm/categories/`
- Public image URLs
- Public video URLs
- Public documentation/data endpoints

Rules:
- Prefer the project's `llm/categories/` catalog when available.
- Never invent API endpoints or asset URLs.
- Use the exact documented `direct_url` or official public URL.
- Before writing any external image, video, or asset URL into code, verify it is reachable in the current session.

Required check:

```bash
curl -I -L --max-time 10 "<FULL_URL>"
```

Accept only:
- HTTP 200
- HTTP 301/302 that resolves to HTTP 200

Reject:
- 403
- 404
- 5xx
- timeout
- DNS failure
- blocked or hotlink-protected response

If the URL fails:
- Do NOT use it.
- Try up to 2 better alternatives from the same approved source.
- Verify each with `curl -I -L`.
- If none work, ask the user before choosing another source.

Never commit an external media URL that was not verified.

### 2. Private API / Secret-Based API

Use this only when the API requires credentials, tokens, API keys, user-specific auth, paid access, webhooks, or private infrastructure.

Rules:
- Never place private API keys, tokens, secrets, or webhook URLs in frontend code.
- Never hardcode secrets.
- Store secrets only in backend environment variables.
- Frontend must call the project backend, not the private third-party API directly.
- Backend/service layer is responsible for attaching secrets.
- If credentials are missing, ask the user for the integration details or env variable name.
- Do not fake private API responses unless the user explicitly asks for mock UI only.

### 3. Internal Project API

Use internal backend APIs when the app already owns the data or action.

Rules:
- Reuse existing backend endpoints and API helpers when present.
- Do not create a new public API integration if the backend already has the required data.
- Do not bypass the backend for authenticated or project-specific actions.

### Final Self-Check

Before editing any file that references an API or external media URL, answer internally:
- Is this public, private, or internal?
- If public media: did I verify it with `curl -I -L`?
- If private: are secrets kept out of frontend code?
- If internal: am I reusing existing backend/API helpers?
- Did I avoid invented URLs?

If any answer is uncertain, STOP and resolve it before writing code."""

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
            subprocess.run(
            ["chown", "-R", "dreampilot:dreampilot", str(self.backup_dir)],
            capture_output=True
        )
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
            subprocess.run(
        ["chown", "-R", "dreampilot:dreampilot", str(self.frontend_path)],
        capture_output=True
    )
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

    def __init__(self, frontend_src_path: str, project_name: str, max_new_files: int = 15, project_id: int = None):
        """
        Initialize ACP Frontend Editor v2.

        Args:
            frontend_src_path: Absolute path to frontend/src directory
            project_name: Name of the project for logging
            max_new_files: Maximum number of new files allowed per execution
            project_id: Optional database project ID for workflow metadata
        """
        self.frontend_src_path = Path(frontend_src_path).resolve()
        self.frontend_path = self.frontend_src_path.parent
        self.project_path = self.frontend_path.parent
        self.project_name = project_name
        self.project_id = project_id
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

        # Token usage from last query
        self._last_token_usage = None

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
        self._last_token_usage = None  # Reset token usage for new execution

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

            # Step 4: Write manifest only — do NOT create stub files on disk.
            # Claude Code's internal Write gate: if file exists on disk, it checks
            # tool history for a prior Read/Write. No Read history → silent drop.
            # When files DON'T exist → new file creation allowed → Write succeeds.
            # Stubs would trigger the exist+no-history rejection path.
            logger.info(f"[CLAUDE-AGENT] Step 4: Writing page manifest (no stub files)...")
            manifest_result = self.manifest_manager.write_manifest(required_pages)
            if not manifest_result:
                issues.append("Failed to write page manifest")
                logger.warning(f"[CLAUDE-AGENT] ⚠️ Manifest write failed, continuing...")

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

                # =============================================
                # FIX PERMISSIONS: Remove immutable flags from scaffold files
                # The Vite scaffold creates App.tsx/Layout.tsx with inherited
                # ACLs that prevent the wrapper's repair_route_wiring phase
                # from overwriting them via Bash heredoc.
                # =============================================
                try:
                    subprocess.run(
                        ["chattr", "-R", "-i", str(self.frontend_src_path)],
                        check=False, capture_output=True, timeout=10
                    )
                    subprocess.run(
                        ["chmod", "-R", "u+rw", str(self.frontend_src_path)],
                        check=False, capture_output=True, timeout=10
                    )
                    logger.info(f"[CLAUDE-AGENT] ✅ Permissions fixed on {self.frontend_src_path}")
                except Exception as perm_err:
                    logger.warning(f"[CLAUDE-AGENT] ⚠️ Permission fix failed (non-fatal): {perm_err}")

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
                # PARTIAL COMMIT: Timeout/error handling (NEVER rollback — always continue)
                # =============================================
                
                # Handle timeout (return code 124) or error (non-zero return code)
                # Policy: never rollback on timeout. The infrastructure pipeline
                # (wrapper-v2) continues the workflow via server-side state tracking.
                if return_code != 0:
                    created_files = list(self.frontend_src_path.glob("**/*.tsx"))
                    dist_index = self.frontend_path / "dist" / "index.html"
                    has_build = dist_index.exists()

                    if return_code == 124:
                        issues.append(f"Timeout exceeded ({CLAUDE_TIMEOUT}s)")
                        if has_build:
                            logger.warning(f"[CLAUDE-AGENT] ⚠️ Timeout ({CLAUDE_TIMEOUT}s) — build exists ({len(created_files)} .tsx files), continuing pipeline")
                            print(f"⚠️ CLAUDE-AGENT-TIMEOUT: Build exists, {len(created_files)} files — continuing pipeline (partial_success)", flush=True)
                            status = "partial_success"
                        else:
                            logger.error(f"[CLAUDE-AGENT] 🔴 Timeout ({CLAUDE_TIMEOUT}s) — NO build output, pipeline likely broken")
                            print(f"🔴 CLAUDE-AGENT-TIMEOUT: No build output! {len(created_files)} .tsx files exist but dist/index.html missing", flush=True)
                            issues.append("No build output (dist/index.html missing)")
                            status = "partial_success"
                    else:
                        if has_build:
                            issues.append(f"Claude Agent exited with code {return_code}")
                            logger.warning(f"[CLAUDE-AGENT] ⚠️ Non-zero exit ({return_code}) — build exists, continuing pipeline")
                            print(f"⚠️ CLAUDE-AGENT-ERROR: code {return_code}, build exists — continuing pipeline (partial_success)", flush=True)
                            status = "partial_success"
                        else:
                            logger.error(f"[CLAUDE-AGENT] 🔴 Non-zero exit ({return_code}) — NO build output")
                            print(f"🔴 CLAUDE-AGENT-ERROR: code {return_code}, no build output (dist/index.html missing)", flush=True)
                            issues.append(f"Claude Agent exited with code {return_code}, no build output")
                            status = "partial_success"

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
                "rollback": False,
                "token_usage": self._last_token_usage,
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
        explicit_pages = []
        pages_section = ""
        pages_match = re.search(r"(?im)^\s*pages\s*:\s*$", goal_description)
        if pages_match:
            pages_section = goal_description[pages_match.end():]
            next_section = re.search(r"(?m)^\s*[A-Z][A-Z0-9 /&()_-]{2,}\s*:\s*$", pages_section)
            if next_section:
                pages_section = pages_section[:next_section.start()]

        for match in re.finditer(
            r"(?im)^\s*(?:\d+[\.\)]\s*|[-*]\s+)([A-Za-z][A-Za-z0-9 &/+-]{1,50}?)\s+PAGE\b",
            pages_section,
        ):
            label = re.sub(r"[^A-Za-z0-9]+", " ", match.group(1)).strip()
            if label:
                explicit_pages.append("".join(part.capitalize() for part in label.split()) + "page")
        if len(set(explicit_pages)) >= 2:
            required_pages = list(dict.fromkeys(explicit_pages))
            print(f"PLANNER-EXPLICIT-PAGES: Using pages from prompt: {required_pages}", flush=True)

        # Step 1: Try Groq AI inference
        try:
            if required_pages:
                inferred_pages = []
            else:
                from groq_service import GroqService
                groq = GroqService()
                inferred_pages = await groq.infer_pages(goal_description)
                    
            if not required_pages and inferred_pages and len(inferred_pages) >= 3:
                required_pages = inferred_pages
                print(f"✅ PLANNER-GROQ-SUCCESS: Using {len(inferred_pages)} pages: {inferred_pages}", flush=True)
            elif not required_pages:
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
        Run Claude Code Agent to execute the prompt as a background task.

        Uses asyncio.create_task() with asyncio.shield() pattern from chat handler
        to ensure the query runs to completion even if caller disconnects.

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
        from datetime import datetime
        from acp_progress_mapper import ClaudeProgressMapper

        stdout_lines = []
        stderr_lines = []
        chunk_count = 0
        query_start_time = datetime.now()
        progress_mapper = ClaudeProgressMapper()

        def _check_ai_index_writing(text: str) -> bool:
            """Return True if Claude is writing AI index files (last workflow step)."""
            lowered = text.lower()
            if "ai index" in lowered or "ai_index" in lowered:
                return True
            return False
        
        def on_text(text: str) -> None:
            """Callback for streaming text output (persisted to DB)."""
            nonlocal chunk_count
            chunk_count += 1
            stdout_lines.append(text)
            
            # Verbose logging for PM2
            logger.info(f"[ACPX-V2] on_text chunk #{chunk_count}: {text[:100]}{'...' if len(text) > 100 else ''}")

            # Detect AI index write — log milestone for monitoring
            if _check_ai_index_writing(text):
                logger.info(f"[ACPX-V2] 🟢 AI INDEX DETECTED — Claude writing index files")
                print(f"🟢 AI-INDEX-DETECTED: Claude writing index files", flush=True)
            
            # Get friendly progress message from keyword mapper
            friendly = progress_mapper.get_friendly_message(text)
            if friendly:
                logger.info(f"[ACPX-V2] Progress mapped: {friendly}")
                print(f"🔧 {friendly}", flush=True)
            
            # Print meaningful text to stdout for PM2 logs (skip noise)
            cleaned = text.strip()
            if cleaned and cleaned not in ["null", "{}", "[]", "---"]:
                skip_patterns = [
                    cleaned.startswith('{'),
                    cleaned.startswith('['),
                    cleaned.startswith("```json"),
                    cleaned.startswith("```"),
                    cleaned == "**Input:**",
                    cleaned == "**Output:**",
                ]
                if not any(skip_patterns):
                    print(f"📄 {text}", flush=True)

        def on_progress(progress: str) -> None:
            """Callback for phase-based progress (timeout updates)."""
            elapsed = (datetime.now() - query_start_time).total_seconds()
            friendly = progress_mapper.get_phase_message(elapsed)
            logger.info(f"[ACPX-V2] Phase progress ({elapsed:.0f}s): {friendly}")
            print(f"⏱️ [{elapsed:.0f}s] {friendly}", flush=True)

        logger.info(f"[ACPX-V2] === CLAUDE CODE AGENT STARTING ===")
        logger.info(f"[ACPX-V2] Working directory: {self.frontend_src_path}")
        logger.info(f"[ACPX-V2] Prompt length: {len(prompt)} chars")
        logger.info(f"[ACPX-V2] Timeout: {CLAUDE_TIMEOUT}s")

        print("=" * 80, flush=True)
        print("🤖 CLAUDE CODE AGENT - STARTING", flush=True)
        print(f"   Working directory: {self.frontend_src_path}", flush=True)
        print(f"   Prompt length: {len(prompt)} chars", flush=True)
        print(f"   Timeout: {CLAUDE_TIMEOUT}s", flush=True)
        print("=" * 80, flush=True)

        # Run Claude directly — no background thread, no early return.
        # The wrapper prompt enforces: after AI index write, STOP.
        # No rebuild, no reinstall, no re-serve.
        try:
            # Phase 4: resolve user_id for container targeting (no-op in local mode).
            from claude_code_agent import resolve_user_id_for_project
            _user_id = resolve_user_id_for_project(self.project_id)
            # Capture chrome-devtools-mcp PIDs BEFORE the session so we only
            # reap the ones this session spawned (parallel builds are safe).
            from services.chrome_cleanup import cleanup_after_session, _get_chrome_devtools_pids
            _chrome_pids_before = _get_chrome_devtools_pids(_user_id)
            async with ClaudeCodeAgent(
                repo_path=str(self.frontend_src_path),
                on_text=on_text,
                on_progress=on_progress,
                user_id=_user_id,
            ) as agent:
                logger.info(f"[ACPX-V2] ClaudeCodeAgent created, calling query...")
                
                result = await agent.query(prompt, timeout=CLAUDE_TIMEOUT)

                self._last_token_usage = agent.last_token_usage
                if self._last_token_usage:
                    cost = self._last_token_usage.get('cost_usd') or 0
                    logger.info(f"[ACPX-V2] Token usage: input={self._last_token_usage.get('input_tokens')}, output={self._last_token_usage.get('output_tokens')}, cost=${cost:.4f}")

                    # Record to token_usage table
                    try:
                        from services.token_tracker import record_from_token_usage_json
                        from database_adapter import get_db
                        if self.project_id:
                            with get_db() as conn:
                                row = conn.execute(
                                    "SELECT user_id FROM projects WHERE id = %s",
                                    (self.project_id,),
                                ).fetchone()
                            _uid = row["user_id"] if row else None
                            if _uid:
                                record_from_token_usage_json(
                                    user_id=_uid,
                                    token_usage_json=self._last_token_usage,
                                    usage_type="project_create",
                                    project_id=self.project_id,
                                    description=f"Website create: {self.project_name}",
                                )
                    except Exception as track_err:
                        logger.warning(f"[ACPX-V2] Token tracking failed: {track_err}")

                return_code = 0 if result is not None else 1
                elapsed = (datetime.now() - query_start_time).total_seconds()

                logger.info(f"[ACPX-V2] === QUERY COMPLETED ===")
                logger.info(f"[ACPX-V2] Return code: {return_code}")
                logger.info(f"[ACPX-V2] Total chunks: {chunk_count}")
                logger.info(f"[ACPX-V2] Elapsed time: {elapsed:.1f}s")

                print("=" * 80, flush=True)
                print("✅ CLAUDE CODE AGENT - COMPLETED", flush=True)
                print(f"   Return code: {return_code}", flush=True)
                print(f"   Total chunks: {chunk_count}", flush=True)
                print(f"   Elapsed time: {elapsed:.1f}s", flush=True)
                print("=" * 80, flush=True)

                # Reap chrome-devtools-mcp processes + leftover browser tabs that
                # Claude's browser verification opened. Without this, website
                # CREATE sessions leak ~130MB renderer processes per unclosed tab.
                try:
                    cleanup_after_session(_user_id, _chrome_pids_before)
                except Exception as chrome_err:
                    logger.warning(f"[ACPX-V2] Chrome cleanup failed (non-fatal): {chrome_err}")

                return (return_code, '\n'.join(stdout_lines), '\n'.join(stderr_lines))

        except asyncio.TimeoutError:
            elapsed = (datetime.now() - query_start_time).total_seconds()
            logger.error(f"[ACPX-V2] === TIMEOUT after {CLAUDE_TIMEOUT}s ===")
            print(f"🔴 CLAUDE-AGENT-TIMEOUT: Exceeded {CLAUDE_TIMEOUT}s ({elapsed:.1f}s elapsed, {chunk_count} chunks)", flush=True)
            # Still reap chrome on timeout — a hung session leaves the most tabs.
            try:
                cleanup_after_session(_user_id, _chrome_pids_before)
            except Exception as chrome_err:
                logger.warning(f"[ACPX-V2] Chrome cleanup on timeout failed (non-fatal): {chrome_err}")
            return (124, '\n'.join(stdout_lines), f"Timeout after {CLAUDE_TIMEOUT}s")

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

        # Strip trailing "page" suffix for clean route/display names
        # e.g. "Historypage" → "History" for routes and nav labels
        def _clean_page_name(name: str) -> str:
            return re.sub(r"page$", "", name, flags=re.IGNORECASE) or name

        clean_page_names = [_clean_page_name(p) for p in required_pages_list]

        required_page_labels = []
        for name in clean_page_names:
            stem = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
            label = re.sub(r"[^A-Za-z0-9]+", " ", stem).strip()
            if label:
                required_page_labels.append(label)
        required_page_labels = list(dict.fromkeys(required_page_labels))

        # File paths use original names (must match files on disk)
        required_pages_str = "\n".join([f"- src/pages/{page}.tsx" for page in required_pages_list])

        # Phase 4: Build page specs section (NEW)
        page_specs_section = self._build_page_specs_section(required_pages)

        # Determine which page should be the default route (clean name for JSX component)
        default_page = clean_page_names[0] if clean_page_names else "Dashboard"

        # Translate host paths to container paths for Claude's metadata.
        # Claude sees /workspace/... (its cwd), not /workspaces/user_24/... (host path).
        from services.container_storage import to_container_path
        meta_block = build_workflow_meta_block(
            project_type_id=1,
            project_type="website",
            operation="create",
            workflow="website_create",
            project_name=self.project_name,
            project_id=self.project_id,
            project_path=to_container_path(str(self.project_path)),
            frontend_path=to_container_path(str(self.frontend_path)),
            prompt_kind="website_create",
            pages=required_pages_list,
        )

        return f"""{meta_block}
You are editing a React + Vite + TypeScript application.

Project Name: {self.project_name}
Project Description: {goal_description}

Do not assume this is a SaaS/admin/dashboard app unless the user explicitly requested it.
Follow the product category, audience, navigation pattern, theme, and visual style in the Project Description.
For consumer, social, lifestyle, marketplace, game, portfolio, or mobile-app prompts, build the actual
domain experience instead of generic dashboard/table sections.
Build a complete desktop web experience by default. Mobile responsiveness is required, but do not output
only a narrow mobile mockup centered on an empty desktop canvas unless the user explicitly requested
mobile-only output.

---

## ⛔ NEVER KILL GLOBAL PROCESSES (CRITICAL — read before any `pkill`/`kill`)

The build toolchain (`vite`, `esbuild`, `npm`, `node`) and the chrome-devtools
MCP are ALL `node` processes. A single `pkill node` or `pkill -f node` will
SIGKILL your own `npm run build` mid-flight, leaving a stale/empty `dist/`.
Your next verification then serves the stale dist, the browser shows a 404,
you panic, you `pkill node` again — a death-loop that burns minutes of tokens
and never converges. This has happened. Do not repeat it.

**BANNED commands (NEVER run any of these):**
- `pkill node` / `pkill -f node` / `pkill -9 node`
- `pkill npm` / `pkill -f npm`
- `pkill vite` / `pkill -f vite`
- `pkill esbuild` / `pkill -f esbuild`
- `pkill serve` (bare — too broad)
- `killall node`

**Killing processes is ALWAYS by PORT, never by process name.** To stop the
preview server, free only the port it bound:
```bash
# Kill whatever listens on 3004 (the serve port) — nothing else
fuser -k 3004/tcp 2>/dev/null || kill $(lsof -t -i:3004) 2>/dev/null
```
If `fuser`/`lsof` are missing, leave the serve running — it is harmless and
gets reaped at session end. **Never escalate to pkill.**

**Build discipline (avoids the 404 death-loop):**
1. Build: `npm run build` — wait for the literal `✓ built` line before doing
   anything else. If you don't see it, the build is still running or failed;
   do NOT serve.
2. Serve: `npx serve -s dist -l 3004` in the background, then `sleep 3` before
   any curl/browser check — serve needs a moment to bind. Verifying before the
   bind shows a connection error that looks identical to a build failure.
3. Verify the build you just ran, not a previous one. If you killed/restarted
   serve, `curl` once to confirm 200 + `<div id="root">` BEFORE opening the
   browser.

**URL discipline (CRITICAL — the #1 cause of false-404 death-loops):**
The chrome-devtools MCP browser runs in a **SEPARATE container** from your
shell. `localhost:3004` in the browser does NOT reach your `npx serve` — it
hits an empty server that returns serve's own 404 page
(`<span>404</span><p>The requested path could not be found</p>`). This 404
has **no `<title>`** and a ~98-byte body — that signature is **serve's
fallback, NOT your React app**. If you see it, you used the wrong URL; the
build is fine. Do NOT rebuild.

- In the browser, ALWAYS use `$CHROME_VERIFY_URL:3004/` (e.g.
  `http://172.18.0.2:3004/`). NEVER hand-type `localhost:3004` or
  `127.0.0.1:3004`.
- In your shell (curl), `localhost:3004` IS correct (the shell shares the
  container with serve). So `curl http://localhost:3004/` → 200, but
  `new_page(url: "http://localhost:3004/")` → serve 404. This asymmetry is
  expected; resolve it by using `$CHROME_VERIFY_URL` for the browser only.

---

## EXECUTION ORDER — FOLLOW THIS EXACTLY

1. Create each required non-Welcome page (fully implemented, 800+ chars)
2. Fix and validate routing before build (remove Welcome route, set `{default_page}` at `"/"`)
3. Create domain-appropriate navigation in `src/layout/Navbar.tsx`
4. Integrate navigation into `Layout.tsx`
5. Run `npm run build` only after router validation passes
6. Serve dist: `npx serve -s dist -l 3004` in the background, then `sleep 3`.
   (serve binds to 0.0.0.0 by default, so it's reachable via the container's
   bridge IP — which is what the browser must use.)
7. **BROWSER VERIFICATION (PRIMARY — runs first).** Use `$CHROME_VERIFY_URL`
   (NOT localhost). Run the visibility check from the POST-BUILD VERIFICATION
   section below:
   - `new_page(url: "$CHROME_VERIFY_URL:3004/")`
   - `evaluate_script` → returns `{{ok, mainW, navW, links, headings}}`
   - `close_page`
   If `ok === true` → **verification passed.** Skip curl entirely. Kill the
   serve process and proceed to update AI index files.
8. **IF BROWSER FAILED — ONE FIX, THEN CURL FALLBACK.** Only enter this step
   if step 7 returned `ok === false` (or the browser tools errored).
   **FIRST: diagnose the 404 before touching anything.** Inspect the page body:
   - If bodyHTML contains `<span>404</span>` / `<p>The requested path...` AND
     `title` is empty → that is **serve's own fallback page**, NOT your app. It
     means the browser used `localhost` (wrong) instead of `$CHROME_VERIFY_URL`.
     The build is FINE. Fix: `new_page(url: "$CHROME_VERIFY_URL:3004/")` and
     re-run the visibility check. Do NOT rebuild. Do NOT pkill anything.
   - Otherwise (real JS error, headings:0 from a runtime crash): do exactly
     ONE debug-and-fix cycle:
     a. Read the error: if the browser reported `headings: 0` or `mainW: 0`, run
        `get_console_message(types: ["error"])` to capture the JS runtime error.
     b. Fix the reported error in source (e.g. undefined import, bad hook, route
        mismatch). Make ONE fix — do not iterate.
     c. Rebuild (`npm run build`) and re-serve.
     d. Verify the rebuild with curl (run via Bash):
        ```
        curl -s http://localhost:3004/ | grep -E '<title>|<div id="root">|<script'
        ```
        The page must have a `<title>` (not "DreamPilot"), `<div id="root">`, and
        at least one `<script>`. If curl returns these, **mark verified.** Do NOT
        loop back to the browser. Do NOT attempt a second fix.

**Hard rules:**
- You get AT MOST ONE fix attempt in step 8. If curl still fails after the one
  rebuild, report "build succeeded but verification failed — needs manual check"
  and stop. Do not loop.
- If the browser passed in step 7, do not run curl. Do not run a second browser
  check. Verification is done.
- `$CHROME_VERIFY_URL` (e.g. `http://172.18.0.2`) is the container's bridge IP
  and IS reachable from host Chrome. NEVER use `http://localhost:3004` in the
  browser — localhost inside the container is NOT reachable from host Chrome.
9. Free the serve port ONLY (never `pkill` by name — see the ⛔ NEVER block):
   `fuser -k 3004/tcp 2>/dev/null || kill $(lsof -t -i:3004) 2>/dev/null`
10. Update AI index files (symbols, files, dependencies, summaries)

Wrapper compatibility: if required page files already exist as one-line scaffolds, overwrite all non-Welcome required page files with complete implementations first. Do not edit `src/pages/Welcome.tsx`.


---

## CONSTRAINTS

**Never do:**
- Run any commands after AI index files are updated (Step 8 = hard stop)
- Install new npm packages or modify `package.json`
- Run `npm install`, `npm add`, or `npm update`
- Modify files in `src/components/ui/` (use them, don't change them)
- Modify `vite.config.*`, `tsconfig.json`, or any backend/env files
- Create pages not in the required list
- Leave any page as a stub, placeholder, or under 800 characters
- Change project architecture
- Create alternate layout paths such as `src/app/layouts/`, `src/app/layout/`, `src/layouts/`, or `AppLayout.tsx`

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

## STEP 1 — FIX AND VALIDATE ROUTING

Read `src/App.tsx`. Delete ALL routes at `path="/"`. Add exactly one. Do this BEFORE running `npm run build`.

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
- `Layout` must come from `src/layout/Layout.tsx`; do not create or use alternate layout paths
- If no Layout wrapper exists, add it
- Layout MUST use `<Outlet />`, not a `children` prop
- Pages render at `<Outlet />`, not via children prop
- Layout uses flex for full-screen layout with overflow handling
- Do not leave Welcome at `"/"`
- Do not route pages directly under `<Routes>` without the Layout wrapper

Router validation MUST pass before build:
- `/` renders `{default_page}`, not `Welcome`
- exactly one root route at `"/"`
- all generated pages are imported and routed
- all routes are wrapped in the active `Layout`
- `Layout.tsx` renders `<Outlet />`
- desktop navigation visibly exposes all required page labels

Do not run build, serve, or browser verification until this router check is complete. Wrong routing = the browser renders the starter page even when build succeeds.

---

## POST-BUILD VERIFICATION (browser-first — see EXECUTION ORDER steps 7-8)

The EXECUTION ORDER above defines the flow: browser check first; if it fails,
ONE fix attempt then curl as fallback. This section gives the exact tool bodies.

### PRIMARY: Browser visibility check (step 7)

```
Step 1: mcp__chrome-devtools__new_page(url: "$CHROME_VERIFY_URL:3004/")
         — Do NOT use localhost:3004 in the browser. Use $CHROME_VERIFY_URL:3004.

Step 2: mcp__chrome-devtools__evaluate_script — copy this function verbatim.
  The 1.5s sleep bakes in hydration time; do NOT remove it or you'll read an
  empty DOM and false-fail. Return one `ok` boolean plus diagnostic widths.
  NOTE on nav: layouts are allowed to use <nav>, <aside> (sidebar), <header>,
  or any element containing links. The check accepts any of these — do NOT
  require a literal <nav> element.
  async () => {{
    await new Promise(r => setTimeout(r, 1500));
    const m = document.querySelector('main')?.getBoundingClientRect();
    const navEl = document.querySelector('nav') || document.querySelector('aside') || document.querySelector('header');
    const n = navEl?.getBoundingClientRect();
    const visibleLinks = Array.from(document.querySelectorAll('a, button')).filter(a => {{
      const r = a.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    }}).length;
    return JSON.stringify({{
      ok: !!(m && m.width > 0 && ((n?.width ?? 0) > 0 || visibleLinks > 0) && document.querySelectorAll('h1,h2,h3').length > 0),
      mainW: m?.width || 0,
      navW: n?.width || 0,
      links: visibleLinks,
      headings: document.querySelectorAll('h1,h2,h3').length
    }});
  }}

Step 3: mcp__chrome-devtools__close_page
```

If `ok === true` → **verification passed.** Skip curl, go to AI index update.
If `ok === false` → the page is blank or broken. Proceed to step 8 in EXECUTION
ORDER: read the JS error with `get_console_message`, make ONE fix, rebuild, then
verify with curl.

### FALLBACK: curl check (step 8d — only after a failed browser check + one fix)

```bash
HTML=$(curl -s http://localhost:3004/)
echo "$HTML" | grep -qE '<title>.*</title>' && echo "TITLE: OK" || echo "TITLE: MISSING"
echo "$HTML" | grep -q 'id="root"' && echo "ROOT DIV: OK" || echo "ROOT DIV: MISSING"
echo "$HTML" | grep -qE '<script.*src=.*\.js' && echo "JS BUNDLE: OK" || echo "JS BUNDLE: MISSING"
echo "$HTML" | grep -qi "DreamPilot Generated\|Start building" && echo "WARNING: STARTER TEMPLATE" || echo "NOT STARTER: OK"
```

If all four pass → **mark verified.** Do not loop back to browser. Do not make
a second fix attempt. Move to AI index update.

---

## STEP 2 — NAVBAR

Create `src/layout/Navbar.tsx` with these requirements:
- Navigation is mandatory. The finished website must have a visible desktop menu/header/sidebar on the first viewport.
- Use the navigation pattern requested by the Project Description.
- If the prompt asks for mobile sticky bottom navigation, implement sticky bottom tabs on mobile.
- If the prompt asks for a desktop sidebar/floating nav, implement that on desktop.
- Otherwise, use a polished responsive top navigation with visible text links on desktop.
- Navigation MUST expose links/tabs to all required pages: {', '.join(clean_page_names)}
- Desktop navigation MUST NOT be hidden behind a hamburger/menu icon at `md` and larger breakpoints.
- Navigation labels should be human-readable page names, for example `Discover` not `Discoverpage`.
- Use `NavLink` from `react-router-dom` for active link highlighting
- Touch-friendly tap targets (min 44px height)
- Smooth open/close transitions
- Import Navbar in `Layout.tsx` and place it in the header section
- `src/layout/Layout.tsx` MUST render `<Navbar />` and `<main><Outlet /></main>`
- `src/App.tsx` MUST import `Layout` from `src/layout/Layout.tsx` and wrap all generated routes with it
- For consumer/social/mobile-app prompts, avoid admin sidebars, table-heavy layouts, and generic SaaS dashboard chrome.

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
- Desktop web composition: use the available width intentionally, with visible navigation and primary actions above the fold
- Do not clip the primary card/content at the bottom of the first viewport
- Do not hide core actions below a large blank area on desktop
- TypeScript types properly defined
- 800+ characters — no stubs, no TODOs, no "coming soon", no placeholders

**Accessibility — enforced during creation (not audited after):**
- Use semantic `<button>` for all actions — never `<div onClick>`, `<span onClick>`, or `<a onClick>`:
  ```tsx
  // ❌ BAD: <div onClick={{handleClick}}>Submit</div>
  // ✅ GOOD: <button onClick={{handleClick}}>Submit</button>
  ```
- `<a>` for navigation only, `<button>` for all actions (submit, toggle, modal open, etc.)
- Icon/image buttons MUST have `aria-label`:
  ```tsx
  // ❌ BAD: <button><CloseIcon /></button>
  // ✅ GOOD: <button aria-label="Close modal"><CloseIcon /></button>
  ```
- All inputs MUST have `aria-label` (even with placeholder):
  ```tsx
  // ❌ BAD: <input type="text" placeholder="Search..." />
  // ✅ GOOD: <input type="text" aria-label="Search bots" placeholder="Search..." />
  ```
- Modals MUST have `role="dialog"` + `aria-label`
- Decorative SVGs MUST have `aria-hidden="true"`
- Dynamic content MUST have `aria-live`

**Forbidden patterns — will cause build failure:**
```
return <div></div>
return null
return <div>Dashboard</div>
return <div className="p-4">Page content coming soon</div>
// TODO: Add content
// Page content will be generated by AI
```

**Page pattern requirements:**
- Import React hooks, Lucide icons, and any UI components from `src/components/ui/`
- Use `useState` / `useEffect` for state management
- Tailwind CSS with responsive `md:` / `lg:` breakpoints
- Loading states and error handling
- 800+ characters of real content — no stubs, no TODOs, no placeholders

---

## STEP 4 — PAGE SPECIFICATIONS

{page_specs_section}

---

{PROMPT_API_SOURCE_GATE}

---

## STEP 5 — UI/UX QUALITY STANDARDS

This is an initial UI build — focus on SPEED + visual completeness. Static/mock data is fine.

Use ui-ux-pro-max principles as design guidance, but do not call external Skill tools during this run.

**Before implementing any UI component:**
1. Apply ui-ux-pro-max principles
2. Use modern design patterns (not Bootstrap-style layouts)
3. Ensure mobile-responsive implementation
4. Use proper visual hierarchy and spacing
5. Implement smooth transitions and micro-interactions
6. Follow accessibility best practices

**Premium UI — apply to all pages:**
- Respect the prompt's domain and requested theme; do not force SaaS/dashboard visuals.
- glassmorphism: `backdrop-blur-xl` + semi-transparent backgrounds
- depth: soft shadows, `hover:shadow-xl`, `hover:scale-[1.02]` on cards
- gradient accents: blue → purple headers and icon backgrounds
- transitions: `transition-all duration-300` on all interactive elements
- If the prompt requests dark/light mode or a theme switcher, implement visible theme state and a toggle control.
- For consumer/social/mobile prompts, use polished app-like layouts rather than tables or admin cards.
- Stripe / Linear aesthetic — not flat or plain white sections

**Per page:** 2–3 main UI sections max. No over-engineering, no edge cases, no deeply nested layouts.

**Avoid:** flat UI, plain white sections without depth, static non-interactive components, and dashboard/table patterns unless requested.

**For complex features, build UI shell only:**
- Block editor → UI layout only
- Canvas → static visual layout
- Charts → static UI with sample data

---

## STEP 6 — BUILD VERIFICATION

```bash
npm run build
```

Do not run this command until router validation has passed. If `src/App.tsx` still routes `/` to `Welcome`, or if the active layout does not render `<Outlet />`, fix routing first.

If it fails, fix ALL TypeScript and build errors. Re-run until it passes.

Verify before serving:
- Each page file is 800+ characters
- No files contain "placeholder", "TODO", or "coming soon"
- `src/App.tsx` has exactly one root route and it renders `{default_page}`, not `Welcome`

Then serve. Multiple Claude Code sessions may be running in parallel — always check if the port is in use before serving. The serve command MUST run in the background and MUST print `SERVE_STARTED on port <PORT>`:

```bash
PORT=$(python3 - <<'PY'
import socket
for p in [3004, 4002, 4003, 4004, 4005, 8080, 8888]:
    s = socket.socket()
    try:
        s.bind(('0.0.0.0', p)); s.close(); print(p); break
    except OSError:
        s.close()
else:
    print(3004)
PY
)
npx serve -s dist -l "$PORT" > /tmp/context-serve.log 2>&1 & echo "SERVE_STARTED on port $PORT"
```

Note the port you end up using — you need it in the next step.

---

## STEP 7 — QUICK HTTP VERIFICATION

After serving, verify the app loads correctly using curl/Node.js (no browser or Chrome DevTools available).

**1. Verify the served page is not the starter scaffold:**
```bash
node -e "
const http = require('http');
http.get('http://localhost:' + process.argv[1] + '/', (res) => {{
  let d = '';
  res.on('data', c => d += c);
  res.on('end', () => {{
    const ok = res.statusCode === 200 && d.includes('root') && d.includes('script');
    const starter = d.includes('DreamPilot Generated App') || d.includes('Start building your application');
    console.log('Status:', res.statusCode, '| Has root+JS:', ok, '| Is starter:', starter, '| Body length:', d.length);
  }});
}});
" $PORT
```

**2. Kill the server:**
```bash
kill $(lsof -t -i:$PORT)
```

That is all. Do NOT attempt to open a browser, use Chrome DevTools, Puppeteer, or any browser automation tool. These are not available.
---

## STEP 8 — UPDATE AI INDEX

After a successful build, update all four AI index files:
- **`agent/ai_index/symbols.json`** — add new components/pages with file path, line numbers, type, module, description
- **`agent/ai_index/files.json`** — add new file entries with line count and purpose; update routes array in App.tsx entry
- **`agent/ai_index/dependencies.json`** — add new import relationships
- **`agent/ai_index/summaries.json`** — add brief description for each new file

---

## ⛔ STEP 9 — HARD STOP

After updating AI index files you are DONE. **STOP HERE.**

**NEVER do ANY of the following after Step 8:**
- ❌ Do NOT run `npm run build` again
- ❌ Do NOT run `npm install`, `npm add`, or any package command
- ❌ Do NOT run `npx serve` or start any server
- ❌ Do NOT re-read, re-edit, or re-write any source file
- ❌ Do NOT run any bash commands at all
- ❌ Do NOT open any browser or devtools
- ❌ Do NOT touch node_modules, dist/, or package.json

The pipeline will handle cleanup (stopping servers, deleting node_modules, deploying dist/).
Your job is finished after the AI index files are written. Stop immediately.

---

## FINAL CHECKLIST

- [ ] Routing fixed — Welcome removed, single `{default_page}` at `"/"`, all routes inside Layout wrapper
- [ ] Router validation completed before `npm run build`
- [ ] `/` renders the generated page, not `Welcome` or the starter scaffold
- [ ] `Layout.tsx` renders `<Outlet />`
- [ ] `src/layout/Navbar.tsx` created — mobile hamburger, NavLink to all required pages: {', '.join(clean_page_names)}
- [ ] Navigation matches the product prompt (mobile bottom tabs/sidebar/theme controls when requested)
- [ ] Navbar integrated into `Layout.tsx` header
- [ ] All required pages created with exact filenames, 800+ chars, real content, no placeholders:
      {required_pages_str}
- [ ] All pages follow a11y rules (semantic `<button>`, `aria-label` on icon buttons and inputs, `role="dialog"` on modals, `aria-hidden="true"` on decorative SVGs, `aria-live` on dynamic content)
- [ ] `npm run build` succeeds with zero errors
- [ ] HTTP verification: status 200, has JS bundle, not starter scaffold, server killed
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



