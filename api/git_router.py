#!/usr/bin/env python3
"""Custom Git Projects — user-facing API.

Enterprise-only (requires active dedicated worker).
All endpoints owner-gated + dedicated-worker-gated.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from utils.auth_helpers import get_user_id_from_token
from services.git_projects.urls import GitUrlValidator
from services.git_projects.credentials import GitCredentialService
from services.git_projects.transport import GitTransport
from services.git_projects.audit import audit_event

logger = logging.getLogger("api.git")
router = APIRouter()


def _require_dedicated(user_id: int) -> dict:
    """Gate: user must have an active dedicated worker."""
    from services import worker_registry

    node = worker_registry.resolve_for_user(user_id)
    if not node:
        raise HTTPException(
            status_code=403,
            detail="Custom Git Projects require a Dedicated Worker. Upgrade to Enterprise or purchase the Dedicated Worker add-on.",
        )
    return node


# ── Credential management ─────────────────────────────────────────────────

@router.get("/api/git/providers")
async def list_providers(authorization: Optional[str] = Header(None)):
    """List connected Git accounts for the current user."""
    user_id = get_user_id_from_token(authorization)
    _require_dedicated(user_id)
    return {"credentials": GitCredentialService.list_credentials(user_id)}


class ConnectPatRequest(BaseModel):
    provider: str  # github | generic
    token: str
    account_ref: Optional[str] = None
    display_label: Optional[str] = None


@router.post("/api/git/connect")
async def connect_provider(req: ConnectPatRequest, authorization: Optional[str] = Header(None)):
    """Connect a Git provider using a Personal Access Token."""
    user_id = get_user_id_from_token(authorization)
    _require_dedicated(user_id)

    if not req.token or len(req.token) < 10:
        raise HTTPException(status_code=400, detail="Token is required")

    account_ref = req.account_ref or f"{req.provider}-account"
    result = GitCredentialService.connect(
        user_id, req.provider, account_ref, req.token,
        display_label=req.display_label,
    )
    audit_event(user_id, "connect", detail={"provider": req.provider, "account": account_ref})
    return result


@router.delete("/api/git/credentials/{credential_id}")
async def disconnect(credential_id: int, authorization: Optional[str] = Header(None)):
    """Disconnect a Git account."""
    user_id = get_user_id_from_token(authorization)
    _require_dedicated(user_id)
    GitCredentialService.disconnect(user_id, credential_id)
    audit_event(user_id, "disconnect", detail={"credential_id": credential_id})
    return {"success": True}


# ── Repository listing ────────────────────────────────────────────────────

@router.get("/api/git/repos")
async def list_repos(
    url: Optional[str] = None,
    credential_id: Optional[int] = None,
    authorization: Optional[str] = Header(None),
):
    """List repositories (or validate a specific URL)."""
    user_id = get_user_id_from_token(authorization)
    _require_dedicated(user_id)

    if url:
        # Validate a specific URL
        is_valid, error = GitUrlValidator.validate(url)
        if not is_valid:
            raise HTTPException(status_code=400, detail=error)
        info = GitUrlValidator.extract_info(url)
        return {"valid": True, "info": info, "url": GitUrlValidator.normalize(url)}

    # List GitHub repos using the user's token
    token = GitCredentialService.get_token(user_id, credential_id)
    if not token:
        raise HTTPException(status_code=404, detail="No Git credential connected")

    import urllib.request
    req = urllib.request.Request(
        "https://api.github.com/user/repos?per_page=30&sort=updated",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3+json"},
    )
    try:
        import json
        with urllib.request.urlopen(req, timeout=15) as resp:
            repos = json.loads(resp.read())
        return {"repos": [
            {
                "name": r["full_name"],
                "private": r["private"],
                "default_branch": r.get("default_branch", "main"),
                "updated_at": r.get("updated_at", ""),
                "url": r["clone_url"],
            }
            for r in repos[:30]
        ]}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"GitHub API error: {str(exc)[:100]}")


# ── Project git operations ────────────────────────────────────────────────

@router.get("/api/projects/{project_id}/git/status")
async def git_status(project_id: int, authorization: Optional[str] = Header(None)):
    """Get git status for a Git Project."""
    user_id = get_user_id_from_token(authorization)
    _require_dedicated(user_id)

    from app import _require_project_owner
    from database_adapter import get_db
    _require_project_owner(project_id, authorization)

    with get_db() as conn:
        row = conn.execute(
            """SELECT project_path, git_origin_url, git_default_branch, git_provider
               FROM projects WHERE id = %s""",
            (project_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")

    d = row if isinstance(row, dict) else dict(zip(
        ("project_path", "git_origin_url", "git_default_branch", "git_provider"), row))

    if not d.get("git_origin_url"):
        raise HTTPException(status_code=400, detail="Not a Git Project")

    transport = GitTransport(user_id, d["project_path"])
    status = transport.status()
    ab = transport.ahead_behind()

    return {
        "provider": d.get("git_provider"),
        "origin": d.get("git_origin_url"),
        "branch": status.get("output", "").split("\n")[-1].strip() if status.get("output") else "unknown",
        "dirty": status.get("dirty", False),
        "ahead": ab["ahead"],
        "behind": ab["behind"],
        "recent": transport.log(5),
    }


class CommitRequest(BaseModel):
    message: str
    paths: Optional[str] = None


@router.post("/api/projects/{project_id}/git/commit")
async def git_commit(project_id: int, req: CommitRequest, authorization: Optional[str] = Header(None)):
    """Explicit user-initiated commit."""
    user_id = get_user_id_from_token(authorization)
    _require_dedicated(user_id)

    from app import _require_project_owner
    from database_adapter import get_db
    _require_project_owner(project_id, authorization)

    with get_db() as conn:
        row = conn.execute(
            "SELECT project_path FROM projects WHERE id = %s", (project_id,)
        ).fetchone()
    project_path = (row["project_path"] if isinstance(row, dict) else row[0]) if row else None
    if not project_path:
        raise HTTPException(status_code=404, detail="Project not found")

    transport = GitTransport(user_id, project_path)
    result = transport.commit(req.message, req.paths)

    if result["success"]:
        audit_event(user_id, "commit", project_id, {"sha": result.get("sha", "")[:12]})
    return result


class PushRequest(BaseModel):
    force: bool = False


@router.post("/api/projects/{project_id}/git/push")
async def git_push(project_id: int, req: PushRequest, authorization: Optional[str] = Header(None)):
    """Explicit user-initiated push (with policy checks)."""
    user_id = get_user_id_from_token(authorization)
    _require_dedicated(user_id)

    from app import _require_project_owner
    from database_adapter import get_db
    _require_project_owner(project_id, authorization)

    with get_db() as conn:
        row = conn.execute(
            "SELECT project_path, git_credential_id FROM projects WHERE id = %s",
            (project_id,),
        ).fetchone()
    d = row if isinstance(row, dict) else dict(zip(("project_path", "git_credential_id"), row))
    if not d.get("project_path"):
        raise HTTPException(status_code=404, detail="Project not found")

    # Get token for push auth
    token = GitCredentialService.get_token(user_id, d.get("git_credential_id"))
    if not token:
        raise HTTPException(status_code=400, detail="No Git credential for push auth")

    transport = GitTransport(user_id, d["project_path"])

    # Pre-push checks
    status = transport.status()
    if status.get("dirty"):
        raise HTTPException(status_code=409, detail="Uncommitted changes — commit first")

    # Push
    result = transport.push(token=token, force=req.force)

    if result["success"]:
        audit_event(user_id, "push", project_id, {"force": req.force})
    else:
        audit_event(user_id, "push_denied", project_id, {"force": req.force, "reason": result.get("output", "")[:200]})

    return result


@router.post("/api/projects/{project_id}/git/pull")
async def git_pull(project_id: int, authorization: Optional[str] = Header(None)):
    """Explicit user-initiated pull."""
    user_id = get_user_id_from_token(authorization)
    _require_dedicated(user_id)

    from app import _require_project_owner
    from database_adapter import get_db
    _require_project_owner(project_id, authorization)

    with get_db() as conn:
        row = conn.execute(
            "SELECT project_path, git_credential_id FROM projects WHERE id = %s",
            (project_id,),
        ).fetchone()
    d = row if isinstance(row, dict) else dict(zip(("project_path", "git_credential_id"), row))

    token = GitCredentialService.get_token(user_id, d.get("git_credential_id"))
    transport = GitTransport(user_id, d["project_path"])
    result = transport.pull(token=token)

    if result["success"]:
        audit_event(user_id, "pull", project_id)
    return result
