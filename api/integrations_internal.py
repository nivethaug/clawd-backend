#!/usr/bin/env python3
"""
Internal Integrations Proxy — lets deployed projects call their owner's
connected OAuth integrations (Nango) without any credentials in the
project environment.

Mounted at: /api/integrations (prefix added in app.py → /api/integrations/proxy).

Auth chain (fixture-tested):
    project sends: Authorization: Bearer <SECRET_KEY from its .env>
        → backend reads the PROJECT's .env (same path resolver the env
          dialog uses) → compares with compare_digest
        → resolves project owner from the projects table
        → owner has an active nango_connections row for the provider?
        → nango_client.proxy_request (token lives ONLY inside Nango)
        → provider JSON back to the project

No user tokens, no Nango secrets, no decrypted values ever touch the
project, the prompt, or logs. A project can only ever reach the OAuth
accounts of ITS OWNER (ownership validated on every call).
"""

import hmac
import logging
import os
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from database_adapter import get_db

logger = logging.getLogger("api.integrations.internal")

router = APIRouter()

MAX_ENDPOINT_CHARS = 500


class ProxyRequest(BaseModel):
    provider: str                       # e.g. 'youtube'
    method: str = "GET"                 # GET | POST | PUT | PATCH | DELETE
    endpoint: str                       # provider path, e.g. 'youtube/v3/channels?part=snippet&mine=true'
    mode: Optional[str] = None          # 'resumable_upload' = proxy runs the whole init->PUT dance server-side
    body: Optional[dict] = None         # JSON body for non-GET
    body_base64: Optional[str] = None   # RAW body (binary-safe, e.g. video bytes) — wins over body
    request_headers: Optional[dict] = None  # outbound headers (allowlisted below)
    timeout: int = 30                   # seconds, capped at 300 (large uploads)
    params: Optional[dict] = None       # query params (alternative to embedding ?... in endpoint)

# Outbound header allowlist — credential/cookie headers are NEVER taken
# from callers (the proxy injects auth itself).
_REQUEST_HEADER_ALLOWLIST = frozenset({
    "content-type", "content-length",
    "x-upload-content-type", "x-upload-content-length",
})


def _project_env_secret(project_id: int) -> Optional[str]:
    """Get the project's SECRET_KEY.

    Cross-VPS reality: the .env file only exists on the WORKER VPS, but this
    proxy runs on the MAIN VPS. Priority:
      1. projects.secret_key column (stored at creation by infrastructure_manager)
      2. .env file on disk (same-server fallback for dev/local)
    """
    # 1) DB first — works from any VPS
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT secret_key FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        if row:
            d = dict(row) if not isinstance(row, dict) else row
            if d.get("secret_key"):
                return d["secret_key"]
    except Exception as e:
        logger.warning("[INTEGRATIONS-INTERNAL] DB secret lookup failed for %s: %s", project_id, e)

    # 2) Filesystem fallback (same-server / dev)
    try:
        from env_manager import get_project_env_info
        env_path, _type, _domain, _name = get_project_env_info(project_id)
        if not env_path or not os.path.isfile(env_path):
            return None
        with open(env_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                if key.strip() == "SECRET_KEY":
                    return value.strip().strip("'\"") or None
        return None
    except Exception as e:
        logger.warning("[INTEGRATIONS-INTERNAL] env secret read failed for %s: %s", project_id, e)
        return None


def _resolve_project(project_id: int, bearer: str) -> int:
    """Validate the bearer secret against the project's .env and return the
    OWNER user id. Raises 401/404 on any mismatch."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT user_id FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    owner_id = (dict(row) if not isinstance(row, dict) else row)["user_id"]

    secret = _project_env_secret(project_id)
    if not secret:
        raise HTTPException(status_code=401, detail="Project has no integration secret")
    if not hmac.compare_digest(secret, bearer or ""):
        logger.warning("[INTEGRATIONS-INTERNAL] auth failed for project %s", project_id)
        raise HTTPException(status_code=401, detail="Invalid project secret")

    return owner_id


def _resumable_upload(request, connection_id):
    """Server-side resumable upload: init -> Location -> PUT bytes -> final.

    1. mint the owner's OAuth access token (server-side only)
    2. POST the metadata JSON to <provider_base>/<endpoint> with the
       X-Upload-Content-* headers -> provider returns the session URL in
       the Location header (consumed HERE, never forwarded)
    3. PUT the raw bytes to the session URL (self-authorizing)
    4. return the final response (e.g. the uploaded video resource JSON)
    """
    import base64 as _b64
    import httpx as _httpx
    import json as _json
    from services.integrations import nango_client

    if not request.body_base64:
        raise HTTPException(status_code=400, detail="resumable_upload requires body_base64 (the file bytes)")
    try:
        raw = _b64.b64decode(request.body_base64, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="body_base64 is not valid base64")
    if len(raw) > 256 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File exceeds 256MB cap")

    token = nango_client.get_access_token(connection_id, request.provider)
    if not token:
        raise HTTPException(status_code=502, detail="Could not mint provider access token")

    meta = nango_client.get_provider_metadata(
        nango_client.ENABLED_PROVIDERS.get(request.provider, {}).get("nango_provider", request.provider)
    ) or {}
    base = (meta.get("base_url") or "").rstrip("/")
    if not base:
        raise HTTPException(status_code=502, detail=f"No base_url known for provider '{request.provider}'")

    rh = request.request_headers or {}
    mime = rh.get("X-Upload-Content-Type") or rh.get("Content-Type") or "application/octet-stream"
    timeout_s = max(5, min(int(request.timeout or 280), 300))

    init_headers = {
        "Authorization": f"Bearer {token}",
        "X-Upload-Content-Type": mime,
        "X-Upload-Content-Length": str(len(raw)),
    }
    init = _httpx.post(
        f"{base}/{request.endpoint.lstrip('/')}",
        json=request.body or {},
        headers=init_headers,
        timeout=timeout_s,
    )
    if init.status_code >= 400:
        logger.warning("[INTEGRATIONS-INTERNAL] upload init failed: %s %s", init.status_code, init.text[:300])
        return Response(content=init.text, status_code=init.status_code, media_type="application/json")
    session_url = init.headers.get("location")
    if not session_url:
        return Response(
            content=_json.dumps({"detail": "Provider returned no upload session URL"}),
            status_code=502, media_type="application/json")

    put = _httpx.put(session_url, content=raw, headers={"Content-Type": mime}, timeout=timeout_s)
    logger.info(
        "[INTEGRATIONS-INTERNAL] project upload (%s): init %s -> PUT %s bytes -> %s",
        request.provider, init.status_code, len(raw), put.status_code,
    )
    return Response(content=put.text, status_code=put.status_code, media_type="application/json")


@router.post("/proxy")
async def integrations_proxy(
    request: ProxyRequest,
    request_obj: Request,
    authorization: Optional[str] = Header(None),
    x_project_id: Optional[str] = Header(None),
):
    """Proxy an authenticated provider call for a deployed project.

    The project's own backend calls this with the SECRET_KEY it was
    deployed with. Only providers the project OWNER connected (Settings →
    Integrations) are reachable — the model for all project types.
    """
    from services.integrations import nango_client

    if not nango_client.is_configured():
        raise HTTPException(status_code=503, detail="OAuth integrations not configured")

    # project id: header or query (the project codebase template decides)
    project_id_raw = x_project_id
    if not project_id_raw:
        project_id_raw = request_obj.query_params.get("project_id")
    if not project_id_raw or not str(project_id_raw).isdigit():
        raise HTTPException(status_code=400, detail="X-Project-Id header required")
    project_id = int(project_id_raw)

    bearer = (authorization or "").removeprefix("Bearer ").strip()
    owner_id = _resolve_project(project_id, bearer)

    if request.provider not in nango_client.ENABLED_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Provider '{request.provider}' is not enabled")
    if request.method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise HTTPException(status_code=400, detail="Invalid method")
    if not request.endpoint or len(request.endpoint) > MAX_ENDPOINT_CHARS:
        raise HTTPException(status_code=400, detail="endpoint required (<=500 chars)")

    # Owner's active connection for this provider
    with get_db() as conn:
        row = conn.execute(
            "SELECT connection_id FROM nango_connections "
            "WHERE user_id = ? AND provider_config_key = ?",
            (owner_id, request.provider),
        ).fetchone()
    if not row:
        raise HTTPException(
            status_code=409,
            detail=f"'{request.provider}' is not connected for this account "
                   f"(Settings → Integrations)",
        )
    connection_id = (dict(row) if not isinstance(row, dict) else row)["connection_id"]

    # ---- Resumable upload mode: the full two-step runs INSIDE the proxy.
    # The provider's Location header never crosses to user code (Nango strips
    # it; here we consume it internally), and the OAuth token never leaves
    # the server either. Caller supplies: metadata JSON (body), raw bytes
    # (body_base64), mime via request_headers['X-Upload-Content-Type'] (or
    # Content-Type). Returns the FINAL provider response (video resource).
    if request.mode == "resumable_upload":
        return _resumable_upload(request, connection_id)

    kwargs = {}
    if request.body_base64:
        import base64 as _b64
        try:
            raw = _b64.b64decode(request.body_base64, validate=True)
        except Exception:
            raise HTTPException(status_code=400, detail="body_base64 is not valid base64")
        if len(raw) > 256 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Raw body exceeds 256MB cap")
        kwargs["raw_body"] = raw
    elif request.body is not None and request.method.upper() != "GET":
        kwargs["json"] = request.body
    if request.params:
        kwargs["params"] = request.params
    if request.request_headers:
        kwargs["extra_headers"] = {
            k: v for k, v in request.request_headers.items()
            if k.lower() in _REQUEST_HEADER_ALLOWLIST
        }
    if request.timeout:
        kwargs["timeout_seconds"] = max(5, min(int(request.timeout), 300))

    result = nango_client.proxy_request(
        provider_config_key=request.provider,
        connection_id=connection_id,
        method=request.method.upper(),
        endpoint=request.endpoint,
        **kwargs,
    )

    logger.info(
        "[INTEGRATIONS-INTERNAL] project %s (owner %s) %s %s/%s -> provider %s",
        project_id, owner_id, request.method.upper(), request.provider,
        request.endpoint.split("?")[0][:60], result.get("status"),
    )
    from fastapi.responses import Response, JSONResponse

    if result["status"] >= 500:
        raise HTTPException(status_code=502, detail="Provider call failed")
    # Pass the provider's status + body through untouched, plus filtered
    # provider headers. Content-type follows the PROVIDER's (binary-safe) —
    # never force application/json (video bytes etc.).
    fwd = dict(result.get("headers") or {})
    provider_ct = fwd.pop("content-type", None)
    return Response(
        content=result["body"] if isinstance(result.get("body"), (str, bytes)) else str(result.get("body", "")),
        status_code=result["status"],
        media_type=provider_ct,
        headers=fwd,
    )
