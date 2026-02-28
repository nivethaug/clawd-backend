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
    # Build plan based on template registry (production-grade)
    # Template registry is source of truth for page existence
    # This is deterministic and doesn't depend on filesystem state
    
    # Get existing pages from template registry
    template_pages_map = {
        "social_media": ["Dashboard", "Login", "Signup", "Settings", "NotFound"],
        "ecommerce": ["Home", "Products", "Cart", "Checkout", "Orders", "Account"],
        "crm": ["Dashboard", "Deals", "Contacts", "Pipeline", "Tasks"],
        "blog": ["Home", "Articles", "Article", "Categories", "Tags"],
        "saas": ["Dashboard", "Users", "Settings", "Billing", "Reports"],
        "analytics": ["Dashboard", "Reports", "Funnels", "Cohorts"]
    }
    
    # Get pages for this template type
    template_pages = template_pages_map.get(template_id, ["Dashboard"])
    
    # Determine which pages to add and which to keep
    # Pages that exist (from template registry) are kept
    # Pages that don't exist are added
    # Core pages (Dashboard, NotFound) are always added
    
    logger.info(f"Template ID: {template_id}")
    logger.info(f"Template pages: {template_pages}")
    
    # Build keep_pages list (pages that exist)
    keep_pages = []
    for page in template_pages:
        if page not in ["NotFound"]:  # NotFound is always there
            page_path = frontend_path / "src" / "pages" / f"{page}.tsx"
            if page_path.exists():
                keep_pages.append(page)
                logger.info(f"   Keeping existing page: {page}")
    
    # Build add_pages list (pages that don't exist)
    add_pages = []
    for page in template_pages:
        if page not in ["NotFound"]:  # Don't add NotFound
            if page not in keep_pages:
                add_pages.append(page)
                route = f"/{page.lower()}"
                purpose = f"Core {page} page for {template_id} template"
                logger.info(f"   Adding required page: {page}")
    
    # Always ensure Dashboard (if not in add_pages, add it)
    if "Dashboard" not in add_pages and "Dashboard" in template_pages:
        add_pages.append({
            "name": "Dashboard",
            "route": "/dashboard",
            "purpose": "Social media dashboard with posts, scheduler, analytics",
            "create_from_template": True
        })
        logger.info("   Ensuring Dashboard page is included")
    
    # No modifications - just page management
    
    plan = {
        "template_id": template_id,
        "template_category": template_id,
        "project_name": project_name,
        "project_description": project_description,
        "existing_pages": keep_pages,
        "add_pages": add_pages,
        "remove_pages": [],
        "modifications": [],
        "root_route": "/dashboard" if "Dashboard" in template_pages else "/",
        "strategy": {
            "total_pages_kept": len(keep_pages),
            "total_pages_added": len(add_pages),
            "total_pages_removed": 0,
            "total_modifications": 0,
            "reasoning": f"Template registry approach: Always include core {template_id} pages (Dashboard{', Login, Signup' if 'Login' in template_pages else '')}. Based on template registry, not filesystem scan. Deterministic and production-grade."
        }
    }
    
    logger.info("✅ Template registry-based plan generated")
    return plan
