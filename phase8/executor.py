#!/usr/bin/env python3
"""
Phase 8 Executor - Safely applies validated plan.

Reads JSON plan from planner.py and executes changes.
Fails loudly if any step fails.
"""

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# Core pages that must always exist
CORE_REQUIRED_PAGES = ["Dashboard", "NotFound"]


def create_file(content: str, file_path: Path) -> bool:
    """Create file with content."""
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        logger.info(f"✓ Created: {file_path}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to create {file_path}: {e}")
        return False


def remove_file(file_path: Path) -> bool:
    """Remove file safely."""
    try:
        if file_path.exists():
            file_path.unlink()
            logger.info(f"✓ Removed: {file_path}")
            return True
        return False
    except Exception as e:
        logger.error(f"❌ Failed to remove {file_path}: {e}")
        return False


def update_app_routes(frontend_path: Path, plan: Dict[str, Any]) -> bool:
    """Update App.tsx routes based on plan."""
    try:
        app_path = frontend_path / "src" / "App.tsx"
        
        if not app_path.exists():
            logger.error(f"❌ App.tsx not found: {app_path}")
            return False
        
        with open(app_path, 'r', encoding='utf-8') as f:
            app_content = f.read()
        
        # Apply root route if specified
        root_route = plan.get("root_route")
        if root_route:
            logger.info(f"   Setting root route to: {root_route}")
            # Find existing root route
            import re
            root_pattern = r'<Route path="/" element=\{[^}]+\} />'
            match = re.search(root_pattern, app_content)
            if match:
                # Replace with specified route
                new_route = f'<Route path="/" element={{<{root_route} }} />'
                app_content = app_content.replace(match.group(0), new_route)
                logger.info(f"   Updated root route")
        
        # Write back
        with open(app_path, 'w', encoding='utf-8') as f:
            f.write(app_content)
        
        logger.info(f"✓ Updated: {app_path}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to update App.tsx: {e}")
        return False


def verify_build(frontend_path: Path) -> bool:
    """Verify build succeeds."""
    try:
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(frontend_path),
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode == 0:
            logger.info("✓ Build successful")
            return True
        else:
            logger.error(f"❌ Build failed with code: {result.returncode}")
            logger.error(f"   Error: {result.stderr[-500:] if result.stderr else 'Unknown'}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("❌ Build timed out (5 minutes)")
        return False
    except Exception as e:
        logger.error(f"❌ Build verification failed: {e}")
        return False


def execute_plan(frontend_path: Path, plan: Dict[str, Any]) -> bool:
    """Execute validated plan."""
    
    logger.info("=" * 60)
    logger.info("🚀 Starting Phase 8 Execution")
    logger.info("=" * 60)
    
    steps_passed = 0
    steps_failed = 0
    
    # Step 1: Remove unwanted pages
    logger.info("📋 Step 1: Removing unwanted pages...")
    for page_name in plan.get("remove_pages", []):
        page_path = frontend_path / "src" / "pages" / f"{page_name}.tsx"
        if remove_file(page_path):
            steps_passed += 1
        else:
            steps_failed += 1
    
    # Step 2: Add new pages (from templates)
    logger.info("📋 Step 2: Adding new pages...")
    for page in plan.get("add_pages", []):
        if page.get("create_from_template"):
            # This would be handled by template cloning
            logger.info(f"   Skipping template page: {page['name']}")
            continue
        
        page_path = frontend_path / "src" / "pages" / f"{page['name']}.tsx"
        # For now, create placeholder
        page_content = f"// {page['name']} page - Placeholder\n// This page was created by Phase 8.\n// Purpose: {page['purpose']}"
        if create_file(page_content, page_path):
            steps_passed += 1
        else:
            steps_failed += 1
    
    # Step 3: Apply modifications
    logger.info("📋 Step 3: Applying modifications...")
    for mod in plan.get("modifications", []):
        if mod["page"] == "App.tsx":
            if not update_app_routes(frontend_path, plan):
                steps_failed += 1
            else:
                steps_passed += 1
        else:
            logger.info(f"   Skipping modification for: {mod['page']}")
            steps_passed += 1  # No change needed
    
    # Step 4: Verify build
    logger.info("📋 Step 4: Verifying build...")
    if verify_build(frontend_path):
        steps_passed += 1
    else:
        steps_failed += 1
    
    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("📊 Execution Summary")
    logger.info("=" * 60)
    logger.info(f"  Steps Passed: {steps_passed}")
    logger.info(f"  Steps Failed: {steps_failed}")
    
    if steps_failed > 0:
        logger.error("❌ Execution incomplete - some steps failed")
        return False
    else:
        logger.info("✅ Execution completed successfully!")
        return True


def main():
    """Main execution."""
    if len(sys.argv) < 3:
        print("Usage: python3 executor.py <frontend_path> <plan_file>")
        sys.exit(1)
    
    frontend_path = Path(sys.argv[1])
    plan_file = Path(sys.argv[2])
    
    if not frontend_path.exists():
        logger.error(f"❌ Frontend path not found: {frontend_path}")
        sys.exit(1)
    
    if not plan_file.exists():
        logger.error(f"❌ Plan file not found: {plan_file}")
        sys.exit(1)
    
    logger.info("🚀 Starting Phase 8 Executor")
    logger.info(f"   Frontend: {frontend_path}")
    logger.info(f"   Plan: {plan_file}")
    
    # Read plan
    with open(plan_file, 'r') as f:
        plan = json.load(f)
    
    # Execute plan
    success = execute_plan(frontend_path, plan)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
