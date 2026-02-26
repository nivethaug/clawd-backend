#!/usr/bin/env python3
"""
Phase 8: Frontend Refinement using Direct File Operations

Simple, reliable file operations to replace "Lovable" branding.
"""

import os
import subprocess
import re
import logging
from pathlib import Path
import sys
from typing import List, Dict, Tuple, Union, Any

# Configure logging (simple to avoid time module conflicts)
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def replace_in_file(file_path: Path, replacements: List[Tuple[str, Union[str, re.Pattern]]], project_name: str) -> bool:
    """Replace patterns in a file.
    
    Args:
        file_path: Path to file
        replacements: List of (pattern, replacement) tuples
        project_name: Project name for logging
    
    Returns:
        True if modified, False otherwise
    """
    logger.info(f"Processing: {file_path}")
    
    try:
        # Read file
        content = file_path.read_text(encoding='utf-8')
        original_content = content
        
        # Apply all replacements
        for pattern, replacement in replacements:
            if isinstance(pattern, str):
                # String replacement
                new_content = content.replace(pattern, replacement)
                if new_content != content:
                    content = new_content
            else:
                # Regex replacement
                new_content = pattern.sub(replacement, content)
                if new_content != content:
                    content = new_content
        
        # Write if changed
        if content != original_content:
            file_path.write_text(content, encoding='utf-8')
            logger.info(f"Modified: {file_path}")
            return True
        else:
            logger.info(f"Skipped (no changes needed): {file_path}")
            return False
            
    except Exception as e:
        logger.error(f"Failed to modify {file_path}: {e}")
        return False


def run_npm_build(cwd: str) -> Dict[str, Any]:
    """Run npm build to verify changes."""
    
    logger.info("Running npm run build")
    
    try:
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode == 0:
            logger.info("Build succeeded!")
            return {
                "success": True,
                "stdout": result.stdout,
                "stderr": result.stderr
            }
        else:
            logger.error(f"Build failed with code: {result.returncode}")
            return {
                "success": False,
                "stdout": result.stdout,
                "stderr": result.stderr
            }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "timeout"
        }
    except Exception as e:
        logger.error(f"Build failed with exception: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def git_commit(message: str, cwd: str) -> Dict[str, Any]:
    """Commit changes with message."""
    
    logger.info(f"Committing: {message[:50]}...")
    
    try:
        # Stage all changes
        subprocess.run(
            ["git", "add", "."],
            cwd=cwd,
            capture_output=True,
            timeout=60
        )
        
        # Commit
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            logger.info(f"Committed: {message[:50]}...")
            return {"success": True}
        else:
            logger.error("Git commit failed")
            return {"success": False, "stderr": result.stderr}
            
    except Exception as e:
        logger.error(f"Git commit error: {e}")
        return {"success": False}


def run_phase_8_direct(project_name: str, project_path: str, description: str) -> bool:
    """Execute Phase 8 using direct file operations."""
    
    frontend_path = Path(project_path) / "frontend"
    
    logger.info(f"Starting Phase 8: Direct File Operations")
    logger.info(f"  Project: {project_name}")
    logger.info(f"  Frontend path: {frontend_path}")
    
    # Define batches
    batches = [
        {
            "name": "Core Branding",
            "files": [
                ("index.html", [
                    (r"<title>Lovable App</title>", f"<title>{project_name}</title>"),
                    (r'<meta name="description" content="Lovable Generated Project" />',
                     f'<meta name="description" content="{project_name} - Generated Project" />'),
                    (r'<meta name="author" content="Lovable" />',
                     f'<meta name="author" content="{project_name}" />'),
                    (r'<meta property="og:title" content="Lovable App" />',
                     f'<meta property="og:title" content="{project_name}" />'),
                    (r'<meta property="og:description" content="Lovable Generated Project" />',
                     f'<meta property="og:description" content="{project_name} - Generated Project" />'),
                ]),
                ("src/App.tsx", [
                    (r"Lovable App", project_name),
                    (r"Lovable", project_name),
                ])
            ],
            "description": f"Replace 'Lovable' branding with '{project_name}' in core files"
        },
        {
            "name": "Page Branding",
            "files": [
                ("src/pages/Dashboard.tsx", [
                    (r"Lovable App", project_name),
                ]),
                ("src/pages/Account.tsx", [
                    (r"Lovable App", project_name),
                ]),
                ("src/pages/Settings.tsx", [
                    (r"Lovable App", project_name),
                ])
            ],
            "description": f"Add '{project_name}' branding to page components"
        }
    ]
    
    summary = {
        "project": project_name,
        "batches_executed": 0,
        "batches_succeeded": 0,
        "batches_failed": 0,
        "files_modified": []
    }
    
    import time
    start_time = time.time()
    
    # Execute each batch
    for batch_num, batch in enumerate(batches, 1):
        batch_name = batch["name"]
        batch_files = batch["files"]
        batch_desc = batch["description"]
        
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"Batch {batch_num}/{len(batches)}: {batch_name}")
        logger.info("=" * 60)
        
        files_modified_count = 0
        
        # Process each file
        for file_name, replacements in batch_files:
            file_path = frontend_path / file_name
            
            if not file_path.exists():
                logger.warning(f"File not found: {file_name}")
                continue
            
            # Replace in file
            if replace_in_file(file_path, replacements, project_name):
                files_modified_count += 1
                summary["files_modified"].append(file_name)
        
        if files_modified_count == 0:
            logger.info(f"No files needed modifications in batch {batch_num}")
            summary["batches_executed"] += 1
            continue
        
        # Verify build
        build_result = run_npm_build(str(frontend_path))
        if build_result["success"]:
            logger.info(f"Build passed after batch {batch_num}")
            
            # Commit changes
            commit_msg = f"Phase 8: Batch {batch_num} - {batch_name}"
            git_commit(commit_msg, str(frontend_path))
            
            summary["batches_executed"] += 1
            summary["batches_succeeded"] += 1
        else:
            logger.error(f"Build failed after batch {batch_num}")
            summary["batches_executed"] += 1
            summary["batches_failed"] += 1
    
    # Calculate total time
    total_time = time.time() - start_time
    
    # Generate SUMMARY.md
    summary_md = f"""# Phase 8: Frontend Refinement Summary

**Project:** {project_name}
**Execution Date:** 2026-02-26
**Total Duration:** {total_time:.1f} minutes

## Execution Statistics

- **Batches Executed:** {summary['batches_executed']}
- **Batches Succeeded:** {summary['batches_succeeded']}
- **Batches Failed:** {summary['batches_failed']}
- **Files Modified:** {len(summary['files_modified'])}

## Files Modified

{chr(10).join(f"- `{f}`" for f in summary['files_modified'])}

## Git Commits

Total {summary['batches_succeeded']} commits created, one per batch.

## Next Steps

1. Review SUMMARY.md for overview of changes
2. Restart PM2 frontend service
3. Verify frontend accessible at live URL
4. Test all modified functionality

## Phase 8 Implementation

Using direct file operations with Python:
- Pattern-based replacements in files
- Build verification after each batch
- Git commits per batch
- No external dependencies (reliable & fast)

Generated: 2026-02-26
"""
    
    summary_path = frontend_path / "SUMMARY.md"
    try:
        with open(summary_path, 'w') as f:
            f.write(summary_md)
        logger.info(f"SUMMARY.md created: {summary_path}")
    except Exception as e:
        logger.error(f"Failed to create SUMMARY.md: {e}")
    
    # Print summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("Phase 8 completed!")
    logger.info("=" * 60)
    logger.info(f"Total time: {total_time:.1f} minutes")
    logger.info(f"Batches: {summary['batches_succeeded']}/{len(batches)} succeeded")
    logger.info(f"Files: {len(summary['files_modified'])} modified")
    logger.info("=" * 60)
    
    return summary['batches_succeeded'] > 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 phase8_openclaw.py <project_name> <project_path> [description]")
        sys.exit(1)
    
    project_name = sys.argv[1]
    project_path = sys.argv[2]
    description = sys.argv[3] if len(sys.argv) > 3 else "Frontend refinement"
    
    try:
        success = run_phase_8_direct(project_name, project_path, description)
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"Phase 8 failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
