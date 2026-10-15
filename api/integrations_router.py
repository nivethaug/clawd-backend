#!/usr/bin/env python3
"""
Integrations Router — managed integrations for user projects.

Clean separation (see INTEGRATIONS_PLAN.md): all logic lives in
services/integrations/; this router only authenticates, resolves the user
from the token (never client-supplied), enforces project ownership via the
service layer, and maps service results to HTTP codes.

Endpoints (absolute paths; mounted without a prefix in app.py):
  GET    /api/integrations/catalog                      (public metadata)
  POST   /api/integrations/validate                     (server-side credential check)
  GET    /api/projects/{project_id}/integrations        (connected + available)
  POST   /api/projects/{project_id}/integrations/connect
  DELETE /api/projects/{project_id}/integrations/{gi_id}
  POST   /api/projects/{project_id}/integrations/reconcile
"""

import logging
import os
import secrets
from typing import Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from utils.auth_helpers import get_user_id_from_token
from services.integrations import service
from services.integrations.catalog import catalog_metadata, get_def, validate_credentials

logger = logging.getLogger("api.integrations")

router = APIRouter()

_ERROR_STATUS = {
    "not_found": 404,
    "unknown_integration": 404,
    "credential_not_found": 404,
    "env_unavailable": 409,
    "key_conflict": 409,
    "key_conflict_manual": 409,
    "needs_all_keys": 400,
    "single_credential": 400,
    "key_mismatch": 400,
    "invalid_keys": 400,
    "missing_values": 400,
    "validation_failed": 400,
    "decrypt_failed": 500,
}


class ValidateRequest(BaseModel):
    type: str
    values: Dict[str, str]


class SaveCredentialRequest(BaseModel):
    type: str
    values: Dict[str, str]
    label: Optional[str] = None


class ConnectRequest(BaseModel):
    type: str
    gi_ids: List[int]
    swap: bool = False


def _run(result: Dict) -> Dict:
    if result.get("error"):
        raise HTTPException(
            status_code=_ERROR_STATUS.get(result["error"], 400),
            detail=result.get("detail") or result["error"],
        )
    return result


# ======================================================================
# Catalog + validation
# ======================================================================

@router.get("/api/integrations/catalog")
async def get_catalog():
    """Public integration catalog (titles/docs/categories — no secrets)."""
    return {"integrations": catalog_metadata()}


@router.post("/api/integrations/validate")
async def validate(request: ValidateRequest, authorization: Optional[str] = Header(None)):
    """Server-side credential validation for a catalog type. The value is
    used for one provider call and never stored, logged, or echoed."""
    user_id = get_user_id_from_token(authorization)
    if not get_def(request.type):
        raise HTTPException(status_code=404, detail="Unknown integration type")
    # Rate-limit: this endpoint proxies a provider call per attempt.
    try:
        from services.rate_limiter import rate_limit, RateLimitExceeded
        rate_limit(user_id, "general_api")
    except RateLimitExceeded:
        raise HTTPException(status_code=429, detail="Too many validation attempts — slow down.")
    except Exception:
        pass  # limiter unavailable must not block validation
    result = await validate_credentials(request.type, request.values)
    if result.get("valid"):
        logger.info("[INTEGRATIONS] user %s validated %s credential", user_id, request.type)
    else:
        logger.info("[INTEGRATIONS] user %s %s credential invalid", user_id, request.type)
    return result


# ── MCP OAuth connect flow ─────────────────────────────────────────────────

class McpOAuthStartRequest(BaseModel):
    url: str
    label: Optional[str] = None


def _vault_row_suffix(user_id: int, base_key: str) -> str:
    """Next free suffix for base_key / base_key_2 / ... (multi-connection)."""
    from database_adapter import get_db as _get_db
    with _get_db() as conn:
        rows = conn.execute(
            "SELECT key_name FROM global_integrations WHERE user_id = ? "
            "AND (key_name = ? OR left(key_name, ?) = ? || '_') ",
            (user_id, base_key, len(base_key) + 1, base_key)).fetchall()
    names = {(r["key_name"] if isinstance(r, dict) else r[0]) for r in rows}
    if base_key not in names:
        return ""
    n = 2
    while f"{base_key}_{n}" in names:
        n += 1
    return f"_{n}"


@router.post("/api/integrations/mcp/oauth/start")
async def mcp_oauth_start(request: McpOAuthStartRequest,
                          authorization: Optional[str] = Header(None)):
    """Begin the OAuth connect for an MCP server. Returns the authorize URL
    the frontend must open. 409 when the server does NOT require OAuth
    (paste-URL flow applies instead)."""
    user_id = get_user_id_from_token(authorization)
    from services.integrations import mcp_oauth
    from database_adapter import get_db as _get_db

    url = (request.url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL must be http(s)")
    try:
        auth = await mcp_oauth.discover(url)
    except mcp_oauth.OAuthFlowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if auth is None:
        raise HTTPException(
            status_code=409,
            detail="This MCP server does not require OAuth — connect it with "
                   "the URL field instead.")
    try:
        client_id, client_secret = await mcp_oauth.dynamic_register(auth)
    except mcp_oauth.OAuthFlowError as e:
        raise HTTPException(status_code=400, detail=str(e))
    verifier, challenge = mcp_oauth.make_pkce()
    state = secrets.token_urlsafe(32)
    with _get_db() as conn:
        conn.execute(
            "INSERT INTO mcp_oauth_flows (user_id, server_url, "
            "authorization_endpoint, token_endpoint, client_id, "
            "client_secret, code_verifier, state, label) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, url, auth.authorization_endpoint, auth.token_endpoint,
             client_id, client_secret, verifier, state,
             (request.label or "").strip() or None))
        conn.commit()
    return {"authorize_url": mcp_oauth.authorize_url(auth, state, challenge, client_id)}


@router.get("/api/integrations/mcp/oauth/callback")
async def mcp_oauth_callback(state: str, code: Optional[str] = None,
                             error: Optional[str] = None,
                             error_description: Optional[str] = None):
    """AS redirect target: exchange the code, save URL+token vault rows,
    bounce the browser back to the Integrations page with a status flag."""
    import time as _time
    frontend = (os.getenv("FRONTEND_URL") or "https://dreamagent.cloud").rstrip("/")
    from services.integrations import mcp_oauth
    from database_adapter import get_db as _get_db
    from secure_value import encrypt_value

    def _back(flag, detail=""):
        from urllib.parse import quote as _q
        extra = f"&detail={_q(detail[:200])}" if detail else ""
        return RedirectResponse(f"{frontend}/app/integrations?mcp_oauth={flag}{extra}")

    if error:
        return _back("denied", error_description or error)
    if not code:
        return _back("error", "missing code")

    with _get_db() as conn:
        row = conn.execute(
            "SELECT * FROM mcp_oauth_flows WHERE state = ? AND status = 'pending'",
            (state,)).fetchone()
    if not row:
        return _back("error", "unknown or expired connect (15-minute window)")
    flow = dict(row) if not isinstance(row, dict) else row
    if _time.time() - (flow.get("created_at").timestamp()
                       if hasattr(flow.get("created_at"), "timestamp") else 0) > mcp_oauth.FLOW_TTL_SECONDS:
        return _back("error", "connect expired — try again")

    auth = mcp_oauth.ServerAuth(
        server_url=flow["server_url"],
        authorization_endpoint=flow["authorization_endpoint"],
        token_endpoint=flow["token_endpoint"])
    try:
        doc = await mcp_oauth.exchange_code(
            auth, flow["client_id"], flow.get("client_secret"),
            code, flow["code_verifier"])
    except mcp_oauth.OAuthFlowError as e:
        return _back("error", str(e))

    # Save: MCP_SERVER_URL[n] + MCP_TOKEN[n] vault rows (verified=TRUE).
    suffix = _vault_row_suffix(int(flow["user_id"]), "MCP_SERVER_URL")
    title = flow.get("label") or "MCP Server (OAuth)"
    token_json = mcp_oauth.token_row_value(doc, auth, flow["client_id"],
                                            flow.get("client_secret"))
    with _get_db() as conn:
        for key, plain in ((f"MCP_SERVER_URL{suffix}", flow["server_url"]),
                           (f"MCP_TOKEN{suffix}", token_json)):
            conn.execute(
                """INSERT INTO global_integrations
                   (user_id, token_type, key_name, value_encrypted, verified,
                    title, docs_url, category, created_at, updated_at)
                   VALUES (?, 'other', ?, ?, TRUE, ?, ?, 'Tools', NOW(), NOW())
                   ON CONFLICT (user_id, key_name) DO UPDATE SET
                     value_encrypted = EXCLUDED.value_encrypted,
                     verified = TRUE, updated_at = NOW()""",
                (int(flow["user_id"]), key, encrypt_value(plain),
                 title, "https://modelcontextprotocol.io"))
        conn.execute(
            "UPDATE mcp_oauth_flows SET status='completed', completed_at=NOW() "
            "WHERE id = ?", (flow["id"],))
        conn.commit()
    logger.info("[MCP-OAUTH] user %s connected MCP server via OAuth", flow["user_id"])
    return _back("connected", title)


@router.post("/api/integrations/save")
async def save_credential(request: SaveCredentialRequest,
                          authorization: Optional[str] = Header(None)):
    """Validate-then-save in one server-side call. verified is computed by
    the server (the generic GI endpoint forces verified=False for 'other'
    types). Value is encrypted immediately; never returned or logged."""
    user_id = get_user_id_from_token(authorization)
    if not get_def(request.type):
        raise HTTPException(status_code=404, detail="Unknown integration type")
    try:
        from services.rate_limiter import rate_limit, RateLimitExceeded
        rate_limit(user_id, "general_api")
    except RateLimitExceeded:
        raise HTTPException(status_code=429, detail="Too many attempts — slow down.")
    except Exception:
        pass
    return _run(await service.save_catalog_credential(
        user_id, request.type, request.values, request.label))


# ======================================================================
# Project-scoped operations
# ======================================================================

@router.get("/api/projects/{project_id}/integrations")
async def list_integrations(project_id: int, authorization: Optional[str] = Header(None)):
    user_id = get_user_id_from_token(authorization)
    return _run(service.list_project_integrations(project_id, user_id))


@router.post("/api/projects/{project_id}/integrations/connect")
async def connect(request: ConnectRequest, project_id: int,
                  authorization: Optional[str] = Header(None)):
    user_id = get_user_id_from_token(authorization)
    if not request.gi_ids:
        raise HTTPException(status_code=400, detail="gi_ids required")
    return _run(service.connect(project_id, user_id, request.type,
                                request.gi_ids, swap=request.swap))


@router.delete("/api/projects/{project_id}/integrations/{gi_id}")
async def disconnect(project_id: int, gi_id: int,
                     authorization: Optional[str] = Header(None)):
    user_id = get_user_id_from_token(authorization)
    return _run(service.disconnect(project_id, user_id, gi_id))


@router.post("/api/projects/{project_id}/integrations/reconcile")
async def reconcile(project_id: int, authorization: Optional[str] = Header(None)):
    """Remove .env keys left by deleted/rotated credentials (lazy cleanup)."""
    user_id = get_user_id_from_token(authorization)
    return _run(service.reconcile(project_id, user_id))
