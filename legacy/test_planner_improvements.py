#!/usr/bin/env python3
"""
Test the improved Phase-9 planner page detection.

Tests the _build_acpx_prompt method with various descriptions.
"""

import sys
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# Import the ACP Frontend Editor V2
sys.path.insert(0, '/root/clawd-backend')
from acp_frontend_editor_v2 import ACPFrontendEditorV2


def test_planner(description: str, project_name: str = "TestProject"):
    """Test planner with a given description."""
    print(f"\n{'='*60}")
    print(f"Testing: {description}")
    print(f"{'='*60}\n")

    # Create test frontend directory
    test_frontend = Path("/tmp/test-frontend")
    test_frontend.mkdir(exist_ok=True)
    (test_frontend / "src").mkdir(exist_ok=True)

    # Create editor instance
    editor = ACPFrontendEditorV2(
        frontend_src_path="/tmp/test-frontend/src",
        project_name=project_name
    )

    # Build prompt (this triggers the planner logic)
    prompt = editor._build_acpx_prompt(description)

    # Extract detected pages from the prompt
    lines = prompt.split('\n')
    detected_pages = []
    for line in lines:
        if line.strip().startswith('- src/pages/'):
            page_name = line.strip().replace('- src/pages/', '').replace('.tsx', '')
            if page_name:  # Skip empty page names
                detected_pages.append(page_name)

    print(f"Detected Pages ({len(detected_pages)}):")
    for i, page in enumerate(detected_pages, 1):
        print(f"  {i}. {page}")

    return detected_pages


if __name__ == "__main__":
    # Test 1: PandaDoc explicit page list
    test_planner(
        "Complete document automation SaaS with 10 pages: Dashboard, Documents, Templates, Document Editor, Signing, Analytics, Team, Contacts, Billing, Notifications",
        "PandaDoc"
    )

    # Test 2: SaaS without explicit list
    test_planner(
        "CRM for managing customers and deals with analytics dashboard",
        "SimpleCRM"
    )

    # Test 3: E-commerce
    test_planner(
        "Online store with products, cart, checkout, and order management",
        "ShopApp"
    )

    # Test 4: Task management
    test_planner(
        "Task and project management with Kanban boards",
        "TaskMaster"
    )

    print(f"\n{'='*60}")
    print("✅ All planner tests completed")
    print(f"{'='*60}\n")
