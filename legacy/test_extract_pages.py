#!/usr/bin/env python3
"""
Test the _extract_required_pages_from_prompt method.

Tests the new extracted page detection logic.
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


def test_extract_pages(description: str, project_name: str = "TestProject"):
    """Test _extract_required_pages_from_prompt with a given description."""
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

    # Extract pages (this triggers the new method)
    detected_pages = editor._extract_required_pages_from_prompt(description)

    print(f"Detected Pages ({len(detected_pages)}):")
    for i, page in enumerate(detected_pages, 1):
        print(f"  {i}. {page}")

    return detected_pages


if __name__ == "__main__":
    # Test 1: PandaDoc explicit page list
    test_extract_pages(
        "Complete document automation SaaS with 10 pages: Dashboard, Documents, Templates, Document Editor, Signing, Analytics, Team, Contacts, Billing, Notifications",
        "PandaDoc"
    )

    # Test 2: SaaS without explicit list
    test_extract_pages(
        "CRM for managing customers and deals with analytics dashboard",
        "SimpleCRM"
    )

    # Test 3: E-commerce
    test_extract_pages(
        "Online store with products, cart, checkout, and order management",
        "ShopApp"
    )

    # Test 4: Task management
    test_extract_pages(
        "Task and project management with Kanban boards",
        "TaskMaster"
    )

    print(f"\n{'='*60}")
    print("✅ All _extract_required_pages_from_prompt tests passed!")
    print(f"{'='*60}\n")
