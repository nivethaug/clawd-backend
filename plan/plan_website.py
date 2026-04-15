"""
Website project plan prompt builder.
"""

from typing import Optional
from plan.plan_base import build_base_plan_prompt


def build_website_plan_prompt(
    user_message: str,
    session_context: str,
    project_path: str,
    project_name: str,
    existing_plan: Optional[str] = None,
) -> str:
    project_context = f"""## PROJECT CONTEXT — Website ({project_name})

**Project path:** `{project_path}`

### File Structure (Key Areas)
- `frontend/` — React/Vite frontend
- `frontend/src/` — Source code
- `frontend/src/components/` — UI components
- `frontend/src/pages/` — Page components
- `frontend/src/lib/` — Utilities, API clients, hooks
- `backend/` — Python backend
- `frontend/agent/README.md` — Frontend agent docs
- `backend/agent/README.md` — Backend agent docs

### Agent ai_index Files (READ BEFORE PLANNING)
- `frontend/agent/ai_index/symbols.json` — All functions, components, APIs with line numbers
- `frontend/agent/ai_index/modules.json` — Logical file groupings
- `frontend/agent/ai_index/summaries.json` — What each file does
- `backend/agent/ai_index/symbols.json` — Backend functions/APIs
- `backend/agent/ai_index/summaries.json` — Backend file summaries

### Build & Deploy
- Run `buildpublish.py` to install + build + deploy
- Test with Chrome DevTools on live site after deployment

### Git Workflow
- Use `git_workflow.py` GitWorkflowManager at `{project_path}/git_workflow.py`
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
