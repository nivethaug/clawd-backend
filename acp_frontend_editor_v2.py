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

        # Phase 9: Guardrails - Store allowed pages whitelist
        self.allowed_pages: Set[str] = set()

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
            rel_path = str(file_path.relative_to(self.frontend_src_path))
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

        # Step 9: Enforce page guardrails (BEFORE build to prevent routing issues)
        logger.info(f"[ACPX-V2] Step 9: Enforcing page guardrails (BEFORE build)...")
        unauthorized_removed = self._enforce_page_guardrails()

        if unauthorized_removed > 0:
            logger.info(f"[ACPX-V2]   ⚠️  Removed {unauthorized_removed} unauthorized page(s)")
        else:
            logger.info(f"[ACPX-V2]   ✓ All pages authorized")

        # Step 10: Run build gate (AFTER guardrails to prevent build errors)
        logger.info(f"[ACPX-V2] Step 10: Running build gate (npm install && npm run build)...")
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

        # Step 11: Success - cleanup snapshot
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
            # Call LLM for page inference
            llm_cmd = [
                "node",
                "/usr/lib/node_modules/openclaw/extensions/acpx/node_modules/acpx/dist/cli.js",
                "claude",
                "exec",
                inference_prompt
            ]

            result = subprocess.run(
                llm_cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd="/tmp"
            )

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

    def _build_acpx_prompt(self, goal_description: str) -> str:
        """
        Build ACPX prompt with explicit required artifacts and completion checklist.

        Args:
            goal_description: Goal for changes

        Returns:
            Prompt string for ACPX
        """
        # Extract required pages from goal description (improved planner)
        required_pages = []
        required_components = []

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

        # Step 1: Extract explicit page lists (highest priority)
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

        # Step 2: AI Page Inference (if no explicit pages found) - NEW
        if not explicit_match:
            logger.info("[Planner] Triggering AI page inference")
            logger.info(f"[Planner] Description for inference: {goal_description[:200]}...")
            inferred_pages = self._ai_infer_pages(goal_description)
            required_pages.extend(inferred_pages)
            logger.info(f"[Planner] AI inferred pages: {inferred_pages}")

        # Step 3: Keyword matching (if explicit list not found or incomplete)
        desc_lower = goal_description.lower()
        for page_name, keywords in PAGE_KEYWORDS.items():
            if page_name not in required_pages:  # Skip if already in explicit list
                if any(keyword in desc_lower for keyword in keywords):
                    required_pages.append(page_name)

        # Step 3: SaaS default fallback (if less than 3 pages detected)
        if len(required_pages) < 3:
            logger.info(f"[Planner] Fewer than 3 pages detected ({len(required_pages)}), adding SaaS defaults")
            saas_defaults = ["Dashboard", "Analytics", "Contacts", "Settings"]
            for default_page in saas_defaults:
                if default_page not in required_pages:
                    required_pages.append(default_page)

        # Step 4: Remove duplicates while preserving order
        required_pages = list(dict.fromkeys(required_pages))

        # Phase 9: Store allowed pages whitelist for guardrails
        self.allowed_pages = set(required_pages)
        logger.info(f"[Phase9] Allowed pages: {required_pages}")

        # Planner logging
        logger.info(f"[Planner] Description: {goal_description}")
        logger.info(f"[Planner] Detected pages: {required_pages}")

        # Build required artifacts list
        required_pages_list = required_pages
        required_components_list = list(set(required_components))

        required_pages_str = "\n".join([f"- src/pages/{page}.tsx" for page in required_pages_list])
        required_components_str = "\n".join([f"- src/components/{comp}.tsx" for comp in required_components_list])

        # Phase 9: Build page templates section
        page_templates_section = self._build_page_templates_section(required_pages, goal_description)

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
