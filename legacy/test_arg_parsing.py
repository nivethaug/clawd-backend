#!/usr/bin/env python3
"""
Test the argument parsing fix in openclaw_wrapper.py
"""
import sys

# Simulate the command line arguments that would be passed
# This is what subprocess.run() would pass
test_argv = [
    "openclaw_wrapper.py",
    "536",
    "/root/dreampilot/projects/website/536_PandaDoc Final Test_20260309_175748",
    "PandaDoc Final Test",
    "Complete document automation SaaS with 10 pages: Dashboard, Documents, Templates, Document Editor, Signing, Analytics, Team, Contacts, Billing, Notifications",
    "saas"
]

sys.argv = test_argv

# Now apply the fix
project_id = int(sys.argv[1])
project_path = sys.argv[2]
project_name = sys.argv[3]

# Fixed argument parsing
description = " ".join(sys.argv[4:-1]) if len(sys.argv) > 4 else None
template_id = sys.argv[-1] if len(sys.argv) > 4 else None

print("="*60)
print("Argument Parsing Test Results")
print("="*60)
print(f"project_id: {project_id}")
print(f"project_path: {project_path}")
print(f"project_name: {project_name}")
print(f"description: {description}")
print(f"template_id: {template_id}")
print("="*60)

# Validate
expected_desc = "Complete document automation SaaS with 10 pages: Dashboard, Documents, Templates, Document Editor, Signing, Analytics, Team, Contacts, Billing, Notifications"
expected_template = "saas"

print("\nValidation:")
if description == expected_desc:
    print("✅ Description: CORRECT")
else:
    print(f"❌ Description: INCORRECT")
    print(f"   Expected: {expected_desc}")
    print(f"   Got: {description}")

if template_id == expected_template:
    print("✅ Template ID: CORRECT")
else:
    print(f"❌ Template ID: INCORRECT")
    print(f"   Expected: {expected_template}")
    print(f"   Got: {template_id}")

print("\n" + "="*60)
