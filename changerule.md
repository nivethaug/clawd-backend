# Change Rules (Mandatory)

These rules MUST be followed for all development work in this repository.

---

## 1. Branching Rule

- All new work MUST start from the `main` branch.
- A new branch MUST be created before any change.
- Direct commits to `main` are strictly forbidden.

### Branch naming convention:
- `feature/<short-description>`
- `fix/<short-description>`
- `refactor/<short-description>`

---

## 2. Development Rule

- All code changes MUST be done on the newly created branch.
- No experimental, partial, or temporary work may be committed to `main`.

---

## 3. Approval Rule

- After completing work, the agent MUST stop.
- Explicit user approval is REQUIRED before proceeding.
- Approval must be clear (e.g., "Approved", "Yes, create PR").

---

## 4. Pull Request Rule

- A Pull Request MUST be created only after approval.
- The PR MUST:
  - Target `main` branch
  - Contain a clear title
  - Include a concise summary of changes.

---

## 5. Merge Restriction

- No merge into `main` is allowed without:
  1. User approval
  2. A Pull Request.

---

## 6. Enforcement

Failure to follow these rules is a process violation. These rules override convenience, speed, or assumptions.

---

IMPORTANT BEHAVIOR CHANGE (APPLIES TO ALL FUTURE TASKS):

Before starting ANY new task:
- Always create a new branch from `main`
- Perform all work on that branch only
- Stop and request user approval when work is complete
- Create a Pull Request ONLY after approval
- Never push or commit directly to `main`
