#!/usr/bin/env python3
"""
Phase 8: Frontend Refinement using OpenClaw Sessions

Instead of CrewAI's write_file tool (which doesn't save files),
we use OpenClaw CLI to spawn an agent session with file tools.
"""

import os
import subprocess
import json
import logging
from pathlib import Path
from time import time
from typing import List, Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def create_refinement_prompt(project_name: str, files: List[str]) -> str:
    """Create OpenClaw prompt for frontend refinement."""
    
    files_list = "\n".join(f"  - {f}" for f in files)
    
    return f"""You are refining a cloned frontend template into a production-ready application.

PROJECT INFORMATION:
- Project Name: {project_name}
- Working Directory: See files list below

FILES TO MODIFY:
{files_list}

INSTRUCTIONS:
1. Read each file using the read tool
2. Replace all "Lovable" branding with "{project_name}"
3. Replace "Lovable App" with "{project_name}" in HTML title
4. Update meta tags and author information
5. Keep all functionality intact
6. Use minimal, focused changes

For HTML files:
- Update <title>Lovable App</title> to <title>{project_name}</title>
- Update <meta name="author" content="Lovable" /> to {project_name}
- Update <meta property="og:title" content="Lovable App" /> to {project_name}

For TypeScript/TSX files:
- Update app titles and headers
- Replace any hardcoded "Lovable" text
- Keep existing imports and component structure

IMPORTANT:
- Use the 'read' and 'write' tools (NOT write_file from CrewAI)
- Files are in src/pages/ not src/features/
- Work in the current directory
- Check if file exists before attempting to modify

Complete all file modifications. Output a summary of changes made."""


def run_openclaw_agent(prompt: str, cwd: str) -> Dict[str, Any]:
    """Run OpenClaw agent with file tools."""
    
    logger.info(f"🤖 Spawning OpenClaw agent session...")
    logger.info(f"   Working directory: {cwd}")
    
    try:
        # Use OpenClaw CLI with local mode
        # This gives access to read/write tools
        cmd = [
            "openclaw",
            "agent",
            "--local",
            "--message", prompt,
            "--thinking", "low",
            "--timeout", "300"  # 5 minutes
        ]
        
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=360  # 6 minutes max
        )
        
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
        
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "timeout"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def run_npm_build(cwd: str) -> Dict[str, Any]:
    """Run npm build to verify changes."""
    
    logger.info("🔨 Running `npm run build`")
    
    try:
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode == 0:
            logger.info("✅ Build succeeded!")
            return {
                "success": True,
                "stdout": result.stdout,
                "stderr": result.stderr
            }
        else:
            logger.error(f"❌ Build failed with code: {result.returncode}")
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


def git_commit(message: str, cwd: str) -> Dict[str, Any]:
    """Commit changes with message."""
    
    logger.info(f"🔀 Committing: {message[:50]}...")
    
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
            logger.info(f"✅ Committed: {message[:50]}...")
            return {"success": True}
        else:
            logger.error(f"❌ Git commit failed")
            return {"success": False, "stderr": result.stderr}
            
    except Exception as e:
        logger.error(f"❌ Git commit error: {e}")
        return {"success": False}


def run_phase_8_openclaw(project_name: str, project_path: str, description: str) -> bool:
    """Execute Phase 8 using OpenClaw agent sessions."""
    
    frontend_path = Path(project_path) / "frontend"
    
    logger.info(f"🚀 Starting Phase 8: OpenClaw Agent Frontend Refinement")
    logger.info(f"   Project: {project_name}")
    logger.info(f"   Frontend path: {frontend_path}")
    
    # Define batches
    batches = [
        {
            "name": "Core Branding",
            "files": [
                "index.html",
                "src/App.tsx"
            ],
            "description": f"Replace 'Lovable' branding with '{project_name}' in core files"
        },
        {
            "name": "Page Branding",
            "files": [
                "src/pages/Dashboard.tsx",
                "src/pages/Account.tsx",
                "src/pages/Settings.tsx"
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
    
    start_time = time.time()
    
    # Execute each batch
    for batch_num, batch in enumerate(batches, 1):
        batch_name = batch["name"]
        batch_files = batch["files"]
        batch_desc = batch["description"]
        
        logger.info(f"\n{'='*60}")
        logger.info(f"📦 Batch {batch_num}/{len(batches)}: {batch_name}")
        logger.info(f"{'='*60}")
        
        # Check if files exist
        missing_files = []
        for file_path in batch_files:
            full_path = frontend_path / file_path
            if not full_path.exists():
                missing_files.append(file_path)
                logger.warning(f"⚠️ File not found: {file_path}")
        
        if missing_files:
            logger.error(f"❌ Skipping batch {batch_num}: {len(missing_files)} files not found")
            summary["batches_failed"] += 1
            continue
        
        # Create prompt for this batch
        prompt = create_refinement_prompt(project_name, batch_files)
        
        # Run OpenClaw agent
        logger.info(f"🤖 Running OpenClaw agent for {len(batch_files)} files...")
        result = run_openclaw_agent(prompt, str(frontend_path))
        
        if result["success"]:
            logger.info(f"✅ Batch {batch_num} completed")
            summary["batches_executed"] += 1
            summary["batches_succeeded"] += 1
            summary["files_modified"].extend(batch_files)
            
            # Verify build
            build_result = run_npm_build(str(frontend_path))
            if build_result["success"]:
                logger.info(f"✅ Build passed after batch {batch_num}")
                
                # Commit changes
                commit_msg = f"Phase 8: Batch {batch_num} - {batch_name}"
                git_commit(commit_msg, str(frontend_path))
            else:
                logger.error(f"❌ Build failed after batch {batch_num}")
                summary["batches_failed"] += 1
        else:
            logger.error(f"❌ Batch {batch_num} failed")
            logger.error(f"   Error: {result.get('error', result.get('stderr', 'Unknown'))}")
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

## OpenClaw Agent Version

Using OpenClaw CLI with file tools:
- `read` tool: Read file content
- `write` tool: Write new content
- Local mode: Agent runs in project directory

Generated: 2026-02-26
"""
    
    summary_path = frontend_path / "SUMMARY.md"
    try:
        with open(summary_path, 'w') as f:
            f.write(summary_md)
        logger.info(f"✅ SUMMARY.md created: {summary_path}")
    except Exception as e:
        logger.error(f"❌ Failed to create SUMMARY.md: {e}")
    
    # Print summary
    logger.info(f"\n{'='*60}")
    logger.info(f"✅ Phase 8 completed!")
    logger.info(f"{'='*60}")
    logger.info(f"   Total time: {total_time:.1f} minutes")
    logger.info(f"   Batches: {summary['batches_succeeded']}/{len(batches)} succeeded")
    logger.info(f"   Files: {len(summary['files_modified'])} modified")
    logger.info(f"{'='*60}")
    
    return summary['batches_succeeded'] > 0


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python3 phase8_openclaw.py <project_name> <project_path> [description]")
        sys.exit(1)
    
    project_name = sys.argv[1]
    project_path = sys.argv[2]
    description = sys.argv[3] if len(sys.argv) > 3 else "Frontend refinement"
    
    try:
        success = run_phase_8_openclaw(project_name, project_path, description)
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"❌ Phase 8 failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
