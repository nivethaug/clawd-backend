# Phase 9 Template Override Fix - 2026-03-11 02:30 UTC

## Problem Identified

**Template Override Issue:**

1. Template repo is cloned (e.g., flow-crm)
2. Template already has pages: `Dashboard.tsx`, `Users.tsx`, `Settings.tsx`, etc.
3. Planner detects CRM pages needed: `Dashboard`, `Leads`, `Contacts`, etc.
4. **ACPX sees template pages exist and skips creating them**
5. **ACPX may edit wrong pages (e.g., Users.tsx instead of Leads.tsx)**
6. **Or ACPX doesn't edit because it thinks pages already exist**

## Current Code Flow (WRONG)

```
fast_wrapper.py:
  ↓ Git clone template (pages already exist)
  ↓ Create backend files
  ↓ OpenClaw wrapper calls Phase 9
    ↓
  phase_9_acp_frontend_editor():
    ↓
    Step 2: Generate manifest (lists required pages)
    ↓
    Step 3: Scaffold pages (creates files like src/pages/Dashboard.tsx)
      - Creates files even if they already exist (OVERWRITE)
    ↓
    Step 4: Run ACPX (edit scaffolded files)
      - May see pages exist and skip
      - Or may edit wrong template pages
    ↓
    Step 5: Build + Deploy
```

## Root Cause Analysis

Looking at `acp_frontend_editor_v2.py` line 1315:

```python
Scans src/pages/ and removes any pages not in the allowed_pages whitelist.
```

This guardrail REMOVES template pages, but it's TOO LATE - after scaffolding!

The correct flow should be:
1. **Remove template pages FIRST** (before scaffolding)
2. **Generate manifest** (list required pages)
3. **Scaffold fresh files** (overwrite anything that remains)
4. **Run ACPX** (edit fresh scaffolded files)

## Fix Solution

### Add Step: Cleanup Template Pages Before Scaffolding

**Location:** `acp_frontend_editor_v2.py`

**Change:** Add Step 2.5 between manifest generation and scaffolding

```python
# NEW STEP (insert after line 568, before Step 3)

# Step 2.5: Cleanup template pages before scaffolding (FIX FOR TEMPLATE OVERRIDE)
try:
    print("🔴 ACPX-V2-STEP2.5: Cleaning up template pages...")
    logger.info(f"[ACPX-V2] Step 2.5: Cleaning up template pages from src/pages/...")
    
    pages_dir = self.frontend_src_path / "pages"
    
    # List all existing template pages
    existing_pages = list(pages_dir.glob("*.tsx")) if pages_dir.exists() else []
    logger.info(f"[ACPX-V2]   Found {len(existing_pages)} existing template pages")
    
    # Remove ALL template pages (whitelist filtering happens later)
    # We want clean slate for scaffolding required pages
    removed_count = 0
    for page_file in existing_pages:
        try:
            page_file.unlink()
            removed_count += 1
            logger.info(f"[ACPX-V2]   Removed template page: {page_file.name}")
        except Exception as e:
            logger.error(f"[ACPX-V2]   Failed to remove {page_file.name}: {e}")
    
    logger.info(f"[ACPX-V2]   Removed {removed_count} template pages, ready for scaffolding")
    print(f"🔴 ACPX-V2-STEP2.5-DONE: Removed {removed_count} template pages")
    
except Exception as e:
    print(f"🔴 ACPX-V2-STEP2.5-ERROR: {type(e).__name__}: {str(e)}")
    traceback.print_exc()
    return {"success": False, "message": f"Template cleanup failed: {str(e)}"}

# Then continue with existing Step 3 (Scaffolding)
```

### Why This Fixes Template Override

1. **Prevents template pages from interfering:**
   - Old Dashboard.tsx from template removed
   - Old Users.tsx from template removed
   - Old Settings.tsx from template removed
   
2. **Ensures clean slate for scaffolding:**
   - Scaffold will create fresh files
   - No ambiguity about which files to edit
   
3. **ACPX sees correct files:**
   - Will edit src/pages/Dashboard.tsx (scaffolded)
   - NOT src/pages/Dashboard.tsx (template)
   - No confusion or duplicate files

## Alternative Approach (If Above Doesn't Work)

### Use Different File Naming for Scaffold vs Template

**Current:** Both use `Dashboard.tsx`, `Leads.tsx`, etc.

**Alternative:** Scaffolded files use `DashboardPage.tsx`, `LeadsPage.tsx` (with "Page" suffix)

**Changes:**
```python
# In scaffold_pages():
page_file = self.pages_path / f"{page}Page.tsx"  # Add "Page" suffix
```

**Benefit:**
- Template pages: `Dashboard.tsx`
- Scaffolded pages: `DashboardPage.tsx`
- ACPX edits scaffolded files only (no ambiguity)

## Test Strategy

1. Implement template cleanup (Step 2.5)
2. Create CRM test project (Dashboard, Leads, Contacts, Pipeline, Tasks, Analytics, Settings)
3. Verify pages created correctly (not template pages)
4. Verify ACPX edited scaffolded files
5. Check for template override (should NOT happen)

## Success Criteria

- ✅ Template pages removed before scaffolding
- ✅ Scaffold creates fresh files (Page suffix preferred)
- ✅ ACPX edits scaffolded files (not template)
- ✅ No template override
- ✅ CRM pages implemented correctly

---

## Files to Modify

1. `/root/clawd-backend/acp_frontend_editor_v2.py`
   - Add Step 2.5: Cleanup template pages
   - Insert between manifest generation and scaffolding

2. `/root/clawd-backend/page_manifest.py` (optional)
   - Add "Page" suffix to scaffolded files
   - Change: `Dashboard.tsx` → `DashboardPage.tsx`

---

## Implementation Priority

**Option A:** Template Cleanup (PRIMARY) ✅ RECOMMENDED
- Cleanest approach
- No naming changes needed
- Removes ambiguity at source

**Option B:** File Naming Suffix (SECONDARY)
- Less invasive
- Requires changes to page_manifest.py
- May need router updates for "Page" suffix

---

**Recommendation:** Implement Option A first (template cleanup)

---

**Status:** Ready to implement fix
