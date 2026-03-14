# AI Refinement Prompt

**Purpose:** Refine cloned frontend template into production-ready application  
**Used in:** `openclaw_wrapper.py` → `_build_ai_refinement_prompt()`  
**Phase:** Phase 8 (Legacy - Currently Skipped)

---

## Prompt Template

```markdown
You are refining a cloned frontend template into a real production-ready application.

PROJECT INFORMATION:
- Project Name: {project_name}
- Project Description: {description}
- Template ID: {template_id}

YOUR TASK:

1. Analyze the current frontend structure in the frontend/ directory.
2. Understand the template's existing pages, components, and routing.
3. Remove irrelevant demo/sample content carefully and contextually.
4. Modify existing pages to match the real project intent based on project description.
5. Adjust navigation menu based on actual features implied by project description.
6. Rewrite the homepage hero section to match the project vision and branding.
7. Ensure all UI terminology reflects the project domain (e.g., "crypto" vs "e-commerce" vs "CRM").
8. Keep the build working (npm run build must succeed).
9. Do NOT break routing - all existing routes must continue to work.
10. Do NOT remove required core framework files (App.tsx, main.tsx, etc.).
11. Keep the code clean, production-ready, and well-structured.
12. Do NOT introduce placeholder or mock content unless required by the UI.
13. Preserve the overall project structure - don't reorganize the entire codebase.

IMPORTANT BEHAVIOR RULES:

- Understand the project context from project_name and description before making changes.
- Adapt pages intelligently based on what the project actually needs.
- Rename components if required to reflect project domain (e.g., "TradingTable" vs "GenericTable").
- Update routes logically if navigation changes.
- Modify layout if needed to better suit the project's use case.
- Inject meaningful, realistic content that matches the project vision.
- Keep the project minimal but real - don't add unnecessary complexity.

WHAT AI MUST NOT DO:

- Do NOT over-generate pages or features not implied by the project.
- Do NOT rewrite the entire application blindly - make targeted, intelligent changes.
- Do NOT delete core framework files or break imports.
- Do NOT break the build process.
- Do NOT modify backend files (only modify frontend/ directory).
- Do NOT modify infrastructure or deployment files.

AFTER CHANGES:

- Ensure npm run build passes.
- Do not modify any files outside the frontend/ directory.
- Keep the project structure intact.

WORKING DIRECTORY: You are currently in the project root, which contains frontend/, backend/, database/, etc.
ONLY modify files inside: frontend/

Execute the refinement now and make this template production-ready for: {project_name}
```

---

## Variables

| Variable | Description | Source |
|----------|-------------|--------|
| `{project_name}` | Project name | Project record |
| `{description}` | Project description | User input |
| `{template_id}` | Selected template ID | Template selector |

---

## Expected Behavior

1. **Analyze** - Understand existing template structure
2. **Adapt** - Modify pages to match project vision
3. **Refine** - Remove demo content, add realistic content
4. **Build** - Ensure `npm run build` succeeds

---

## Status

⚠️ **Currently Skipped** - Phase 8 is bypassed in favor of ACPX (Phase 3)

This prompt exists in the codebase but is not currently used. ACPX in Phase 3 handles all frontend refinement.

---

## File Locations

- **Prompt builder:** `openclaw_wrapper.py:1293` (`_build_ai_refinement_prompt()`)
- **Phase 8 function:** `openclaw_wrapper.py:571` (`phase_8_frontend_ai_refinement()`)
- **Execution:** Skipped in `run_all_phases()`
