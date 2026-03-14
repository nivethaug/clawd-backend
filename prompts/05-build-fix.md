# Build Fix Prompt

**Purpose:** Automatically fix build errors after frontend changes  
**Used in:** `infrastructure_manager.py` → `build_frontend()`  
**Phase:** Phase 6 (Service Setup) - Build Gate

---

## Prompt Template

```markdown
You are fixing a build error in a React + Vite + TypeScript application.

BUILD ERROR:
{build_error}

YOUR TASK:
1. Analyze the build error carefully
2. Fix ALL TypeScript errors, missing imports, and type mismatches
3. Ensure all components are properly imported and exported
4. Fix any JSX syntax errors
5. Do NOT delete or remove functionality - only fix errors
6. Keep the code production-ready

RULES:
- Fix ONLY the errors - do not refactor or add features
- Ensure all imports use correct paths
- Fix type mismatches (string vs number, etc.)
- Add missing type definitions if needed
- Ensure all JSX elements are properly closed
- Run npm run build after fixes

CRITICAL: Fix the errors and ensure npm run build succeeds.
```

---

## Variables

| Variable | Description | Source |
|----------|-------------|--------|
| `{build_error}` | Build error output (truncated to 2000 chars) | `npm run build` stderr |

---

## Expected Behavior

1. **Analyze** - Parse TypeScript/build errors
2. **Fix imports** - Correct missing or wrong import paths
3. **Fix types** - Resolve type mismatches
4. **Fix JSX** - Correct syntax errors
5. **Build** - Verify `npm run build` succeeds

---

## When This Runs

This prompt is triggered when:
1. `npm run build` fails during Phase 6
2. Build error is captured from stderr
3. ACPX is invoked with this fix prompt
4. Auto-fix attempts to resolve errors
5. Build is retried after fixes

---

## Example Errors Fixed

- Missing imports: `import { Button } from './ui/button'`
- Type mismatches: `string` vs `number`
- JSX syntax: Unclosed tags, wrong attributes
- Missing components: Component used but not imported
- Export errors: Component not exported from module

---

## File Locations

- **Prompt builder:** `infrastructure_manager.py:1608`
- **Execution:** `infrastructure_manager.py:1631` (ACPX auto-fix)
- **CLI command:** `acpx --cwd <dir> --format quiet claude exec "<fix-prompt>"`
