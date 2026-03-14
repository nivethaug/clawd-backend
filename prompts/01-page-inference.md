# Page Inference Prompt

**Purpose:** AI infers appropriate page structure from product description  
**Used in:** `acp_frontend_editor_v2.py` → `_ai_infer_pages()`  
**Phase:** Step 2 (Page Manifest Generation)

---

## Prompt Template

```markdown
You are planning the page structure for a SaaS application.

Product description:
{goal_description}

Your task:
Return a list of 5-10 pages that would be appropriate for this application.

Rules:
1. Consider the product type (CRM, analytics, document management, etc.)
2. Think about standard SaaS pages (Dashboard, Settings, etc.)
3. Be specific with page names (not generic like "MainPage")
4. Return ONLY a JSON list of page names
5. Do NOT include explanations or extra text

Response format (JSON ONLY):
{"pages": ["Dashboard", "Contacts", "Analytics", "Settings", "Documents"]}

EXAMPLES:
CRM app → {"pages": ["Dashboard", "Contacts", "Deals", "Reports", "Tasks", "Settings"]}
Document management → {"pages": ["Dashboard", "Documents", "Templates", "Editor", "Analytics", "Settings"]}
Analytics dashboard → {"pages": ["Dashboard", "Reports", "Analytics", "Settings"]}

Provide ONLY the JSON list, nothing else.
```

---

## Variables

| Variable | Description | Source |
|----------|-------------|--------|
| `{goal_description}` | Project/product description | User input from project creation |

---

## Expected Response Format

```json
{"pages": ["Dashboard", "Contacts", "Analytics", "Settings", "Documents"]}
```

---

## Usage Context

This prompt is called during Phase 3 (ACPX Frontend Refinement) in Step 2:
- Analyzes project description
- Infers appropriate page structure
- Generates page manifest
- Creates page scaffold files

## Examples

**Input:** "Build a CRM system for managing customer relationships"

**Output:**
```json
{"pages": ["Dashboard", "Contacts", "Deals", "Reports", "Tasks", "Settings"]}
```

**Input:** "Document management system with e-signatures"

**Output:**
```json
{"pages": ["Dashboard", "Documents", "Templates", "Editor", "Signing", "Analytics", "Settings"]}
```
