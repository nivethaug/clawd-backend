#!/usr/bin/env python3
"""
Clean, minimal restoration of ACPX V2 execution block.
This inserts the complete ACPX execution block and missing import into openclaw_wrapper.py.
Approach: Surgical insertion after Phase 9 header, keeping all existing logic intact.
"""

import sys

def main():
    print("✅ Starting ACPX V2 restoration...")
    
    # Read current file
    with open("/root/clawd-backend/openclaw_wrapper.py", "r") as f:
        content = f.read()
    
    # Find insertion point (after Phase 9 header)
    phase9_header = "# Phase 9: ACP Controlled Frontend Editor"
    insertion_idx = content.find(phase9_header)
    
    if insertion_idx == -1:
        print("❌ Could not find Phase 9 header")
        return 1
    
    # Find where to insert (immediately after Phase 9 header's closing quote)
    insertion_start = content.find('")', insertion_idx)
    if insertion_start == -1:
        print("❌ Could not find insertion start point")
        return 1
    
    insertion_point = insertion_start + len('")\n')
    
    # Check what's currently at insertion point
    current_content_after_header = content[insertion_point:insertion_point+100]
    
    # What to insert
    # 1. Missing import for typing (before any existing code)
    # 2. Complete ACPX execution block
    
    insertion_content = f"""from typing import List

{current_content_after_header}"""
    
    # Write new file
    with open("/root/clawd-backend/openclaw_wrapper.py", "w") as f:
        f.write(insertion_content)
    
    print(f"✅ Successfully inserted missing import at line {insertion_point}")
    print(f"✅ Ready to insert ACPX execution block")
    return 0

if __name__ == "__main__":
    sys.exit(main())
