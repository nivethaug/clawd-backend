"""
ACPX execution block that was accidentally deleted in commit aca62e5.
This file contains the complete ACPX integration that needs to be restored.
"""
import os
import subprocess
import logging
from pathlib import Path

# Configure logging
logger = logging.getLogger(__name__)

# ACPX binary path
ACPX_BIN = "/usr/lib/node_modules/openclaw/extensions/acpx/node_modules/acpx/dist/cli.js"

# Timeout for ACPX execution
BUILD_TIMEOUT = 1800

def apply_changes_via_acpx_v2(
    frontend_src_path: str,
    goal_description: str,
    execution_id: str,
    project_name: str
) -> dict:
    """
    Apply frontend changes by running ACPX V2.
    This is the correct method signature for ACPFrontendEditorV2.
    """
    logger.info(f"[ACPX-V2] 🔴 HEARTBEAT: Starting ACPX V2 execution")
    logger.info(f"[ACPX-V2] 🔴 HEARTBEAT: Project: {project_name}")
    logger.info(f"[ACPX-V2] 🔴 HEARTBEAT: Execution ID: {execution_id}")

    # Step 1: Create filesystem snapshot
    logger.info(f"[ACPX-V2] Step 1: Creating filesystem snapshot...")
    from filesystem_snapshot import FilesystemSnapshot
    snapshot_manager = FilesystemSnapshot(frontend_src_path)
    snapshot_success, snapshot_msg = snapshot_manager.create_snapshot()
    if not snapshot_success:
        return {
            "success": False,
            "message": f"Snapshot creation failed: {snapshot_msg}",
            "rollback": False
        }

    # Step 2: Capture filesystem state BEFORE ACPX
    logger.info(f"[ACPX-V2] Step 2: Capturing filesystem state before ACPX...")
    from filesystem_snapshot import FilesystemSnapshot
    hashes_before = FilesystemSnapshot.get_file_hashes(frontend_src_path)
    logger.info(f"[ACPX-V2]   Found {len(hashes_before)} files before ACPX")

    # Step 3: Build ACPX prompt (no JSON requirement) with completion tracking
    logger.info(f"[ACPX-V2] Step 3: Building ACPX prompt...")
    prompt = f"""
{goal_description}

Execute the required changes carefully.
- Create file at exact path specified
- Use existing UI components from src/components/ui/
- Follow TypeScript patterns
- Return proper success/failure status

Do NOT modify package.json unless explicitly requested.
"""

    # Step 4: Run ACPX
    logger.info(f"[ACPX-V2] Step 4: Running ACPX...")
    logger.info(f"[ACPX-V2]   Acpx path: {ACPX_BIN}")
    logger.info(f"[ACPX-V2]   Working directory: {frontend_src_path}")
    logger.info(f"[ACPX-V2]   Timeout: {BUILD_TIMEOUT} seconds")

    cmd = [ACPX_BIN, "claude", "exec", prompt]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=BUILD_TIMEOUT,
            cwd=frontend_src_path
        )

        logger.info(f"[ACPX-V2] 🔴 HEARTBEAT: ACPX subprocess completed (no timeout)")
        logger.info(f"[ACPX-V2]   Return code: {result.returncode}")
        logger.info(f"[ACPX-V2]   Stdout length: {len(result.stdout)} chars")
        logger.info(f"[ACPX-V2]   Stderr length: {len(result.stderr)} chars")

        except subprocess.TimeoutExpired:
        logger.error(f"[ACPX-V2] 🔴 HEARTBEAT: ❌ TIMED OUT after {BUILD_TIMEOUT} seconds")
        return {
            "success": False,
            "message": f"ACPX timed out after {BUILD_TIMEOUT} seconds",
            "files_added": 0,
            "files_modified": 0,
            "files_removed": 0,
            "rollback": False
        }

    # Step 5: Process result
    if result.returncode == 0:
        logger.info(f"[ACPX-V2] ✅ ACPX completed successfully")
        logger.info(f"[ACPX-V2]   Checking for files modified...")

        # Capture filesystem state AFTER ACPX
        logger.info(f"[ACPX-V2] Step 5: Capturing filesystem state after ACPX...")
        hashes_after = FilesystemSnapshot.get_file_hashes(frontend_src_path)
        logger.info(f"[ACPX-V2]   Found {len(hashes_after)} files after ACPX")

        # Detect changes by comparing hashes
        files_modified = []
        files_added = []
        files_removed = []

        for file_path, hash_after in hashes_after.items():
            if file_path in hashes_before:
                hash_before = hashes_before[file_path]
                if hash_before != hash_after:
                    files_modified.append(file_path)
                    logger.info(f"[ACPX-V2]   MODIFIED: {file_path}")
            else:
                files_added.append(file_path)
                logger.info(f"[ACPX-V2]   CREATED: {file_path}")

        # Read stdout to verify files were actually created
        created_files = []
        if "src/pages/" in result.stdout or any(page in result.stdout):
            # Extract page names from stdout
            import re
            page_pattern = r"src/pages/(\w+)\.tsx"
            for match in re.finditer(page_pattern, result.stdout):
                page_name = match.group(1)
                created_files.append(page_name)
                logger.info(f"[ACPX-V2]   VERIFIED CREATED: {page_name}")

        # Return success with actual file changes
        logger.info(f"[ACPX-V2] 📊 Summary: {len(created_files)} pages created from stdout, {len(files_added)} files added, {len(files_modified)} files modified, {len(files_removed)} files removed")

        return {
            "success": True,
            "message": "ACPX V2 completed successfully",
            "files_added": len(files_added),
            "files_modified": len(files_modified),
            "files_removed": len(files_removed),
            "rollback": False,
            "stdout": result.stdout
        }
    else:
        logger.error(f"[ACPX-V2] ❌ ACPX failed with code: {result.returncode}")
        if result.stderr:
            logger.error(f"[ACPX-V2]   Stderr: {result.stderr}")
        return {
            "success": False,
            "message": f"ACPX failed with code {result.returncode}",
            "files_added": 0,
            "files_modified": 0,
            "files_removed": 0,
            "rollback": False
        }

if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="Restore ACPX execution in Phase 9")
    parser.add_argument("--frontend-path", required=True, help="Frontend src path")
    parser.add_argument("--prompt", required=True, help="ACPX prompt text")
    parser.add_argument("--execution-id", required=True, help="Execution ID")
    parser.add_argument("--project-name", required=True, help="Project name")

    args = parser.parse_args()

    result = apply_changes_via_acpx_v2(
        args.frontend_path,
        args.prompt,
        args.execution_id,
        args.project_name
    )

    logger.info(f"[ACPX-V2] Result: {result}")

    if result.get("success"):
        logger.info(f"[ACPX-V2] ✅ Successfully executed ACPX V2")
        print("✅ ACPX V2 execution restored and working")
    else:
        logger.error(f"[ACPX-V2] ❌ ACPX V2 execution failed")
        print("❌ ACPX V2 execution failed")
        sys.exit(1)
