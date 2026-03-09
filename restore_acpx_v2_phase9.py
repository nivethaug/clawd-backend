#!/usr/bin/env python3
"""
Simple script to restore ACPX V2 execution block in openclaw_wrapper.py.
This replaces the broken Phase 9 section with the complete ACPX V2 logic.
"""

import sys

def restore_phase9_acpx():
    """Restore complete ACPX V2 execution block."""
    print("✅ Starting ACPX V2 restoration...")
    
    # Read main file
    with open("/root/clawd-backend/openclaw_wrapper.py", "r") as f:
        content = f.read()
    
    # Find Phase 9 section
    phase9_start = content.find("# Phase 9: ACP Controlled Frontend Editor")
    if phase9_start == -1:
        print("❌ Could not find Phase 9 section")
        return False
    
    # Find where Phase 9 section ends (next major section)
    phase9_end = content.find("\n    4.", 0, phase9_start + 100)
    if phase9_end == -1:
        print("❌ Could not find end of Phase 9 section")
        return False
    
    # Extract content before and after Phase 9 section
    before_phase9 = content[:phase9_start]
    after_phase9 = content[phase9_end:]
    
    # Read restore file (complete ACPX V2 logic)
    with open("/root/clawd-backend/openclaw_wrapper_phase9_acpx_restore.py", "r") as f:
        restore_content = f.read()
    
    # Skip docstring and imports at the top
    restore_start = restore_content.find("logger.info(f\"[ACPX-V2] 🔴 HEARTBEAT: Starting ACPX V2 execution\")")
    if restore_start == -1:
        print("❌ Could not find restore start marker")
        return False
    
    restore_end = restore_content.find("logger.info(f\"[Phase 9]   Success: result.get('success')}\")", restore_start)
    if restore_end == -1:
        # Find a good end point - try multiple patterns
        pattern_end = restore_content.find("except Exception as e:", restore_start)
        if pattern_end == -1:
            # Find another pattern
            pattern_end2 = restore_content.find("logger.error(f\"[Phase 9]   Exception message:", restore_start)
            if pattern_end2 != -1:
                restore_end = pattern_end2
            else:
                print("❌ Could not find restore end marker")
                return False
        else:
            restore_end = pattern_end
    if restore_end == -1:
        print("❌ Could not find restore end marker")
        return False
    
    # Extract restore content (excluding docstring/imports)
    restore_body = restore_content[restore_start+180:restore_end]
    
    # Construct new content
    new_content = before_phase9 + "\n" + restore_body + after_phase9
    
    # Write new file
    with open("/root/clawd-backend/openclaw_wrapper.py", "w") as f:
        f.write(new_content)
    
    print(f"✅ Successfully merged ACPX V2 restoration")
    print(f"✅ Replaced {len(restore_body)} characters")
    print(f"✅ Total file size: {len(new_content)} lines")
    return True

if __name__ == "__main__":
    if restore_phase9_acpx():
        print("\n✅ ACPX V2 execution block has been restored!")
        print("✅ Ready to restart backend and test!")
    else:
        print("\n❌ Restoration failed")
        sys.exit(1)
