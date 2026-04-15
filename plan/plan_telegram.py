"""
Telegram bot project plan prompt builder.
"""

from typing import Optional
from plan.plan_base import build_base_plan_prompt


def build_telegram_plan_prompt(
    user_message: str,
    session_context: str,
    project_path: str,
    project_name: str,
    existing_plan: Optional[str] = None,
) -> str:
    project_context = f"""## PROJECT CONTEXT — Telegram Bot ({project_name})

**Project path:** `{project_path}`

### File Structure (Key Areas)
- `bot.py` or `main.py` — Bot entry point
- `handlers/` — Command and message handlers
- `api_client.py` — External API calls
- `agent/README.md` — Bot agent docs
- `agent/ai_index/` — AI index files

### Agent ai_index Files (READ BEFORE PLANNING)
- `agent/ai_index/summaries.json` — What each file does
- `agent/ai_index/symbols.json` — Functions, commands, handlers with line numbers
- `agent/ai_index/modules.json` — Logical structure
- `agent/ai_index/dependencies.json` — Import relationships
- `agent/ai_index/files.json` — File metadata

### API Integration
- LLM API catalog at `{project_path}/llm/categories/index.json`
- Ask user which API source: LLM catalog, custom endpoint, or existing internal functions

### Deployment
- PM2 manages the bot process
- Restart PM2 after code changes to apply

### Git Workflow
- Use `git_workflow.py` GitWorkflowManager
- Branch → commit → PR → merge via the manager
"""

    return build_base_plan_prompt(
        user_message=user_message,
        session_context=session_context,
        project_name=project_name,
        project_path=project_path,
        existing_plan=existing_plan,
        project_specific_context=project_context,
    )
