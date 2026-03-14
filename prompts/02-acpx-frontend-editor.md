# ACPX Frontend Editor Prompt

**Purpose:** Main prompt for AI-powered frontend customization  
**Used in:** `acp_frontend_editor_v2.py` → `_build_acpx_prompt()`  
**Phase:** Phase 3 (ACPX Frontend Refinement)

---

## Prompt Template

```markdown
You are editing a React + Vite + TypeScript SaaS application.

Project Name: {project_name}
Project Description: {goal_description}

YOUR TASK

Transform the existing template into a production-ready application based on the project description above.

🚨🚨🚨 CRITICAL ROUTING FIX - MUST DO FIRST 🚨🚨🚨

BEFORE YOU DO ANYTHING ELSE, FIX THE ROUTING:

1. READ src/App.tsx
2. FIND the Welcome route at path="/"
3. DELETE or REPLACE it with {default_page} at path="/"

CURRENT STATE (BROKEN - causes blank page):
```tsx
<Routes>
  <Route path="/" element={<Welcome />} />           ← DELETE THIS LINE
  <Route path="/" element={<{default_page} />} />    ← DUPLICATE! Also DELETE
  <Route path="/team" element={<Team />} />
  ...
</Routes>
```

REQUIRED STATE (FIXED):
```tsx
<Routes>
  <Route element={<Layout />}>
    <Route path="/" element={<{default_page} />} />  ← ONLY ONE route at "/"
    <Route path="/team" element={<Team />} />
    ...
  </Route>
</Routes>
```

⚠️ ROUTING RULES (MANDATORY):
1. DELETE ALL routes with path="/" (there may be MULTIPLE duplicates)
2. Keep only ONE route at path="/" for {default_page}
3. All routes MUST be inside <Route element={<Layout />}> wrapper
4. If no Layout wrapper exists, ADD IT
5. DO NOT leave Welcome at path="/"
6. DO NOT create duplicate routes at path="/"

FAILURE TO FIX ROUTING = BROKEN APP (blank page)

Verify routing is correct BEFORE creating pages!

---

## PHASE 9 STRICT PAGE GENERATION RULES (ENFORCED)

⚠️  CRITICAL: EXACT PAGE CREATION REQUIRED ⚠️

1. ONLY create the pages listed below:
{required_pages_str}

2. File names must match EXACTLY:
   - Use this pattern: src/pages/{PageName}.tsx
   - Examples: src/pages/Dashboard.tsx, src/pages/Contacts.tsx, src/pages/Settings.tsx
   - DO NOT add "Page" suffix: ✗ DashboardPage.tsx → ✓ Dashboard.tsx
   - DO NOT add "Overview" suffix: ✗ AnalyticsOverview.tsx → ✓ Analytics.tsx
   - DO NOT use variations: ✗ ReportsPage.tsx → ✓ Reports.tsx

3. ABSOLUTELY FORBIDDEN:
   - DO NOT create any additional pages beyond the list
   - DO NOT create variations like: Account.tsx, Activity.tsx, Users.tsx, Team.tsx, Billing.tsx
   - DO NOT rename pages - use exact names from REQUIRED PAGES list
   - DO NOT generate default SaaS pages when explicit pages are provided

4. FINAL VERIFICATION CHECKLIST:
   Before marking task complete, verify:
   - [ ] ROUTING FIXED: Welcome route removed, {default_page} at "/" (ONLY ONE)
   - [ ] ROUTING FIXED: All routes inside Layout wrapper
   - [ ] ONLY pages from REQUIRED PAGES list exist in src/pages/
   - [ ] NO unauthorized pages were created
   - [ ] All required pages are complete
   - [ ] File names match exactly with REQUIRED PAGES list

---

## PAGE TEMPLATES

{page_templates_section}

---

## PAGE SPECIFICATIONS (Phase 4 - Enhanced UI Quality)

{page_specs_section}

---

## SCOPE LIMITATION (CRITICAL - Reduces AI scanning time)

ONLY modify files in these directories:
- src/pages/
- src/components/
- src/layout/
- src/features/

DO NOT scan:
- node_modules
- dist
- build
- .git

DO NOT modify:
- src/components/ui/ (UI primitives only)
- package.json, vite.config.*, node_modules
- backend files, .env files
- Do NOT change project architecture

---

## COMPLETION CHECKLIST

✓ ROUTING FIXED: Welcome route removed, {default_page} at "/" (ONLY ONE route)
✓ ROUTING FIXED: All routes inside <Route element={<Layout />}> wrapper
✓ All required pages created in src/pages/ (EXACT file names)
✓ All required components created in src/components/
✓ Navigation/sidebar updated
✓ Responsive design implemented
✓ Code is production-ready
✓ npm run build succeeds

---

## WORKING METHODOLOGY

You must work systematically through ALL required pages.

### STEP 0: FIX ROUTING FIRST (MANDATORY)
1. READ src/App.tsx immediately
2. DELETE ALL routes with path="/" (remove duplicates)
3. ADD {default_page} at path="/" inside Layout wrapper
4. VERIFY routing is correct before continuing

### STEP 1-N: CREATE PAGES
1. Read the project description, page templates, and page specifications carefully
2. Plan your approach using BOTH templates and specs as guidance
3. Execute step by step following page templates and specifications
4. DO NOT STOP until ALL required pages are created
5. After completing a page, move to the next page
6. Continue until the entire checklist is complete
7. Run npm run build after all pages are created

---

## EXECUTION RULES

1. FIX ROUTING FIRST - this is your FIRST task
2. Work through pages ONE AT A TIME using page templates
3. Complete each page fully before moving to the next
4. Use EXACT page names from REQUIRED PAGES list
5. Do not skip any required page
6. Do not stop early - continue until checklist is 100% complete
7. Only mark task complete when ALL checklist items are done
8. Use page templates as guidance but adapt to existing code structure

---

## TECHNICAL REQUIREMENTS

- Fix routing BEFORE creating pages
- Keep the code buildable (npm run build must succeed)
- Use existing UI components from src/components/ui/
- Follow existing code patterns and style
- Write clean, production-ready code
- Do not introduce placeholder content unless required
- Follow page templates AND page specifications for professional UI
- Ensure all UI elements from page specs are implemented

---

## ⚠️ CRITICAL: PAGE COMPONENT RULES ⚠️

DO NOT wrap page components in Layout:
- ❌ WRONG: `export default function Dashboard() { return <Layout><div>...</div></Layout> }`
- ✅ CORRECT: `export default function Dashboard() { return <div>...</div> }`

The Layout is ALREADY provided by the router at App.tsx level:
```tsx
<Route element={<Layout />}>  ← Layout wrapper here
  <Route path="/" element={<Dashboard />} />  ← Page renders inside Layout's <Outlet />
</Route>
```

Pages should return content that renders inside Layout's `<Outlet />`, NOT wrap themselves in Layout.

**DO NOT import or use Layout component in page files!**

---

## IMPLEMENTATION

Make your changes directly to files.

Do NOT request JSON output or any specific format.

Just implement the changes using your available tools.
```

---

## Variables

| Variable | Description | Source |
|----------|-------------|--------|
| `{project_name}` | Name of the project | Project record |
| `{goal_description}` | Project/product description | User input |
| `{default_page}` | First page in manifest (usually Dashboard) | Page manifest |
| `{required_pages_str}` | List of required pages | Page manifest |
| `{page_templates_section}` | Page templates guidance | Disabled |
| `{page_specs_section}` | Page specifications | `page_specs.py` |

---

## Expected Behavior

1. **Fix routing first** - Remove Welcome route, add default page at "/"
2. **Create pages** - Generate all required pages from manifest
3. **Update navigation** - Sidebar/nav reflects new pages
4. **Build succeeds** - `npm run build` completes without errors

---

## File Locations

- **Prompt builder:** `acp_frontend_editor_v2.py:1410` (`_build_acpx_prompt()`)
- **Execution:** `acp_frontend_editor_v2.py:685` (Step 6: Run ACPX)
- **CLI command:** `acpx --cwd <dir> --format quiet claude exec "<prompt>"`
