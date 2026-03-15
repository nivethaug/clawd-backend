# Project Creation API

> [TOC](toc.md) | [SKILL.md](../.agents/skills/project-info/SKILL.md) | Updated: 2026-03-15

---

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/projects` | POST | Create new project |
| `/projects` | GET | List all projects |
| `/projects/{project_id}` | GET | Get project details |
| `/projects/{project_id}` | PUT | Update project |

---

## Create Project

```
POST /projects
```

**Request Body:**
```json
{
  "name": "my-project",
  "domain": "myproject",
  "description": "Project description",
  "user_id": 1,
  "type_id": 1,
  "template_id": "blank-template"
}
```

**Response:**
```json
{
  "id": 1,
  "user_id": 1,
  "name": "my-project",
  "domain": "myproject",
  "description": "Project description",
  "project_path": "/root/clawd-projects/my-project",
  "status": "creating",
  "template_id": "blank-template",
  "created_at": "2026-03-15T10:00:00"
}
```

**File:** `app.py:283-350`

---

## List Projects

```
GET /projects?user_id=1
```

**Query Params:**
- `user_id` (optional): Filter by user

**Response:**
```json
[
  {
    "id": 1,
    "name": "my-project",
    "domain": "myproject",
    "status": "ready",
    ...
  }
]
```

**File:** `app.py:241-280`

---

## Get Project

```
GET /projects/{project_id}
```

**Response:** Project object

**File:** `app.py:355-380`

---

## Update Project

```
PUT /projects/{project_id}
```

**Request Body:**
```json
{
  "name": "new-name",
  "description": "Updated description"
}
```

**File:** `app.py:1357-1410`

---

## Pipeline Flow

| Step | File | Description |
|------|------|-------------|
| 1 | `app.py` | Validate request, insert DB |
| 2 | `template_selector.py` | Select template |
| 3 | `fast_wrapper.py` | Scaffold project structure |
| 4 | `openclaw_wrapper.py` | Run pipeline phases |
| 5 | `infrastructure_manager.py` | Setup infrastructure |

---

## Related

- [Project Status](project_status.md)
- [Project Deletion](project_deletion.md)
- [Publish Frontend](publish_frontend.md)
- [Publish Backend](publish_backend.md)
