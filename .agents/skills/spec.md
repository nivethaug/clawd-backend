# Documentation Standards - Complete Reference

> Updated: 2026-03-15

---

## Table of Contents

| Section | Lines | Description |
|---------|-------|-------------|
| [Role & Goal](#role--goal) | 9-22 | Purpose and objective |
| [Required Structure](#required-structure) | 24-33 | File organization rules |
| [TOC Format](#toc-format) | 35-50 | Table of contents template |
| [Backend Rules](#backend-documentation-rules) | 52-90 | API endpoint documentation |
| [Frontend Rules](#frontend-documentation-rules) | 92-120 | Component documentation |
| [Example Files](#example-files) | 122-140 | Reference examples |
| [PRD Workflow](#prd-workflow) | 142-180 | Reverse-engineering process |
| [Output](#output) | 182-188 | File format & location |

---

## Role & Goal

### Role

| Aspect | Description |
|--------|-------------|
| **Title** | Senior Technical Architect |
| **Task** | Read code and translate to user-centric requirements |
| **Output** | Product Requirements Document (PRD) |

### Goal

| Objective | Description |
|-----------|-------------|
| **Target** | Brownfield codebase (existing system) |
| **Process** | Multi-turn conversation |
| **Purpose** | Baseline document for enhancements/fixes/refactors |
| **Companion** | Technical Specification Document (TSD) |

> **Note:** Technical constraints often dictate product behavior (e.g., "reports update daily"). These **should** be captured if they impact user experience.

---

## Required Structure

| Project Type | Required Files | Format |
|--------------|----------------|--------|
| **Any** | `toc.md` | Table of contents with line numbers |
| **Backend** | `docs/{endpoint}.md` | One MD per endpoint group |
| **Frontend** | `docs/{component}.md` | One MD per component/page |

### File Naming Convention

| Type | Pattern | Example |
|------|---------|---------|
| Endpoint | `{resource}_{action}.md` | `project_creation.md`, `chat_stream.md` |
| Component | `{ComponentName}.md` | `LoginForm.md`, `Dashboard.md` |
| TOC | `toc.md` | Always `toc.md` |

---

## TOC Format

Every documentation file MUST include a TOC at the top:

```markdown
## Table of Contents

| Section | Lines | Description |
|---------|-------|-------------|
| [Section Name](#section-name) | 10-25 | Brief description |
```

### TOC Requirements

| Requirement | Description |
|-------------|-------------|
| **Line numbers** | Always include Lines column |
| **Anchors** | Use lowercase, hyphen-separated anchors |
| **Description** | Brief, action-oriented description |

---

## Backend Documentation Rules

| Rule | Description | Example |
|------|-------------|---------|
| **Endpoint-based files** | One MD file per endpoint group | `chat.md`, `project_status.md` |
| **Traverse to end** | Find actual handler method, not just route | Follow `@router` → function → implementation |
| **Include line numbers** | Always use `File:Lines` format | `app.py:1436-1530` |
| **API Endpoints table** | Required at top of each file | See template below |

### Backend File Template

```markdown
# {Resource} - Complete Reference

> [TOC](toc.md) | Updated: YYYY-MM-DD

---

## API Endpoints

| Endpoint | Method | File | Lines | Description |
|----------|--------|------|-------|-------------|
| `/resource` | POST | `app.py` | 100-150 | Create resource |

---

## POST /resource

**File:** `app.py:100-150`

**Request:**
```json
{ ... }
```

**Response:**
```json
{ ... }
```
```

### How to Find Line Numbers

| Step | Action | Tool |
|------|--------|------|
| 1 | Find route decorator | Search `@router.post("/endpoint")` |
| 2 | Find handler function | Look for `async def handler_name()` |
| 3 | Find end of function | Next route decorator or class definition |
| 4 | Record line range | `start_line-end_line` |

---

## Frontend Documentation Rules

| Rule | Description |
|------|-------------|
| **Component-based files** | One MD file per component or page |
| **Include line numbers** | Reference specific component functions |
| **TOC with anchors** | Always include navigable table of contents |

### Frontend File Template

```markdown
# {ComponentName} - Complete Reference

> [TOC](toc.md) | Updated: YYYY-MM-DD

---

## Table of Contents

| Section | Lines | Description |
|---------|-------|-------------|
| [Props](#props) | 15-25 | Component properties |
| [State](#state) | 27-35 | Component state |
| [Methods](#methods) | 37-80 | Component methods |

---

## Props

**File:** `src/components/{ComponentName}.tsx:15-25`

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `id` | string | Yes | Unique identifier |
```

---

## Example Files

### Backend Example: `docs/chat.md`

| Section | Lines | Content |
|---------|-------|---------|
| Title | 1-3 | `# Chat - Complete Reference` |
| Links | 5 | TOC/SKILL links |
| Endpoints Table | 9-12 | API Endpoints table |
| Endpoint Details | 14-40 | POST /chat with Request/Response |

### Frontend Example: `docs/LoginForm.md`

| Section | Lines | Content |
|---------|-------|---------|
| Title | 1-3 | `# LoginForm - Complete Reference` |
| TOC | 5-10 | Table of Contents |
| Props | 12-25 | Props table with types |
| State | 27-35 | State variables |
| Methods | 37-60 | Event handlers |

---

## PRD Workflow

### When to Use

Use this workflow when reverse-engineering a PRD from existing code.

### Process

| Step | Name | Description |
|------|------|-------------|
| 1 | Map & Analyze | Explore codebase, extract implemented behavior |
| 2 | Confidence Check | Categorize findings (Verified/Needs Confirmation/Assumed) |
| 3 | Ask Questions | Present targeted questions, **STOP and wait** |
| 4 | Generate PRD | Produce final document after answers |

### Confidence Categories

| Category | Description | Action |
|----------|-------------|--------|
| **Verified** | Confirmed by code/tests | Document directly |
| **Needs Confirmation** | Code exists, intent unclear | Ask question |
| **Assumed** | Cannot determine | State assumption |

### PRD Structure

| Section | Content |
|---------|---------|
| **System Summary** | What the system is and its purpose |
| **User Roles** | Who uses the system |
| **Functional Requirements** | Grouped by feature, numbered |
| **Business Rules** | Domain rules and validation |
| **System Constraints** | Technical limitations |
| **Edge Cases** | Boundary handling |
| **Assumptions** | Stated assumptions |

---

## Output

| Property | Value |
|----------|-------|
| **Format** | Markdown (`.md`) |
| **Filename** | `{resource}.md` or `PRD-{service}.md` |
| **Location** | `docs/` directory |

---

## End of spec.md
