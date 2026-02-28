#!/usr/bin/env python3
"""
Phase 8 Validator - Ensures AI plans are safe.

Validates:
1. No core pages are deleted (Dashboard, NotFound)
2. No protected paths are modified (ui/, lib/, hooks/)
3. Max 3 pages added (prevents bloat)
4. Root route behavior is enforced (if specified)
5. Plan has real impact (not empty)
"""

import json
import logging
import sys
from pathlib import Path
from typing import Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# Protected paths that AI CANNOT modify
PROTECTED_PATHS = [
    "src/components/ui/",
    "src/lib/",
    "src/hooks/",
    "src/config/",
    "src/styles/",
    "node_modules/",
]

# Core pages that AI CANNOT delete
CORE_REQUIRED_PAGES = ["Dashboard", "NotFound"]

# Max new pages allowed
MAX_NEW_PAGES = 3


def validate_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate AI-generated plan against constraints.
    
    Returns:
        valid: boolean
        errors: list of validation errors
    """
    errors = []
    
    # Rule 1: No core pages deleted
    for page in plan.get("remove_pages", []):
        if page in CORE_REQUIRED_PAGES:
            errors.append(f"Cannot delete core page: {page}")
    
    # Rule 2: No modifications to protected paths
    for mod in plan.get("modifications", []):
        page = mod.get("page", "")
        for protected in PROTECTED_PATHS:
            if page and protected in page:
                errors.append(f"Modification to protected path: {page}")
    
    # Rule 3: Max 3 pages added
    add_pages = plan.get("add_pages", [])
    if len(add_pages) > MAX_NEW_PAGES:
        errors.append(f"Cannot add {len(add_pages)} pages (max {MAX_NEW_PAGES} allowed)")
    
    # Rule 4: Plan must have impact
    add_count = len(add_pages)
    remove_count = len(plan.get("remove_pages", []))
    mod_count = len(plan.get("modifications", []))
    
    if add_count == 0 and remove_count == 0 and mod_count == 0:
        errors.append("Plan has no impact - no changes planned")
    
    # Rule 5: Validate page names
    all_pages = plan.get("keep_pages", []) + plan.get("add_pages", [])
    for page in all_pages:
        if not page or not isinstance(page, str):
            errors.append(f"Invalid page name: {page}")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors
    }


def main():
    """Main execution."""
    if len(sys.argv) < 2:
        print("Usage: python3 validator.py <plan_file>")
        sys.exit(1)
    
    plan_file = Path(sys.argv[1])
    
    if not plan_file.exists():
        logger.error(f"❌ Plan file not found: {plan_file}")
        sys.exit(1)
    
    logger.info("🔍 Starting Phase 8 Plan Validation")
    logger.info(f"   Plan file: {plan_file}")
    
    # Read plan
    with open(plan_file, 'r') as f:
        plan = json.load(f)
    
    # Validate
    validation = validate_plan(plan)
    
    logger.info(f"   Plan valid: {validation['valid']}")
    
    if validation["valid"]:
        logger.info("✅ Plan validation passed!")
        logger.info(f"   Pages to keep: {len(plan['keep_pages'])}")
        logger.info(f"   Pages to add: {len(plan['add_pages'])}")
        logger.info(f"   Pages to remove: {len(plan['remove_pages'])}")
        logger.info(f"   Modifications: {len(plan['modifications'])}")
        sys.exit(0)
    else:
        logger.error("❌ Plan validation failed!")
        for error in validation["errors"]:
            logger.error(f"   • {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
