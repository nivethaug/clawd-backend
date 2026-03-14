# DreamPilot Prompts

This folder contains all prompts used in the DreamPilot project creation flow.

---

## Overview

DreamPilot uses AI-powered prompts at various stages of the project creation pipeline. These prompts are stored as markdown files for easy maintenance, version control, and documentation.

---

## Prompt Files

| File | Purpose | Phase | Used In |
|------|---------|-------|---------|
| `01-page-inference.md` | Infer page structure from product description | Phase 3 - Step 2 | `acp_frontend_editor_v2.py` |
| `02-acpx-frontend-editor.md` | Main frontend customization prompt | Phase 3 - Step 6 | `acp_frontend_editor_v2.py` |
| `03-infrastructure-task.md` | Infrastructure provisioning tasks | Phase 1-7 | `openclaw_wrapper.py` |
| `04-ai-refinement.md` | Refine template into production app | Phase 8 (Skipped) | `openclaw_wrapper.py` |
| `05-build-fix.md` | Auto-fix build errors | Phase 6 - Build Gate | `infrastructure_manager.py` |

---

## Pipeline Flow

```
1. Page Inference (01-page-inference.md)
   ↓
2. ACPX Frontend Editor (02-acpx-frontend-editor.md)
   ↓
3. Infrastructure Tasks (03-infrastructure-task.md)
   ↓
4. Build Fix (05-build-fix.md) - if build fails
   ↓
5. Deployment Verification
```

---

## Primary Prompts

### 01-page-inference.md
- **Purpose:** Analyze product description and infer appropriate page structure
- **Input:** Product description
- **Output:** JSON list of pages: `{"pages": ["Dashboard", "Contacts", ...]}`
- **Phase:** Step 2 of ACPX workflow

### 02-acpx-frontend-editor.md
- **Purpose:** Main AI prompt for frontend customization
- **Key Features:**
  - 🚨 Fix routing FIRST (remove Welcome, add Dashboard at "/")
  - Create pages from manifest
  - Update navigation
  - Ensure build succeeds
- **Phase:** Phase 3 (ACPX Frontend Refinement)

### 03-infrastructure-task.md
- **Purpose:** Execute infrastructure provisioning phases
- **Phases:**
  - Phase 1: Analyze project
  - Phase 2: Template setup
  - Phase 4: Database provisioning
  - Phase 5: Port allocation
  - Phase 6: Service setup
  - Phase 7: Nginx routing
- **Loads rules from:** `RULES_DIR` environment variable

### 04-ai-refinement.md
- **Status:** ⚠️ Currently skipped
- **Purpose:** Legacy AI refinement (replaced by ACPX in Phase 3)
- **Note:** Prompt exists but is not used in current pipeline

### 05-build-fix.md
- **Purpose:** Auto-fix build errors after frontend changes
- **Triggers:** When `npm run build` fails
- **Fixes:** TypeScript errors, missing imports, type mismatches, JSX syntax

---

## Prompt Architecture

### Template Variables

Prompts use Python f-string variables:

```python
prompt = f"""Project Name: {project_name}
Description: {goal_description}
"""
```

### Dynamic Sections

Some prompts include dynamic sections:
- Page lists: `{required_pages_str}`
- Error output: `{build_error}`
- Rules context: `{rules_context}`

### Loading in Code

Prompts are currently embedded in Python files. Future improvement:
- Load from markdown files
- Template engine for variable substitution
- Version control for prompt changes

---

## Editing Prompts

When editing prompts:

1. **Update the markdown file** in `prompts/` folder
2. **Update the Python code** that generates the prompt
3. **Test thoroughly** with new projects
4. **Commit both** markdown and Python changes

---

## Best Practices

### Prompt Engineering

1. **Be explicit** - AI follows instructions literally
2. **Use examples** - Show before/after states
3. **Prioritize tasks** - "DO THIS FIRST"
4. **Add constraints** - "DO NOT" sections
5. **Provide format** - Show expected output format

### Routing Fix Priority

The most critical instruction in `02-acpx-frontend-editor.md`:

```
🚨🚨🚨 CRITICAL ROUTING FIX - MUST DO FIRST 🚨🚨🚨

1. READ src/App.tsx
2. DELETE ALL routes at path="/"
3. ADD Dashboard at path="/" inside Layout wrapper
```

This prevents the blank page issue caused by duplicate "/" routes.

---

## Future Improvements

1. **Template Engine** - Use Jinja2 for prompt templates
2. **Prompt Versioning** - Track prompt changes and A/B test
3. **Prompt Analytics** - Measure prompt effectiveness
4. **External Prompts** - Load from database or config
5. **Prompt Validation** - Verify prompts before execution

---

## Related Files

- `acp_frontend_editor_v2.py` - ACPX prompt builder
- `openclaw_wrapper.py` - Infrastructure task prompts
- `infrastructure_manager.py` - Build fix prompt
- `page_manifest.py` - Page manifest generation
- `page_specs.py` - Page specifications

---

## Documentation

For full project documentation, see:
- `.agents/skills/project-info/SKILL.md` - Complete project knowledge
- `ACP_README.md` - ACPX documentation
- `README.md` - Project overview
