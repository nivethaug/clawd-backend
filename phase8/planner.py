#!/usr/bin/env python3
"""
Phase 8 Planner - Generates structured JSON execution plan.

Does NOT touch filesystem. Returns ONLY valid JSON.
"""

import json
import logging
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# Template pages available for each type
TEMPLATE_PAGES = {
    "social_media": ["Dashboard", "Login", "Signup", "Settings", "Profile"],
    "ecommerce": ["Home", "Products", "Cart", "Checkout", "Orders", "Account"],
    "crm": ["Dashboard", "Deals", "Contacts", "Pipeline", "Tasks"],
    "blog": ["Home", "Articles", "Article", "Categories", "Tags"],
    "saas": ["Dashboard", "Users", "Settings", "Billing", "Reports"]
}

# Core pages that CANNOT be deleted
CORE_REQUIRED_PAGES = ["Dashboard", "NotFound"]

# Protected paths that AI CANNOT modify
PROTECTED_PATHS = [
    "src/components/ui/",
    "src/lib/",
    "src/hooks/",
    "src/config/",
    "src/styles/",
    "node_modules/",
    ".git/",
    "package.json",
    "tsconfig.json",
    "tailwind.config.ts",
    "vite.config.ts"
]


def analyze_project_type(description: str) -> str:
    """Analyze project description to identify type."""
    desc_lower = description.lower()
    if any(k in desc_lower for k in ['ecommerce', 'e-commerce', 'store', 'shop', 'product', 'cart', 'checkout', 'payment', 'online store', 'selling products']):
        return 'ecommerce'
    elif any(k in desc_lower for k in ['task', 'kanban', 'todo', 'project management', 'workflow']):
        return "task_management"
    elif any(k in desc_lower for k in ['social', 'social media', 'socialmedia', 'social manager', 'socialmedia manager', 'instagram', 'twitter', 'facebook', 'linkedin', 'scheduler']):
        return "social_media"
    elif any(k in desc_lower for k in ['blog', 'content', 'article', 'publication']):
        return "blog"
    else:
        return "saas"


def generate_phase8_plan(
    frontend_path: Path,
    template_id: str,
    project_name: str,
    project_description: str,
    template_category: str
) -> dict:
    """Generate structured JSON plan for Phase 8 execution."""
    # Scan existing structure
    pages_dir = frontend_path / "src" / "pages"
    existing_pages = []
    if pages_dir.exists():
        for file in pages_dir.iterdir():
            if file.is_file() and file.suffix == '.tsx':
                existing_pages.append(file.stem)
    
    logger.info(f"📋 Existing pages: {', '.join(existing_pages) if existing_pages else '(none)'}")
    
    # Get template pages
    template_pages = TEMPLATE_PAGES.get(template_id, [])
    
    # Build plan
    plan = {
        "template_id": template_id,
        "template_category": template_category,
        "project_name": project_name,
        "project_description": project_description,
        "existing_pages": existing_pages,
        "available_template_pages": template_pages,
        "keep_pages": [],
        "remove_pages": [],
        "add_pages": [],
        "modifications": [],
        "root_route": None,
        "strategy": {}
    }
    
    # Default strategy: keep existing if they match template
    plan["keep_pages"] = existing_pages.copy()
    
    # Analysis based on template type
    if template_id == "social_media":
        plan["strategy"] = {
            "total_pages_kept": len(existing_pages),
            "total_pages_added": 0,
            "total_pages_removed": 0,
            "total_modifications": 0,
            "reasoning": f"Keeping all existing pages ({len(existing_pages)}) as social media template selected. Current pages match social media requirements."
        }
        
        # Check if Dashboard exists
        if "Dashboard" in existing_pages:
            plan["root_route"] = "/dashboard"
            plan["modifications"].append({
                "page": "App.tsx",
                "instruction": "Ensure root route '/' points to Dashboard for social media projects. Add import for Dashboard if missing."
            })
        else:
            # Dashboard should be added as new page
            plan["add_pages"].append({
                "name": "Dashboard",
                "route": "/dashboard",
                "purpose": "Social media dashboard with posts, scheduler, and analytics",
                "create_from_template": True
            })
            plan["root_route"] = "/dashboard"
    
    return plan


def main():
    """Main execution."""
    if len(sys.argv) < 8:
        print("Usage: python3 planner.py <frontend_path> <template_id> <project_name> <project_description> <template_category>")
        print()
        print("Arguments:")
        print("  frontend_path      - Path to frontend directory")
        print("  template_id        - Selected template ID")
        print("  project_name       - Name of project")
        print("  project_description - Project description for planning")
        print("  template_category   - Template category (social_media, ecommerce, crm, blog, saas)")
        sys.exit(1)
    
    frontend_path = Path(sys.argv[1])
    template_id = sys.argv[2]
    project_name = sys.argv[3]
    project_description = sys.argv[4] if len(sys.argv) > 4 else ""
    template_category = sys.argv[5] if len(sys.argv) > 5 else "saas"
    
    # Validate inputs
    if not frontend_path.exists():
        logger.error(f"❌ Frontend path not found: {frontend_path}")
        sys.exit(1)
    
    logger.info("🚀 Starting Phase 8 Planner")
    logger.info(f"   Template: {template_id} ({template_category})")
    logger.info(f"   Project: {project_name}")
    logger.info(f"   Description: {project_description[:100]}...")
    
    # Generate plan
    plan = generate_phase8_plan(
        frontend_path,
        template_id,
        project_name,
        project_description,
        template_category
    )
    
    # Output plan as JSON
    logger.info("✅ Phase 8 planning completed!")
    logger.info(f"   Pages to keep: {len(plan['keep_pages'])}")
    logger.info(f"   Pages to add: {len(plan['add_pages'])}")
    logger.info(f"   Pages to remove: {len(plan['remove_pages'])}")
    logger.info(f"   Modifications: {len(plan['modifications'])}")
    logger.info(f"   Root route: {plan['root_route'] or '/'}")
    
    # Print to stdout for OpenClaw to capture
    print(json.dumps(plan, indent=2))
    
    sys.exit(0)


if __name__ == "__main__":
    main()
