"""Sanctioned frontend-dependency endpoint (Dependency Management Plan, P1).

POST /projects/{project_id}/frontend/deps  {"packages": ["name@1.2.3", ...]}

Owner-gated (admin allowed). Runs where the project files live — the
project_proxy forwards worker-homed projects automatically after applying
the same owner gate main-side.
"""
import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from services.deps.frontend_deps import add_frontend_deps

logger = logging.getLogger("api.frontend_deps")
router = APIRouter()


class FrontendDepsRequest(BaseModel):
    packages: List[str]


@router.post("/projects/{project_id}/frontend/deps")
async def add_deps(
    project_id: int,
    request: FrontendDepsRequest,
    authorization: Optional[str] = Header(None),
):
    from app import get_user_id_from_token, get_db, _require_project_owner
    user_id = _require_project_owner(project_id, authorization)

    with get_db() as conn:
        row = conn.execute(
            "SELECT project_path FROM projects WHERE id = ?",
            (project_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    project_path = row["project_path"] if not isinstance(row, dict) else row["project_path"]
    if not project_path or not os.path.isdir(project_path):
        raise HTTPException(status_code=404, detail="Project path not found on this host")

    result = add_frontend_deps(project_path, request.packages)
    if not result["ok"]:
        # gate rejections are client errors (actionable); write failures 500
        raise HTTPException(status_code=400, detail={
            "message": result["message"], "gate": result.get("gate")})
    logger.info("[DEPS] user %s added %s to project %s",
                user_id, result["added"], project_id)
    return result
