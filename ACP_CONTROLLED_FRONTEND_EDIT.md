# ACP Controlled Frontend Edit – Phase 8 Extension

## Feature: Controlled Claude Code (ACP) Frontend Refinement

---

## 1. Objective

After Phase 8 completes, enable controlled frontend refinement using Claude Code via ACP (GLM configured). The system must:

* Remove unwanted template files (inside src only)
* Keep existing structure intact
* Keep all UI controls under `components/ui` intact
* Maintain routing system integrity
* Add maximum **4 new files**
* Update routing when new pages are added
* Maintain top-notch UI quality
* Enforce strict validation, build gate, and rollback

This feature must NOT:

* Modify backend
* Modify control backend
* Modify package.json
* Modify vite.config
* Modify node_modules
* Modify UI core component structure

---

## 2. Authoritative Project Paths

Generated project root:
```
/root/dreampilot/projects/website/{projectname}/
```

Frontend root:
```
/root/dreampilot/projects/website/{projectname}/frontend/
```

Allowed edit directory:
```
/root/dreampilot/projects/website/{projectname}/frontend/src/
```

Protected UI core directory:
```
/root/dreampilot/projects/website/{projectname}/frontend/src/components/ui/
```

---

## 3. Hard Enforcement Rules

### 3.1 Allowed Claude may:

* Modify files inside `src/`
* Remove unused template files inside `src/`
* Add maximum **4 new files**
* Create new page files
* Update route definitions in `App.tsx` or router file

### 3.2 Strictly Forbidden Claude must NOT:

* Modify `/root/clawd-backend/`
* Modify `/backend/`
* Modify `/frontend/package.json`
* Modify `/frontend/vite.config.*`
* Modify `/frontend/node_modules/`
* Modify any `.env`
* Modify nginx configs
* Modify database files
* Modify structure inside `components/ui/`

---

## 4. UI Quality Requirement (Critical)

All newly created or modified UI must be:

* Production-grade quality
* Consistent spacing and layout
* Responsive (mobile + desktop)
* Properly structured
* Type-safe (TypeScript compliant)
* Clean component composition
* Accessible where applicable
* Visually aligned with existing design system

Must:

* Use existing UI primitives from `components/ui/`
* Not re-create button/card/alert components
* Not duplicate UI base components
* Respect existing layout system

Top-notch UI quality is mandatory.

---

## 5. File Addition Constraint

Maximum allowed new files:
```
4 files per ACP execution
```

If new files > 4:

* Abort process
* Restore snapshot
* Log violation

---

## 6. Snapshot & Rollback

Before ACP execution: Create full backup:
```
/root/dreampilot/projects/website/{projectname}/frontend_backup_<timestamp>/
```

If:

* Validation fails
* File limit exceeded
* Build fails

Then:

* Restore backup
* Log rollback event
* Abort safely

---

## 7. Routing Enforcement

If a new page is added:

1. The page must be placed in appropriate directory (e.g. `src/pages/`)
2. Routing must be updated inside:
   * `App.tsx`
   * or existing router file
3. No routing refactor allowed
4. Existing routes must not be broken
5. Default route must remain functional

---

## 8. ACP Instruction Template

Claude must receive structured instruction:
```
You are editing a React + Vite + TypeScript project.

Rules:
- Only modify files inside src/
- Do not touch components/ui/
- You may remove unused template files
- You may add at most 4 new files
- Do not modify package.json
- Do not modify vite.config
- Keep folder structure intact
- Keep routing intact
- Maintain top-tier UI quality
- Use existing UI primitives
- Not re-create button/card/alert components
- Not duplicate UI base components
- Respect existing layout system
- Return structured patch (file path + content)

Goal: <Project description>
```

---

## 9. Validation Layer

System must validate:

* All edited paths are inside allowed directory
* No protected paths modified
* File addition count <= 4
* No structural folder changes
* No modification inside `components/ui/`

If violation detected:

* Abort
* Rollback
* Log violation

---

## 10. Build Gate (Mandatory)

After applying ACP changes: Run:
```
cd /root/dreampilot/projects/website/{projectname}/frontend
npm install
npm run build
```

If build fails:

* Restore snapshot
* Log failure
* Abort

If build succeeds:

* Restart frontend PM2 process only
* Do NOT restart backend

---

## 11. Mutation Log

Create:
```
/root/dreampilot/projects/website/{projectname}/frontend/.acp_mutation_log.json
```

Log:

* Timestamp
* Files modified
* Files added
* Files removed
* Build result
* Rollback status

---

## 12. Git Rules (Control Backend Only)

All control backend changes must follow:

Branch:
```
feature/acp-controlled-frontend-edit
```

Rules:

* No direct commits to main
* Work only on feature branch
* Stop after completion
* Wait for approval
* Create PR to main
* After merge confirmation → delete branch (local + remote safely)

---

## 13. Acceptance Criteria

* Snapshot working
* Whitelist enforced
* Max 4 files enforced
* components/ui untouched
* Routing intact
* UI quality high
* Build gate enforced
* Rollback working
* Mutation log generated
* Tested on development port 8001
* Production untouched (8002 safe)

---

## 14. Expected Outcome

After implementation:

1. Project created
2. Phase 8 runs
3. ACP refines frontend safely
4. UI improved
5. Routing updated if needed
6. Build validated
7. Frontend restarted
8. Backend untouched
9. Control backend safe

---

## End of Task Specification
