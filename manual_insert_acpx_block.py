#!/usr/bin/env python3
"""
Very simple script to manually insert ACPX V2 execution block.
"""
import sys

def main():
    print("✅ Manually inserting ACPX V2 execution block...")
    
    # Read current file
    with open("/root/clawd-backend/openclaw_wrapper.py", "r") as f:
        content = f.read()
    
    # Define what to insert (the complete ACPX V2 logic)
    acpx_block = '''
                # Initialize ACP editor with frontend/src path
                # ACPFrontendEditorV2 expects full path to src/ directory
                logger.debug(f"[Phase 9] Preparing frontend_src_path: {frontend_src_path}")
                logger.debug(f"[Phase 9] Type: {type(frontend_src_path)}")

                # Force str conversion early to avoid path issues
                frontend_src_path = str(frontend_src_path).rstrip("/")


                if not os.path.exists(frontend_src_path):
                    logger.debug(f"[Phase 9] ❌ Frontend src path does NOT exist: {frontend_src_path}")

                # Phase 9: ACP Frontend Editor (Filesystem Diffing Architecture)
                logger.info("📋 Phase 9/8: ACP Controlled Frontend Editor (Integrated)")

                try:
                    # Initialize ACP editor with frontend/src path
                    # ACPFrontendEditorV2 expects full path to src/ directory
                    editor = ACPFrontendEditorV2(frontend_src_path, self.project_name)
                    logger.info("✓ ACP Frontend Editor V2 initialized")

                    # Generate execution ID
                    import uuid
                    execution_id = f"acp_{uuid.uuid4().hex[:12]}"
                    logger.info(f"🎯 ACPX Execution ID: {execution_id}")

                    # STEP 1: Extracting required pages from description
                    logger.info("🔍 Step 1: Extracting required pages from description")
                    required_pages = self._extract_pages_from_description(self.description)
                    logger.info(f"[Phase 9] Required pages: {', '.join(required_pages)}")

                    # STEP 2: Execute each page as separate AI call (step-by-step execution)
                    logger.info("🚀 Step 2: Executing pages step-by-step (Lovable/Bolt architecture)")

                    step_results = []
                    pages_succeeded = []
                    pages_failed = []

                    for idx, page in enumerate(required_pages, start=1):
                        page_num = idx + 1
                        step_name = f"Create {page} page"
                        step_prompt = f"""
Create a {page} page for this React + Vite + TypeScript application.

PROJECT: {self.project_name}
DESCRIPTION: {self.description}

PAGE SPECIFICS:
- File: src/pages/{page}.tsx
- Follow existing layout and UI component patterns
- Use appropriate UI components from src/components/ui/

Make it production-ready.
Do NOT modify unrelated files.
Only create or modify files necessary for this page.
"""

                        logger.info(f"[Phase 9] Step {page_num}/{len(required_pages)}: Creating {page} page...")

                        try:
                            # Run ACPX V2 for this single page
                            from acp_frontend_editor_v2 import ACPFrontendEditorV2

                            editor = ACPFrontendEditorV2(frontend_src_path, self.project_name)
                            logger.info(f"[Phase 9]   ACPX V2 Editor initialized for page: {page}")

                            # Call apply_changes_via_acpx
                            page_result = editor.apply_changes_via_acpx(step_prompt, execution_id)

                            if page_result.get("success"):
                                pages_succeeded.append(page)
                                step_results.append(f"✓ {page} created")
                                logger.info(f"[Phase 9] Step {page_num} ✓: {page} page created successfully")
                            else:
                                pages_failed.append(page)
                                step_results.append(f"✗ {page} failed: {page_result.get('message', 'Unknown error')}")
                                logger.error(f"[Phase 9] Step {page_num} ✗: {page} page failed")

                        except Exception as e:
                            pages_failed.append(page)
                            step_results.append(f"✗ {page} exception: {str(e)}")
                            logger.error(f"[Phase 9] Step {page_num} ✗ Exception creating {page}: {e}")
'''
    
    # Define where to insert (find line with "# Phase 9: ACP Controlled Frontend Editor")
    insertion_marker = "# Phase 9: ACP Controlled Frontend Editor"
    
    # Find insertion point
    insertion_index = content.find(insertion_marker)
    if insertion_index == -1:
        print("❌ Could not find insertion marker")
        return 1
    
    # Find end of section to replace (look for next major section or file end)
    # Search for next section start or file end
    section_end = content.find("\n# ", insertion_index + 2)  # Start of next section
    if section_end == -1:
        # Check for EOF
        if insertion_index + 100 < len(content):
            section_end = len(content)
        else:
            print("❌ Could not find section end")
            return 1
    
    # Construct new content
    new_content = content[:insertion_index] + acpx_block + "\n\n" + content[section_end:]
    
    # Write new file
    with open("/root/clawd-backend/openclaw_wrapper.py", "w") as f:
        f.write(new_content)
    
    print(f"✅ Successfully inserted ACPX V2 execution block")
    print(f"✅ Added {len(acpx_block)} characters at position {insertion_index}")
    print(f"✅ New file size: {len(new_content)} characters")
    return 0

if __name__ == "__main__":
    sys.exit(main())
