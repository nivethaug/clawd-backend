"""
Scheduler project plan prompt builder.
"""

from typing import Optional
from plan.plan_base import build_base_plan_prompt


def build_scheduler_plan_prompt(
    user_message: str,
    session_context: str,
    project_path: str,
    project_name: str,
    existing_plan: Optional[str] = None,
) -> str:
    project_context = f"""## PROJECT CONTEXT — Scheduler ({project_name})

**Project path:** `{project_path}`

### File Structure (Key Areas)
- `executor.py` — Job execution engine
- `api_client.py` — REST API helpers
- `scheduler.py` — Scheduling logic
- `agent/README.md` — Agent docs
- `agent/ai_index/` — AI index files

### Agent ai_index Files (READ BEFORE PLANNING)
- `agent/ai_index/summaries.json` — What each file does
- `agent/ai_index/symbols.json` — Functions, APIs with line numbers
- `agent/ai_index/modules.json` — Logical structure
- `agent/ai_index/dependencies.json` — Import relationships
- `agent/ai_index/files.json` — File metadata

### REST API
- Jobs managed via REST API endpoints
- Backend URL: `http://localhost:<port>/api/scheduler/projects/<project_id>/jobs`

### Deployment
- PM2 manages the scheduler process
- Restart PM2 after code changes to apply

### Git Workflow
- Use `git_workflow.py` GitWorkflowManager
- Initialize with project_id and session_id
- Use manager.commit_and_push("message") after user approval
- No branching — work directly on main
"""

    return build_base_plan_prompt(
        user_message=user_message,
        session_context=session_context,
        project_name=project_name,
        project_path=project_path,
        existing_plan=existing_plan,
        project_specific_context=project_context,
    )
