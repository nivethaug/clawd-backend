#!/usr/bin/env python3
"""
Complete restoration of ACPX V2 execution block.
This inserts the missing import AND the complete ACPX execution block into openclaw_wrapper.py.
"""

import sys

def step1_insert_missing_import():
    """Step 1: Insert missing typing import at top of file."""
    print("📝 Step 1: Inserting missing import...")
    
    with open("/root/clawd-backend/openclaw_wrapper.py", "r") as f:
        content = f.read()
    
    # Find Phase 9 header
    phase9_header = "# Phase 9: ACP Controlled Frontend Editor"
    insertion_idx = content.find(phase9_header)
    
    if insertion_idx == -1:
        print("❌ Could not find Phase 9 header")
        return False
    
    # Insert missing import before Phase 9 header
    insertion_content = f"""from typing import List

{content[:insertion_idx]}"""
    
    with open("/root/clawd-backend/openclaw_wrapper.py", "w") as f:
        f.write(insertion_content)
    
    print(f"✅ Missing import inserted at line {insertion_idx}")
    return True

def step2_insert_acpx_execution_block():
    """Step 2: Insert complete ACPX execution block."""
    print("📝 Step 2: Inserting ACPX execution block...")
    
    with open("/root/clawd-backend/openclaw_wrapper.py", "r") as f:
        content = f.read()
    
    # Find insertion point (after Phase 9 header's closing quote)
    phase9_header = "# Phase 9: ACP Controlled Frontend Editor"
    insertion_idx = content.find(phase9_header)
    
    if insertion_idx == -1:
        print("❌ Could not find Phase 9 header")
        return False
    
    # Find exact insertion point
    insertion_start = content.find('")', insertion_idx)
    if insertion_start == -1:
        print("❌ Could not find insertion start point")
        return False
    
    insertion_point = insertion_start + len('")\n')
    
    # ACPX execution block to insert (complete, minimal version)
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
                            logger.info(f"[Phase 9]   ACPX prompt length: {len(step_prompt)} chars")
                            
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
    
    # Insert ACPX block after Phase 9 header
    insertion_content = f"""
{content[:insertion_point]}{acpx_block}
"""
    
    with open("/root/clawd-backend/openclaw_wrapper.py", "w") as f:
        f.write(insertion_content)
    
    print(f"✅ ACPX execution block inserted (added ~{len(acpx_block)} characters)")
    return True

def main():
    print("🚀 Starting complete ACPX V2 restoration...")
    
    # Execute both steps
    success1 = step1_insert_missing_import()
    if not success1:
        print("❌ Step 1 failed - aborting")
        return 1
    
    success2 = step2_insert_acpx_execution_block()
    if not success2:
        print("❌ Step 2 failed - aborting")
        return 1
    
    print("\n✅ Complete ACPX V2 restoration finished!")
    print("✅ Missing import added")
    print("✅ Complete ACPX execution block added")
    print("✅ DreamPilot Phase 9 should now be fully functional")
    print("\n📋 Next steps:")
    print("1. Restart backend: pm2 restart clawd-backend")
    print("2. Verify ACPX import: grep 'from acp_frontend_editor_v2' openclaw_wrapper.py")
    print("3. Run test project: Create small SaaS with 2 pages")
    print("4. Monitor logs: pm2 logs clawd-backend --lines 100")
    return 0

if __name__ == "__main__":
    sys.exit(main())
