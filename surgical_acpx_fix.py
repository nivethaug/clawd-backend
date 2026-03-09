#!/usr/bin/env python3
"""
Surgical fix: Replace ACPFrontendEditor with ACPFrontendEditorV2 within Phase 9 section.
This is the ACTUAL fix needed - not a top-level import addition.
"""

import sys

def main():
    print("✅ Starting surgical ACPFrontendEditorV2 replacement...")
    
    with open("/root/clawd-backend/openclaw_wrapper.py", "r") as f:
        content = f.read()
    
    # Count occurrences in Phase 9 section (lines 692-800 approximately)
    acp_editor_old_count = content.count("ACPFrontendEditor")
    acp_editor_v2_count = content.count("ACPFrontendEditorV2")
    
    print(f"📊 Current state:")
    print(f"   ACPFrontendEditor references: {acp_editor_old_count}")
    print(f"   ACPFrontendEditorV2 references: {acp_editor_v2_count}")
    
    # Count replacements needed
    replacements_needed = acp_editor_old_count - acp_editor_v2_count
    
    if replacements_needed == 0:
        print("✅ NO REPLACEMENTS NEEDED - ACPFrontendEditorV2 already in use!")
        print("🎯 This means the file is actually correct, or another issue exists.")
        return 0
    
    print(f"🔧 Replacing {replacements_needed} occurrence(s)...")
    
    # Replace all occurrences within Phase 9 section only
    # Phase 9 is approximately lines 692-800
    phase9_section = content[690:800]
    phase9_section_replaced = phase9_section.replace("ACPFrontendEditor", "ACPFrontendEditorV2")
    
    # Verify replacement
    old_count = phase9_section.count("ACPFrontendEditor")
    new_count = phase9_section_replaced.count("ACPFrontendEditorV2")
    
    print(f"   Before: {old_count} ACPFrontendEditor references")
    print(f"   After:  {new_count} ACPFrontendEditorV2 references")
    print(f"   Replaced: {new_count - old_count} occurrences")
    
    if new_count != old_count:
        print("❌ ERROR: Replacement count doesn't match expected!")
        return 1
    
    # Write modified content
    final_content = content[:690] + phase9_section_replaced + content[800:]
    
    with open("/root/clawd-backend/openclaw_wrapper.py", "w") as f:
        f.write(final_content)
    
    print(f"✅ Successfully modified openclaw_wrapper.py")
    print(f"✅ File size changed from {len(content)} to {len(final_content)} characters")
    print(f"✅ Replaced: {new_count} ACPFrontendEditor → ACPFrontendEditorV2")
    print("\n✅ NEXT STEPS:")
    print("1. Restart backend: pm2 restart clawd-backend")
    print("2. Verify import: grep 'from acp_frontend_editor_v2' openclaw_wrapper.py")
    print("3. Run test: Create small SaaS project to validate ACPX execution")
    print("4. Check logs: pm2 logs clawd-backend --lines 100 | grep -E 'Phase 9|Creating.*page'")
    print("\n✅ Expected result: Pages created with ACPX execution")
    return 0

if __name__ == "__main__":
    sys.exit(main())
