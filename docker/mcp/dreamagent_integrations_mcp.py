#!/usr/bin/env python3
"""
DreamAgent Integrations MCP server (stdio, ZERO dependencies).

Exposes the project owner's connected OAuth integrations (Nango: Notion,
X/Twitter, YouTube, ...) as MCP tools so Claude agents can call them
directly — no credentials in project code, no .env reads.

Auth model (same trust chain as the integrations proxy):
  - The server locates the PROJECT's .env (walks up from its CWD — the
    agent always runs with cwd inside the project) and reads SECRET_KEY.
  - SECRET_KEY resolves the project server-side; the project can only ever
    reach the OAuth accounts of ITS OWNER.
  - The OAuth tokens themselves never leave the backend/Nango.

Protocol: MCP stdio transport — newline-delimited JSON-RPC 2.0 on
stdin/stdout. All logs go to stderr. Stdlib only (urllib for HTTP).
"""

import json
import logging
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

logging.basicConfig(
    level=logging.INFO,
    format="[DA-INTEGRATIONS-MCP] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

API_BASE = os.environ.get("DREAMAGENT_API_URL", "https://api.dreamagent.cloud").rstrip("/")

MAX_RESPONSE_CHARS = 20_000  # keep provider payloads from flooding the context


# ────────────────────────────────────────────────────────────────────
# Project .env discovery — the agent's CWD is inside the project tree
# (/workspace/<type>/<proj>/, .../frontend, .../backend)
# ────────────────────────────────────────────────────────────────────

def _read_env_file(path: str) -> Dict[str, str]:
    env: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip().strip("'\"")
    except OSError:
        pass
    return env


def _project_env() -> Dict[str, str]:
    """Find the project's .env from the agent's CWD.

    Layout per project type (env_manager): website → backend/.env,
    telegram → telegram/.env, discord → discord/.env, scheduler → .env.
    The agent's cwd can be anywhere in the tree (commonly
    <project>/frontend/src), so walk UP several levels, checking both
    .env and backend/.env at each step. First file with SECRET_KEY wins.
    """
    import pathlib

    start = pathlib.Path(os.environ.get("DA_MCP_PROJECT_DIR") or os.getcwd()).resolve()
    dirs = [start] + list(start.parents)[:6]
    candidates = []
    for d in dirs:
        candidates.append(d / "backend" / ".env")
        candidates.append(d / ".env")
    # shallowest backend/.env first at each level, then that level's .env
    for cand in candidates:
        if cand.is_file():
            env = _read_env_file(str(cand))
            if env.get("SECRET_KEY"):
                log.info("project env found: %s", cand)
                return env
    log.warning(
        "no project .env with SECRET_KEY found (walked up from %s)", start
    )
    return {}


_ENV = _project_env()
_SECRET = _ENV.get("SECRET_KEY") or os.environ.get("SECRET_KEY") or ""
_PROJECT_ID = _ENV.get("PROJECT_ID") or os.environ.get("PROJECT_ID") or ""

_state: Dict[str, Any] = {"project_id": _PROJECT_ID or None, "providers": None}


# ────────────────────────────────────────────────────────────────────
# Backend calls (project-secret auth)
# ────────────────────────────────────────────────────────────────────

def _api_get(path: str) -> Any:
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        headers={"Authorization": f"Bearer {_SECRET}"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _api_post(path: str, payload: dict, timeout: int = 60) -> Dict[str, Any]:
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {_SECRET}",
            "Content-Type": "application/json",
            "X-Project-Id": str(_state.get("project_id") or ""),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return {"status": resp.status, "body": body[:MAX_RESPONSE_CHARS]}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:MAX_RESPONSE_CHARS]
        return {"status": e.code, "body": body, "error": True}
    except urllib.error.URLError as e:
        return {"status": 0, "body": f"network error: {e}", "error": True}


def _resolve() -> Dict[str, Any]:
    """Resolve project_id + connected providers from SECRET_KEY (cached)."""
    if _state.get("providers") is not None and _state.get("project_id"):
        return _state
    if not _SECRET:
        _state["providers"] = []
        _state["resolve_error"] = "No SECRET_KEY found in the project environment"
        return _state
    try:
        info = _api_get("/api/integrations/mcp-resolve")
        _state["project_id"] = str(info.get("project_id") or _state.get("project_id") or "")
        _state["providers"] = info.get("providers") or []
    except Exception as e:
        log.warning("resolve failed: %s", e)
        _state["providers"] = []
        _state["resolve_error"] = str(e)
    return _state


# ────────────────────────────────────────────────────────────────────
# Tools
# ────────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "integrations_status",
        "description": (
            "List the OAuth integrations connected for this project's owner "
            "(e.g. notion, x/twitter, youtube) and whether the MCP bridge is "
            "authenticated. Call this first when a task mentions Notion, X, "
            "YouTube, or any connected service."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "integrations_request",
        "description": (
            "Call a connected OAuth provider's API on behalf of the project "
            "owner (auth handled server-side — never ask for tokens). "
            "Providers: notion, x/twitter (free tier: post tweets + own "
            "profile only; max_results 5-100), youtube. Examples: "
            "notion: POST v1/databases/{id}/query; "
            "x: GET 2/users/me?user.fields=public_metrics, POST 2/tweets {\"text\":\"...\"}; "
            "youtube: GET youtube/v3/search?part=snippet&channelId={id}&order=date&maxResults=10."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "provider": {"type": "string", "description": "notion | x | youtube (the connected provider key)"},
                "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"], "description": "HTTP method (default GET)"},
                "endpoint": {"type": "string", "description": "Provider API path after its base URL, e.g. 'v1/pages/{page_id}'"},
                "body": {"type": "object", "description": "JSON body for non-GET requests"},
                "account": {"type": "string", "description": "Optional account label / connection id when several accounts are connected"},
                "timeout": {"type": "integer", "description": "Seconds (default 60, max 120)"},
            },
            "required": ["provider", "endpoint"],
            "additionalProperties": False,
        },
    },
]


def _tool_integrations_status(_: dict) -> dict:
    st = _resolve()
    providers = st.get("providers")
    if providers is None:
        return {"authenticated": False, "error": st.get("resolve_error") or "no SECRET_KEY in project env"}
    return {
        "authenticated": True,
        "project_id": st.get("project_id"),
        "connected_providers": providers,
        "hint": "Call integrations_request with provider=<key> to use one.",
    }


def _tool_integrations_request(args: dict) -> dict:
    st = _resolve()
    if not st.get("project_id"):
        return {"error": True, "text": st.get("resolve_error") or "Project not authenticated — no SECRET_KEY"}
    payload = {
        "provider": str(args.get("provider", "")).strip(),
        "method": str(args.get("method", "GET")).upper(),
        "endpoint": str(args.get("endpoint", "")).lstrip("/"),
        "account": args.get("account"),
        "timeout": max(5, min(int(args.get("timeout") or 60), 120)),
    }
    if not payload["provider"] or not payload["endpoint"]:
        return {"error": True, "text": "provider and endpoint are required"}
    body = args.get("body")
    if body is not None and payload["method"] != "GET":
        payload["body"] = body
    result = _api_post("/api/integrations/proxy", payload, timeout=payload["timeout"] + 10)
    text = result.get("body", "")
    out = f"HTTP {result.get('status')}\n{text}"
    return {"content": [{"type": "text", "text": out[:MAX_RESPONSE_CHARS]}], "isError": bool(result.get("error"))}


_TOOL_HANDLERS = {
    "integrations_status": _tool_integrations_status,
    "integrations_request": _tool_integrations_request,
}


# ────────────────────────────────────────────────────────────────────
# MCP stdio loop — newline-delimited JSON-RPC 2.0
# ────────────────────────────────────────────────────────────────────

SERVER_INFO = {"name": "dreamagent-integrations", "version": "1.0.0"}
PROTOCOL_VERSION = "2024-11-05"


def _handle(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = msg.get("method", "")
    mid = msg.get("id")
    is_notification = mid is None

    if method == "initialize":
        client_version = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL_VERSION
        return {
            "jsonrpc": "2.0", "id": mid,
            "result": {
                "protocolVersion": client_version,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name", "")
        args = params.get("arguments") or {}
        handler = _TOOL_HANDLERS.get(name)
        if not handler:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unknown tool: {name}"}}
        try:
            out = handler(args)
        except Exception as e:
            log.exception("tool %s failed", name)
            out = {"error": True, "text": f"tool failed: {e}"}
        if "content" not in out:
            out = {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}]}
        return {"jsonrpc": "2.0", "id": mid, "result": out}

    if is_notification:
        return None  # notifications/initialized etc. — nothing to answer
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Unknown method: {method}"}}


def main() -> None:
    log.info("starting (api=%s, secret=%s)", API_BASE, "present" if _SECRET else "MISSING")
    # NOTE: readline() (NOT `for line in sys.stdin`) — the iterator's
    # read-ahead buffer deadlocks line-protocol sessions over pipes.
    while True:
        raw = sys.stdin.readline()
        if not raw:
            log.info("stdin EOF — exiting")
            break
        raw = raw.strip()
        if not raw:
            continue
        log.info("recv: %.120s", raw)
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("unparseable message: %.80s", raw)
            continue
        try:
            resp = _handle(msg)
            log.info("handled: %.60s -> %s", msg.get("method", ""), "notification" if resp is None else "response")
        except Exception as e:
            log.exception("handler crashed")
            resp = {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32603, "message": str(e)}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    log.info("stdin closed — exiting")


if __name__ == "__main__":
    main()
