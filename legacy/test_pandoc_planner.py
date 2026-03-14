#!/usr/bin/env python3
"""
Quick test for PandaDoc page detection validation.
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


# Test: PandaDoc explicit page list
description = "Complete document automation SaaS with 10 pages: Dashboard, Documents, Templates, Document Editor, Signing, Analytics, Team, Contacts, Billing, Notifications"

print(f"{'='*60}")
print(f"Testing: PandaDoc Page Detection")
print(f"{'='*60}")
print(f"Description: {description}\n")

# Create test frontend directory
test_frontend = Path("/tmp/test-frontend")
test_frontend.mkdir(exist_ok=True)
(test_frontend / "src").mkdir(exist_ok=True)

# Create editor instance
editor = ACPFrontendEditorV2(
    frontend_src_path="/tmp/test-frontend/src",
    project_name="PandaDoc"
)

# Build prompt (this triggers the planner logic)
prompt = editor._build_acpx_prompt(description)

# Extract detected pages from the prompt
lines = prompt.split('\n')
detected_pages = []
for line in lines:
    if line.strip().startswith('- src/pages/'):
        page_name = line.strip().replace('- src/pages/', '').replace('.tsx', '')
        if page_name:
            detected_pages.append(page_name)

print(f"\n✅ Detected Pages ({len(detected_pages)}):")
for i, page in enumerate(detected_pages, 1):
    print(f"  {i}. {page}")

# Expected pages
expected_pages = [
    "Dashboard", "Documents", "Templates", "DocumentEditor",
    "Signing", "Analytics", "Team", "Contacts", "Billing", "Notifications"
]

# Validation
print(f"\n{'='*60}")
if set(detected_pages) == set(expected_pages):
    print("✅ VALIDATION PASSED - All expected pages detected!")
    print(f"   Expected: {expected_pages}")
    print(f"   Detected: {detected_pages}")
else:
    print("❌ VALIDATION FAILED - Mismatch detected")
    missing = set(expected_pages) - set(detected_pages)
    extra = set(detected_pages) - set(expected_pages)
    if missing:
        print(f"   Missing: {missing}")
    if extra:
        print(f"   Extra: {extra}")
print(f"{'='*60}\n")
