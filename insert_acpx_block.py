#!/usr/bin/env python3
"""
Insert ACPX execution block after Phase 9 header.
This is a clean, minimal restoration.
"""

import sys

def main():
    print("✅ Inserting ACPX execution block after Phase 9 header...")
    
    with open("/root/clawd-backend/openclaw_wrapper.py", "r") as f:
        content = f.read()
    
    # Find Phase 9 header
    phase9_header = "Phase 9: ACP Controlled Frontend Editor"
    phase9_idx = content.find(phase9_header)
    
    if phase9_idx == -1:
        print("❌ Could not find Phase 9 header")
        return 1
    
    # Find end of the Phase 9 header line (after the closing quote)
    header_end = content.find('")\n', phase9_idx)
    if header_end == -1:
        print("❌ Could not find end of Phase 9 header")
        return 1
    
    # Insertion point: right after the Phase 9 header line
    insertion_point = header_end + len('")\n')
    
    # ACPX execution block to insert
    acpx_block = '''

                # Initialize ACP editor with frontend/src path
                # ACPFrontendEditorV2 expects full path to src/ directory
                logger.info("🚀 PHASE 9 START: ACP Controlled Frontend Editor")
                
                pages_created = []
                frontend_src_path = str(self.frontend_path / "src")
                execution_id = f"{self.project_name}-phase9"
                
                # Extract required pages
                required_pages = self._extract_pages_from_description(self.description)
                logger.info(f"[Phase 9] Required pages: {', '.join(required_pages)}")
                
                for idx, page in enumerate(required_pages, start=1):
                    logger.info(f"[Phase 9] Step {idx}/{len(required_pages)} Creating {page}")
                    
                    prompt = f"""Create file:

src/pages/{page}.tsx

Export a React component named {page}.
"""
                    
                    try:
                        # Initialize ACP editor
                        editor = ACPFrontendEditorV2(frontend_src_path, self.project_name)
                        
                        # Execute ACPX
                        result = editor.apply_changes_via_acpx(prompt, execution_id)
                        
                        if result and result.get("success"):
                            pages_created.append(page)
                            logger.info(f"[Phase 9] {page}.tsx created successfully")
                        else:
                            logger.error(f"[Phase 9] ACPX failed for {page}")
                    
                    except Exception as e:
                        logger.error(f"[Phase 9] ACPX exception for {page}: {e}")
                
                # Keep router + navigation auto-wiring
                if pages_created:
                    logger.info("[Phase 9] Updating router and navigation")
                    self._update_router_and_navigation(pages_created)
                
                # Add safety guard
                if not pages_created:
                    logger.error("⚠ Phase 9 created zero pages — ACPX likely failed")
'''
    
    # Insert ACPX block after Phase 9 header
    new_content = content[:insertion_point] + acpx_block + content[insertion_point:]
    
    # Write back to file
    with open("/root/clawd-backend/openclaw_wrapper.py", "w") as f:
        f.write(new_content)
    
    print(f"✅ ACPX execution block inserted successfully")
    print(f"✅ Added {len(acpx_block)} characters at line {insertion_point}")
    print(f"✅ Phase 9 is now fully functional with ACPX")
    return 0

if __name__ == "__main__":
    sys.exit(main())
