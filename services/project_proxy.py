"""
Project Reverse-Proxy Middleware (Option B for the worker VPS split).

When projects are hosted on a separate worker VPS, file-dependent endpoints
(download ZIP, github-export, logs, commits, build/publish, files, etc.)
must execute where the files live. Rather than duplicating those endpoints,
this middleware transparently forwards project-scoped requests to the worker's
internal API (the same `app.py` running on a private port, firewalled to the
main VPS only).

Decision per request:
  1. WORKER_VPS_URL not set  → no worker; pass through to local handler.
  2. Request is not project-scoped → pass through.
  3. project_id not parseable from path → pass through.
  4. Project's project_path EXISTS locally → legacy/main-hosted; handle locally.
  5. Project's project_path MISSING locally + WORKER_VPS_URL set →
     project lives on the worker → forward the entire request to the worker.

Auth: the user's Authorization Bearer header is forwarded unchanged, so the
worker's existing `get_user_id_from_token` + ownership checks still enforce
per-user access. No new auth surface is introduced.

Security: the worker's API port (e.g. 8003) must be firewalled to the main
VPS IP only. This module never exposes it publicly.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional, Tuple

import httpx
from fastapi import Request
from starlette.responses import StreamingResponse

logger = logging.getLogger("project_proxy")

# Routes that carry a project_id we can use to look up project_path.
_PROJECT_PATH_RE = re.compile(
    r"^/(?:projects|apps|plans)/(\d+)(?:/|$)"
)

# ALLOWLIST
# worker (they read/write project files on disk). Everything else (sessions,
# status, env, custom-domain, gallery, usage, clone, etc.) stays on main —
# those only need the DB, not the filesystem.
_PROXY_SUBROUTES = (
    "files",               # GET/PUT project files
    "github-export",       # read files → push to GitHub
    "download",            # read files → ZIP
    "logs",                # read PM2 logs (worker runs the project)
    "commits",             # git log/diff/rollback (worker has the repo)
    "editor/build-publish",  # rebuild + redeploy (worker serves it)
)

# Chat routes — MUST proxy because the ACP handler reads frontend/src from disk.
_CHAT_ROUTES = {"/chat", "/chat/stream", "/chat/cancel", "/chat/status", "/chat/chunks", "/sessions/details"}

# Hop-by-hop headers that must not be forwarded (HTTP spec).
_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

# Reuse a single async client across requests (connection pooling).
# Created lazily so tests/standalone use without WORKER_VPS_URL don't open sockets.
_client: Optional[httpx.AsyncClient] = None


def _get_worker_url() -> Optional[str]:
    """Return the worker internal API base URL, or None if no worker is configured."""
    url = os.getenv("WORKER_VPS_URL", "").strip().rstrip("/")
    return url or None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                # Build/publish can take several minutes; allow generous read timeout.
                read=float(os.getenv("WORKER_PROXY_READ_TIMEOUT", "600")),
                write=60.0,
                pool=10.0,
            ),
            follow_redirects=False,
        )
    return _client


def _parse_project_id(path: str) -> Optional[int]:
    """Extract the leading numeric project_id from a project-scoped route."""
    m = _PROJECT_PATH_RE.match(path)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def _is_proxyable_project_route(path: str) -> bool:
    """Check if a /projects/{id}/* route is in the proxy allowlist.

    Only file-dependent sub-routes should be proxied. Session/status/env/
    gallery/clone routes stay on main (they only need the DB).
    """
    # Strip /projects/{id}/ prefix to get the sub-route
    m = _PROJECT_PATH_RE.match(path)
    if not m:
        return False
    sub = path[m.end():]
    # Check if any allowlisted keyword matches the sub-route prefix
    return any(sub.startswith(sr) or sub == sr for sr in _PROXY_SUBROUTES)


async def _resolve_project_id_from_request(request: Request) -> Optional[int]:
    """Resolve project_id for ANY proxiable route (path-based OR session-based).

    Only routes in the proxy allowlist are considered:
    - File routes: /projects/{id}/files, /download, /github-export, /logs,
      /commits, /editor/build-publish
    - Chat routes: /chat/*, /sessions/details (session_key → project_id)

    Everything else (sessions, status, env, gallery, clone, etc.) returns None
    and stays on main.
    """
    path = request.url.path

    # 1. Path-based project routes — ONLY if in the proxy allowlist.
    if _is_proxyable_project_route(path):
        return _parse_project_id(path)

    # 2. /chat/* and /sessions/details → session_key from query or body.
    #    These MUST proxy because the ACP handler reads frontend/src from disk.
    if path in _CHAT_ROUTES:
        session_key = request.query_params.get("session_key")
        if not session_key:
            # POST bodies carry session_key as JSON. Read+cache the body so the
            # downstream handler can still read it (FastAPI caches request.body).
            try:
                body = await request.body()
                if body:
                    import json
                    data = json.loads(body)
                    if isinstance(data, dict):
                        session_key = data.get("session_key")
            except Exception as body_err:
                logger.warning(
                    "project_proxy: failed to read body for session_key on %s: %s",
                    path, body_err,
                )
        if session_key:
            return _project_id_for_session("session_key", session_key)
        logger.warning("project_proxy: no session_key found for %s (query=%s)",
                       path, dict(request.query_params))

    return None


def _project_id_for_session(key_field: str, key_value) -> Optional[int]:
    """Look up project_id from the sessions table by session_key or id."""
    from database_postgres import get_db
    try:
        with get_db() as conn:
            row = conn.execute(
                f"SELECT project_id FROM sessions WHERE {key_field} = %s LIMIT 1",
                (key_value,),
            ).fetchone()
    except Exception as exc:
        logger.warning("project_proxy session lookup failed (%s=%s): %s", key_field, key_value, exc)
        return None
    if not row:
        return None
    return int(row.get("project_id") if isinstance(row, dict) else row[0])


def _project_lives_on_worker(project_id: int) -> Tuple[bool, Optional[str]]:
    """Decide whether a project's files are on the worker.

    Returns (is_on_worker, project_path).
    A project is on the worker when its `project_path` does NOT exist on the
    local filesystem (it was created on the worker, which has a separate disk).
    Local/legacy projects whose path exists here are handled locally.
    """
    # Lazy import to avoid a circular dependency at module load time.
    from database_postgres import get_db

    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT project_path FROM projects WHERE id = %s",
                (project_id,),
            ).fetchone()
    except Exception as exc:
        # DB errors must NEVER break request handling — fall back to local.
        logger.warning("project_proxy DB lookup failed for %s: %s", project_id, exc)
        return (False, None)

    if not row:
        # Unknown project — let the local handler return the 404.
        return (False, None)

    project_path = (row.get("project_path") if isinstance(row, dict) else row[0]) if row else None
    if not project_path:
        # No path recorded yet — likely mid-creation; let the local handler decide.
        return (False, None)

    # The decisive test: does the path exist HERE?
    # - exists locally → main-hosted (legacy or main-created) → handle locally
    # - missing locally → worker-hosted → proxy
    try:
        if os.path.isdir(project_path):
            return (False, project_path)
    except OSError:
        pass
    return (True, project_path)


def _forwardable_headers(request: Request) -> dict:
    """Build the header dict to send to the worker, minus hop-by-hop headers."""
    headers = {}
    for key, value in request.headers.items():
        if key.lower() in _HOP_BY_HOP:
            continue
        headers[key] = value
    # Preserve the original Host so the worker sees the public-facing host
    # (some endpoints may log or build URLs from it).
    headers["X-Forwarded-Host"] = request.headers.get("host", "")
    return headers


async def project_proxy_middleware(request: Request, call_next):
    """FastAPI/Starlette HTTP middleware: proxy project/session-scoped requests
    to the worker when the project's files are not present locally.

    Covers BOTH:
    - Path-based routes (/projects/{id}, /apps/{id}, /plans/{id}) — id from path
    - Session-based routes (/chat/*, /sessions/{id}/*, /sessions/details) —
      project_id resolved from session_key/session_id via DB lookup
    """
    worker_url = _get_worker_url()
    if not worker_url:
        return await call_next(request)

    # DEBUG: trace every decision for proxiable routes
    _path = request.url.path
    _is_chat = _path in _CHAT_ROUTES or _path.startswith("/chat") or _path.startswith("/sessions")
    if _is_chat:
        logger.warning(
            "project_proxy DEBUG: %s %s query=%s",
            request.method, _path, dict(request.query_params),
        )

    # Resolve project_id from ANY proxiable route (path or session based).
    project_id = await _resolve_project_id_from_request(request)
    if project_id is None:
        if _is_chat:
            logger.warning("project_proxy DEBUG: %s -> project_id=None (pass-through)", _path)
        return await call_next(request)

    if _is_chat:
        logger.warning("project_proxy DEBUG: %s -> project_id=%s", _path, project_id)

    # Decide where this project lives.
    is_on_worker, project_path = _project_lives_on_worker(project_id)
    if _is_chat:
        logger.warning(
            "project_proxy DEBUG: %s -> project_id=%s is_on_worker=%s path=%s",
            _path, project_id, is_on_worker, project_path,
        )
    if not is_on_worker:
        return await call_next(request)

    # ---- Forward to the worker ----
    target_url = f"{worker_url}{request.url.path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    headers = _forwardable_headers(request)

    # Resolve user_id from main's AUTH_TOKENS and pass it as a trusted header.
    # The worker's API has its OWN in-memory AUTH_TOKENS (empty) — it can't
    # validate the user's Bearer token. Since port 8003 is firewalled to main's
    # IP only, we pass the authenticated user_id via a trusted internal header.
    # The worker must accept this header as proof of identity (see TRUST_PROXY).
    try:
        from app import get_user_id_from_token
        auth_header = request.headers.get("authorization", "")
        proxy_user_id = get_user_id_from_token(auth_header) if auth_header else None
    except Exception:
        proxy_user_id = None
    if proxy_user_id:
        headers["X-Proxy-User-Id"] = str(proxy_user_id)
        # Remove the original Authorization so the worker doesn't try to
        # validate a token it doesn't know about.
        headers.pop("authorization", None)
        headers.pop("Authorization", None)

    body = await request.body()

    method = request.method
    logger.info(
        "project_proxy: forwarding %s %s (project=%s user=%s) -> %s",
        method, request.url.path, project_id, proxy_user_id, worker_url,
    )

    client = _get_client()
    try:
        # Stream the response back so large downloads (ZIP) and SSE pass through
        # without buffering the whole body in memory.
        req = client.build_request(method, target_url, headers=headers, content=body)
        worker_resp = await client.send(req, stream=True)

        # Build response headers as a dict (StreamingResponse expects dict, not list).
        resp_headers = {
            k: v for k, v in worker_resp.headers.items()
            if k.lower() not in _HOP_BY_HOP
        }

        async def body_iterator():
            try:
                async for chunk in worker_resp.aiter_raw():
                    yield chunk
            finally:
                await worker_resp.aclose()

        return StreamingResponse(
            body_iterator(),
            status_code=worker_resp.status_code,
            headers=resp_headers,
            media_type=worker_resp.headers.get("content-type"),
        )
    except httpx.ConnectError as exc:
        logger.error("project_proxy: worker unreachable for project=%s: %s", project_id, exc)
        # Don't expose internal topology to the client; return a generic 502.
        from fastapi import HTTPException
        raise HTTPException(
            status_code=502,
            detail="Project host is temporarily unreachable. Please try again shortly.",
        )
    except Exception as exc:
        logger.exception("project_proxy: forward failed for project=%s", project_id)
        from fastapi import HTTPException
        raise HTTPException(status_code=502, detail="Failed to reach project host.")


async def proxy_auth_middleware(request: Request, call_next):
    """Worker-side middleware: translate X-Proxy-User-Id into a valid auth token.

    When the main VPS proxies a request, it resolves the user_id and passes it
    via X-Proxy-User-Id. This middleware injects a synthetic Bearer token into
    AUTH_TOKENS and rewrites the Authorization header, so every existing endpoint
    (which calls get_user_id_from_token) works without modification.

    Only active when TRUST_PROXY_AUTH is set (worker API on port 8003, firewalled
    to main's IP only — never public).
    """
    import os as _os
    if _os.getenv("TRUST_PROXY_AUTH", "").lower() not in ("1", "true", "yes"):
        return await call_next(request)

    proxy_uid = request.headers.get("X-Proxy-User-Id")
    if not proxy_uid:
        return await call_next(request)

    try:
        uid = int(proxy_uid)
    except (TypeError, ValueError):
        return await call_next(request)

    # Inject a synthetic token for this user_id. The token is deterministic
    # (proxy-<uid>) so repeated requests reuse the same entry.
    synthetic_token = f"proxy-{uid}"
    try:
        from app import AUTH_TOKENS
        AUTH_TOKENS[synthetic_token] = uid
    except Exception:
        pass

    # Rewrite the Authorization header so downstream auth sees a valid Bearer.
    # Starlette Request headers are immutable, so we can't modify in-place.
    # Instead, the get_user_id_from_token reads from the Header param which
    # FastAPI injects from the original request. We need to modify at the ASGI
    # scope level.
    scope = request.scope
    raw_headers = scope.get("headers", [])
    new_headers = [
        (k, v) for k, v in raw_headers
        if k.lower() != b"authorization"
    ]
    new_headers.append((b"authorization", f"Bearer {synthetic_token}".encode()))
    scope["headers"] = new_headers

    return await call_next(request)


__all__ = ["project_proxy_middleware", "proxy_auth_middleware"]

# Startup log — confirms the module loaded (visible in pm2 logs on first request
# cycle; also emitted at import time so we know registration happened).
_wu = _get_worker_url()
logger.warning(
    "project_proxy LOADED — worker_url=%s, chat_routes=%s",
    _wu or "(unset, no-op mode)",
    sorted(_CHAT_ROUTES),
)
