"""
Support Project Context — builds the SAFE project snapshot injected into
the AI support assistant's prompt.

HARD EXCLUDE-LIST (never exposed to the support AI, admins' chat view, or
logs): project_path, backend/frontend ports, claude_code_session_name,
active_session_id, any environment values (env_variable_registry), bot
tokens, API keys, passwords. Only the allow-listed display fields below
ever leave the projects row.
"""

import logging
from typing import Any, Dict, Optional

from database_adapter import get_db

logger = logging.getLogger("support.project_context")

# The ONLY project columns exposed. Anything added here must be reviewed
# against the exclude list above.
_SAFE_COLUMNS = "id, name, description, type_id, domain, status, pipeline_status, error_code, repo_url, created_at, updated_at"


def build_project_context(project_id: int, *, owner_user_id: int) -> Optional[Dict[str, Any]]:
    """Return a safe context dict for a project OWNED BY owner_user_id.

    Ownership is re-validated here — a mismatched project_id yields None,
    regardless of what the client asked for.
    """
    with get_db() as conn:
        row = conn.execute(
            f"""SELECT {_SAFE_COLUMNS} FROM projects
                WHERE id = ? AND user_id = ?""",
            (project_id, owner_user_id),
        ).fetchone()
        if not row:
            return None
        p = dict(row) if not isinstance(row, dict) else row

        # Project type label (display only)
        type_row = conn.execute(
            "SELECT display_name FROM project_types WHERE id = ?", (p.get("type_id"),)
        ).fetchone()
        p["project_type"] = (
            (dict(type_row) if not isinstance(type_row, dict) else type_row)["display_name"]
            if type_row else None
        )

        # Container status (safe operational signal)
        cont = conn.execute(
            "SELECT status FROM user_containers WHERE user_id = ? LIMIT 1",
            (owner_user_id,),
        ).fetchone()
        p["container_status"] = (
            (dict(cont) if not isinstance(cont, dict) else cont).get("status") if cont else None
        )

    # Trim potentially large JSONB progress blob to recent/essential keys
    pipeline = p.get("pipeline_status")
    if isinstance(pipeline, dict):
        p["pipeline_status"] = {
            k: pipeline[k] for k in ("current_step", "progress", "error", "status")
            if k in pipeline
        }
    elif pipeline:
        p["pipeline_status"] = str(pipeline)[:400]
    if p.get("description"):
        p["description"] = str(p["description"])[:300]

    return p


def context_as_prompt_text(ctx: Optional[Dict[str, Any]]) -> str:
    """Render the context dict as compact prompt text for the AI."""
    if not ctx:
        return "(no project context available)"
    lines = [
        f"Project name: {ctx.get('name')}",
        f"Type: {ctx.get('project_type') or 'unknown'}",
        f"Status: {ctx.get('status')}",
    ]
    if ctx.get("domain"):
        lines.append(f"Domain: {ctx['domain']}")
    if ctx.get("container_status"):
        lines.append(f"Workspace container: {ctx['container_status']}")
    if ctx.get("error_code"):
        lines.append(f"Last error code: {ctx['error_code']}")
    if ctx.get("pipeline_status"):
        lines.append(f"Pipeline: {ctx['pipeline_status']}")
    if ctx.get("description"):
        lines.append(f"Description: {ctx['description']}")
    return "\n".join(lines)
