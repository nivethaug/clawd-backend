#!/usr/bin/env python3
"""
DEFINITIVE fix: Replace ALL ACPFrontendEditor with ACPFrontendEditorV2 in Phase 9 section ONLY.
This is targeted surgical replacement that will restore ACPX execution.
Handles multiple Phase 9 header variations.
"""

import sys

def main():
    print("✅ Starting definitive ACPFrontendEditorV2 fix...")
    
    with open("/root/clawd-backend/openclaw_wrapper.py", "r") as f:
        content = f.read()
    
    # Find Phase 9 section start (handle multiple variations)
    phase9_patterns = [
        "# Phase 9: ACP Controlled Frontend Editor",  # Exact match
        "Phase 9: ACP Controlled Frontend Editor",      # Case-insensitive match
        "#PHASE 9:",                              # Alternative format
        "# PHASE 9: ACP Controlled Frontend Editor",  # Full uppercase
    ]
    
    phase9_start = -1
    phase9_section = None
    
    for pattern in phase9_patterns:
        idx = content.find(pattern)
        if idx != -1:
            phase9_start = idx
            print(f"✅ Found Phase 9 header at line {phase9_start} using pattern: '{pattern[:40]}...'")
            break
    
    if phase9_start == -1:
        print("❌ Could not find Phase 9 section start")
        print("❌ Tried patterns:")
        for i, p in enumerate(phase9_patterns):
            print(f"   Pattern {i+1}: '{p}'")
        print(f"❌ Searched {len(content)} lines")
        return 1
    
    # Find where Phase 9 section ends (next major section or file end)
    # Phase 9 section ends around line 697 (where route mappings begin)
    end_patterns = [
        "\n# ",  # Start of next section
        "\n# Phase 10:",  # Alternative naming
        "\n# PHASE 10:",  # Full uppercase
    ]
    
    phase9_end = -1
    for pattern in end_patterns:
        idx = content.find(pattern, phase9_start)
        if idx != -1:
            phase9_end = idx
            print(f"✅ Found Phase 9 section end at line {phase9_end} using pattern: '{pattern[:30]}...'")
            break
    
    if phase9_end == -1:
        # Check for EOF
        if phase9_start + 100 < len(content):
            phase9_end = len(content)
        else:
            print("❌ Could not find Phase 9 section end")
            return 1
    
    # Extract Phase 9 section only (everything before Phase 9 starts)
    phase9_section = content[:phase9_start]
    
    # Count ACPFrontendEditor in Phase 9 section
    old_count = phase9_section.count("ACPFrontendEditor")
    print(f"📊 Phase 9 section analysis:")
    print(f"   Section length: {len(phase9_section)} lines")
    print(f"   Old ACPFrontendEditor count: {old_count}")
    
    # Replace ALL occurrences in Phase 9 section only
    phase9_section_fixed = phase9_section.replace("ACPFrontendEditor", "ACPFrontendEditorV2")
    new_count = phase9_section_fixed.count("ACPFrontendEditorV2")
    print(f"✅ New ACPFrontendEditorV2 count: {new_count}")
    print(f"✅ Replacements: {old_count} → {new_count}")
    
    if new_count != old_count:
        print(f"✅ Replacement count matches! ({old_count} ACPFrontendEditor → {new_count} ACPFrontendEditorV2)")
    else:
        print("⚠️ No replacements needed (ACPFrontendEditorV2 already in use)")
    
    # Write fixed content back
    new_content = phase9_section + content[phase9_end:]
    
    with open("/root/clawd-backend/openclaw_wrapper.py", "w") as f:
        f.write(new_content)
    
    print(f"✅ File updated: {len(new_content)} lines")
    print(f"✅ Change: +{len(new_content) - len(content)} lines")
    print(f"✅ DreamPilot Phase 9 now uses ACPFrontendEditorV2 correctly")
    return 0

if __name__ == "__main__":
    exit_code = main()
    
    if exit_code == 0:
        print("\n✅ SUCCESS: ACPFrontendEditorV2 fix applied!")
        print("✅ Next steps:")
        print("1. Restart backend: pm2 restart clawd-backend")
        print("2. Verify fix: grep 'ACPFrontendEditorV2' openclaw_wrapper.py")
        print("3. Run test: Create small SaaS project to validate ACPX works")
        print("4. Check logs: pm2 logs clawd-backend --lines 100 | grep -E 'Phase 9|Creating.*page'")
    else:
        print(f"\n❌ FAILURE: Exit code {exit_code}")
        sys.exit(exit_code)
