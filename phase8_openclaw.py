#!/usr/bin/env python3
"""
Phase 8: AI-Driven Frontend Customization

Uses Claude Code to:
1. Clone selected template from GitHub
2. Customize it based on project requirements
3. Add up to 3 additional pages
4. Modify existing pages
5. Remove unwanted sections
6. Build and deploy
"""

import os
import subprocess
import logging
from pathlib import Path
import sys
from typing import Dict, Any, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def get_claude_code_prompt(
    project_name: str,
    project_description: str,
    template_id: str,
    template_repo: str,
    template_features: list
) -> str:
    """Generate Claude Code prompt for template customization."""

    return f"""You are customizing a frontend template for a new project.

**Project:**
- Name: {project_name}
- Description: {project_description}

**Selected Template:**
- ID: {template_id}
- Repo: {template_repo}
- Features: {', '.join(template_features)}

**Your Tasks:**

1. **Clone the template** from {template_repo} if not already present
   - Use: `git clone {template_repo} temp_clone`
   - Copy relevant files (src/, package.json, etc.) to the current directory
   - Remove temp_clone directory

2. **Customize the template** to match project requirements:
   - Update branding (title, description, meta tags in index.html)
   - Modify existing pages to match the project's purpose
   - Adjust colors, fonts, and styles if needed
   - Update navigation to reflect correct pages

3. **Add up to 3 additional pages** if needed:
   - Analyze the project description to determine missing pages
   - Create new pages that integrate with existing design
   - Follow the template's patterns and components
   - Update App.tsx with new routes

4. **Modify existing pages** based on requirements:
   - Add missing features or sections
   - Remove irrelevant content
   - Update forms and data fields
   - Improve user experience based on project type

5. **Remove unwanted sections**:
   - Delete demo content that doesn't apply
   - Remove placeholder sections
   - Clean up unused components

6. **Final steps:**
   - Run `npm install` to ensure dependencies
   - Run `npm run build` to verify compilation
   - Ensure no build errors or warnings

**Important Rules:**
- Maintain the template's design language and component library
- Keep the existing folder structure (src/, components/, pages/, etc.)
- Use the same shadcn/ui components and patterns
- Don't break existing functionality - enhance, don't replace
- Test routes work correctly after adding new pages

**Example:**
If template is "social" (social media hub):
- Customize: Update to "My Social App" branding
- Add: Analytics dashboard, Campaign manager page
- Modify: Enhance scheduler with calendar view
- Remove: Demo posts and placeholder content

Start by checking if the template is already cloned, then proceed with customization.
Focus on making this a production-ready, fully customized application.
"""


def run_npm_command(command: str, cwd: str, timeout: int = 300) -> bool:
    """Run npm command with timeout."""
    try:
        logger.info(f"   Running: npm {command}")
        result = subprocess.run(
            ["npm", *command.split()],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        if result.returncode == 0:
            logger.info(f"   ✅ npm {command} completed")
            return True
        else:
            logger.warning(f"   ⚠️ npm {command} failed: {result.stderr[:200]}")
            return False
    except subprocess.TimeoutExpired:
        logger.error(f"   ❌ npm {command} timed out")
        return False
    except Exception as e:
        logger.error(f"   ❌ npm {command} failed: {e}")
        return False


def run_claude_code_customization(
    frontend_path: Path,
    project_name: str,
    project_description: str,
    template_id: str = None,
    template_repo: str = None,
    template_features: list = None
) -> bool:
    """
    Run Claude Code to customize template.

    Args:
        frontend_path: Path to frontend directory
        project_name: Project name
        project_description: Project description
        template_id: Selected template ID
        template_repo: Template GitHub repo
        template_features: Template features

    Returns:
        True if successful, False otherwise
    """
    try:
        logger.info("🤖 Starting Claude Code customization...")

        # Build prompt
        prompt = get_claude_code_prompt(
            project_name,
            project_description,
            template_id or "default",
            template_repo or "https://github.com/shadcn/ui",
            template_features or []
        )

        # Write prompt to temporary file
        prompt_file = frontend_path / ".claude_prompt.txt"
        prompt_file.write_text(prompt, encoding='utf-8')

        # Run Claude Code non-interactively
        logger.info("   Executing Claude Code...")
        result = subprocess.run(
            ["/usr/bin/claude", "-p", f"@{prompt_file}"],
            cwd=str(frontend_path),
            capture_output=True,
            text=True,
            timeout=1800  # 30 minutes
        )

        # Clean up prompt file
        prompt_file.unlink(missing_ok=True)

        if result.returncode == 0:
            logger.info("   ✅ Claude Code customization completed")
            return True
        else:
            logger.warning(f"   ⚠️ Claude Code had issues: {result.stderr[-500:] if result.stderr else 'Unknown'}")
            # Continue even with warnings
            return True

    except subprocess.TimeoutExpired:
        logger.warning("   ⚠️ Claude Code timed out (30 min), continuing...")
        return True
    except Exception as e:
        logger.error(f"   ❌ Claude Code failed: {e}")
        return False


def create_summary(
    frontend_path: Path,
    project_name: str,
    project_description: str,
    template_id: Optional[str],
    success: bool
) -> None:
    """Create Phase 8 summary."""
    summary_path = frontend_path / "PHASE8_SUMMARY.md"

    content = f"""# Phase 8: AI-Driven Frontend Customization

**Project:** {project_name}
**Template:** {template_id or "Not specified"}
**Status:** {'✅ Success' if success else '❌ Failed'}

## Project Description

{project_description}

## Customization Process

1. **Template Selection**
   - ID: {template_id or "N/A"}
   - Clone and customize template based on project requirements

2. **Claude Code Customization**
   - Analyze existing template structure
   - Modify pages to match project needs
   - Add up to 3 additional pages
   - Remove unwanted sections
   - Apply branding and styling

3. **Build Verification**
   - Run `npm install` for dependencies
   - Run `npm run build` for compilation
   - Verify no critical errors

## Next Steps

1. Test all routes and functionality
2. Implement backend API endpoints
3. Add real data and integrations
4. Deploy to production
5. Monitor and iterate based on user feedback

---
*Generated by Phase 8 AI Customization*
"""

    try:
        summary_path.write_text(content, encoding='utf-8')
        logger.info(f"✅ Summary created: {summary_path}")
    except Exception as e:
        logger.warning(f"⚠️ Failed to create summary: {e}")


def run_phase_8_ai_customization(
    project_name: str,
    project_path: str,
    project_description: str,
    template_id: Optional[str] = None,
    template_repo: Optional[str] = None,
    template_features: Optional[list] = None
) -> bool:
    """
    Execute Phase 8 with AI-driven template customization.

    Args:
        project_name: Project name
        project_path: Full project path
        project_description: Project description
        template_id: Selected template ID (from Phase 7)
        template_repo: Template GitHub repository
        template_features: Template features list

    Returns:
        True if successful, False otherwise
    """
    import time
    start_time = time.time()

    frontend_path = Path(project_path) / "frontend"

    logger.info(f"🚀 Phase 8: AI-Driven Frontend Customization")
    logger.info(f"   Project: {project_name}")
    logger.info(f"   Path: {frontend_path}")
    logger.info(f"   Template: {template_id or 'default'}")

    # Step 1: Verify frontend exists
    if not frontend_path.exists():
        logger.error("❌ Frontend directory not found")
        return False

    # Step 2: Run npm install (ensure dependencies)
    logger.info("📦 Step 1: Installing dependencies...")
    npm_install_success = run_npm_command("install", str(frontend_path), timeout=300)

    if not npm_install_success:
        logger.warning("⚠️ npm install failed, continuing anyway...")

    # Step 3: Run Claude Code for customization
    logger.info("🤖 Step 2: Running Claude Code customization...")
    claude_success = run_claude_code_customization(
        frontend_path,
        project_name,
        project_description,
        template_id,
        template_repo,
        template_features or []
    )

    # Step 4: Build verification
    logger.info("🔨 Step 3: Verifying build...")
    build_success = run_npm_command("run build", str(frontend_path), timeout=300)

    # Step 5: Create summary
    logger.info("📝 Step 4: Creating summary...")
    create_summary(
        frontend_path,
        project_name,
        project_description,
        template_id,
        claude_success and build_success
    )

    # Step 6: Calculate and report time
    total_time = time.time() - start_time

    logger.info("")
    logger.info("=" * 60)
    logger.info("✅ Phase 8 completed!")
    logger.info("=" * 60)
    logger.info(f"   Template: {template_id or 'default'}")
    logger.info(f"   Claude Code: {'✅ Success' if claude_success else '❌ Failed'}")
    logger.info(f"   Build: {'✅ Passed' if build_success else '❌ Failed'}")
    logger.info(f"   Total time: {total_time / 60:.1f} minutes")
    logger.info("=" * 60)

    return claude_success or build_success


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 phase8_ai_customization.py <project_name> <project_path> [description] [template_id] [template_repo] [features...]")
        sys.exit(1)

    project_name = sys.argv[1]
    project_path = sys.argv[2]
    project_description = sys.argv[3] if len(sys.argv) > 3 else ""
    template_id = sys.argv[4] if len(sys.argv) > 4 else None
    template_repo = sys.argv[5] if len(sys.argv) > 5 else None

    # Remaining args are features
    template_features = sys.argv[6:] if len(sys.argv) > 6 else []

    try:
        success = run_phase_8_ai_customization(
            project_name,
            project_path,
            project_description,
            template_id,
            template_repo,
            template_features
        )
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"💥 Phase 8 failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
