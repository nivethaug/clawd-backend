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

## 6. Post-Merge Branch Cleanup Rule (Mandatory)

- After user confirms that a Pull Request has been merged into `main`,
  - AI MUST verify whether the feature branch still exists.

- The AI MUST check:
  1. Whether branch exists locally
  2. Whether branch exists on the remote (GitHub)

- If the branch EXISTS:
  - The AI MUST delete it safely:
    - Local: `git branch -d <branch-name>`
    - Remote: `git push origin --delete <branch-name>`

- If the branch DOES NOT exist:
  - The AI MUST NOT fail
  - The AI MUST report that the branch was already deleted
    (for example, due to GitHub auto-delete after merge)

- Branch cleanup MUST be:
  - Safe
  - Idempotent
  - Non-blocking

- The AI MUST NEVER attempt branch deletion:
  - Before PR is merged
  - Without explicit user confirmation that the merge is complete.

---

## 7. Enforcement

Failure to follow these rules is a process violation.
These rules override convenience, speed, or assumptions.

---

## IMPORTANT BEHAVIOR CHANGE (APPLIES TO ALL FUTURE TASKS):

Before starting ANY new task:

- Always create a new branch from `main`
- Perform all work on that branch only
- Stop and request user approval when work is complete
- Create a Pull Request ONLY after approval
- Never push or commit directly to `main`
- After merge confirmation, clean up the feature branch if it exists.

---

## Reference Deployment Architecture (Authoritative)

The following architecture defines how source code, server instances,
and port bindings MUST behave in this repository. These paths and flows
are mandatory and must not be altered unless explicitly approved by the user.


┌─────────────────────────────────────────────────────┐
│  SOURCE CODE (/root/clawd-backend/)           │
│                                              │
│  ├─ main branch (stable)                 │
│  └─ feature/* branches (development)       │
└──────────────────┬──────────────────────────────────┘
                   │
                   │ (Python code runs in place)
                   ▼
┌─────────────────────────────────────────────────────┐
│  RUNNING APPLICATION (Python FastAPI)         │
│  No build step - Python serves directly         │
│  Source files: app.py, database.py, etc.     │
└──────────────────┬──────────────────────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
        │ PM2 Process          │ PM2 Process (Optional)
        │                      │
        ▼                      ▼
┌──────────────┐      ┌─────────────────────┐
│ Port 8002    │      │ Port 8001           │
│ Production   │      │ Development           │
│              │      │                      │
│ Server: Uvicorn │      │ Server: Uvicorn       │
│ Process: main│      │ Process: feature/*   │
│ Branch: main  │      │ Branch: feature/*     │
│ URL:          │      │ URL:                 │
│ http://       │      │ http://              │
│ localhost:    │      │ localhost:           │
│ 8002         │      │ 8001                │
│              │      │                      │
│ API Public   │      │ API Public (Optional) │
│ http://195.   │      │ http://195.           │
│ 200.14.37:   │      │ 200.14.37:           │
│ 8002         │      │ 8001                 │
└──────────────┘      └─────────────────────┘


### Architectural Rules Derived From This Diagram

- There is **only one source code directory**: `/root/clawd-backend/`
- Python applications run **in-place** (no build step)
- Different PM2 processes use **different ports**
- Each branch can run on its own port simultaneously

### Production Server Rules (Port 8002)

- PM2 process `clawd-backend` runs on port 8002
- Always runs `main` branch code
- Production API: http://195.200.14.37:8002
- Database: `/root/clawd-backend/clawdbot_adapter.db`

### Development Server Rules (Port 8001 - Optional)

- Optional PM2 process for feature branches
- Runs on port 8001 when needed
- Development API: http://195.200.14.37:8001
- Can create multiple development instances if needed

This architecture is intentional for rapid testing without affecting production.
