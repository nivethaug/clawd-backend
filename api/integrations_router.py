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
from typing import Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
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
