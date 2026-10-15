"""OAuth 2.1 connect flow for MCP servers (Integrations → MCP Server).

Streamable-HTTP MCP servers may require OAuth (MCP auth spec). Flow:

  1. start_flow(url): probe the server → 401 → discover the authorization
     server (RFC 9727 resource metadata, with same-origin fallback) →
     dynamic client registration (RFC 7591) when the AS offers it →
     PKCE S256 pair + state stored in mcp_oauth_flows → authorize URL.
  2. The user authorizes; the AS redirects to our callback.
  3. complete_flow(code, state): exchange code + PKCE at the token endpoint,
     then save TWO vault rows: MCP_SERVER_URL[n] (the server URL) and
     MCP_TOKEN[n] (encrypted JSON {access_token, refresh_token, expires_at,
     token_endpoint, client_id, client_secret}).
  4. tools-api sends the access token as a Bearer header; on expiry it asks
     the backend to refresh (refresh_flow) using the stored refresh token.

Tokens never leave the encrypted vault + localhost hops. Nothing is logged
with token values.
"""

import base64
import hashlib
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode, urlparse

import httpx

logger = logging.getLogger("integrations.mcp_oauth")

PROBE_TIMEOUT = 10.0
FLOW_TTL_SECONDS = 15 * 60
PUBLIC_API_BASE = os.getenv("PUBLIC_API_BASE", "https://api.dreamagent.cloud").rstrip("/")
# Frontend origin the OAuth callback bounces to. Deliberately NOT
# FRONTEND_URL — that legacy var carried a dead domain and the bounce
# landed on DNS_PROBE_FINISHED_NXDOMAIN (2026-10-15).
PUBLIC_SITE_URL = os.getenv("PUBLIC_SITE_URL", "https://dreamagent.cloud").rstrip("/")
REDIRECT_URI = f"{PUBLIC_API_BASE}/api/integrations/mcp/oauth/callback"
CLIENT_NAME = "DreamAgent"


class OAuthFlowError(RuntimeError):
    """User-safe error (shown in the UI; never carries token values)."""


@dataclass
class ServerAuth:
    """Discovered auth endpoints for one MCP server."""
    server_url: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: Optional[str] = None
    scopes_supported: Optional[list] = None


# ── discovery ───────────────────────────────────────────────────────────────

def _well_known_variants(base: str) -> list:
    return [
        f"{base}/.well-known/oauth-authorization-server",
        f"{base}/.well-known/openid-configuration",
    ]


def _guard_ssrf(url: str) -> None:
    """Same policy as the catalog validator: public http(s) hosts only —
    no loopback/private/link-local/platform targets (the OAuth discovery
    fetches user-supplied URLs from THIS server)."""
    import ipaddress
    import socket
    from urllib.parse import urlparse as _up

    p = _up(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise OAuthFlowError("URL must be http(s) with a host")
    try:
        infos = socket.getaddrinfo(p.hostname, None)
    except socket.gaierror:
        raise OAuthFlowError(f"Cannot resolve server host: {p.hostname}")
    for info in infos:
        ip = info[4][0]
        addr = ipaddress.ip_address(ip)
        if (addr.is_loopback or addr.is_private or addr.is_link_local
                or addr.is_reserved or ip in ("195.200.14.37", "187.55.225.39")):
            raise OAuthFlowError("Server points at a private/platform address")


async def discover(server_url: str) -> Optional[ServerAuth]:
    """Probe an MCP server for OAuth requirements. None = no OAuth needed."""
    url = (server_url or "").strip()
    _guard_ssrf(url)
    server_url = url
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT, follow_redirects=True) as client:
        try:
            r = await client.post(server_url, headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                           "clientInfo": {"name": "dreamagent", "version": "1.0"}}})
        except httpx.HTTPError as exc:
            raise OAuthFlowError(f"MCP server unreachable: {type(exc).__name__}")
        if r.status_code != 401:
            return None

        as_bases = []
        www = r.headers.get("www-authenticate") or ""
        if "resource_metadata" in www:
            rm_url = www.split("resource_metadata=", 1)[1].strip().strip('"').split(",", 1)[0]
            try:
                rm = await client.get(rm_url)
                if rm.status_code == 200:
                    as_bases = list((rm.json() or {}).get("authorization_servers") or [])
            except Exception:
                pass
        if not as_bases:
            p = urlparse(server_url)
            as_bases = [f"{p.scheme}://{p.netloc}"]

        for base in as_bases:
            for wk in _well_known_variants(base.rstrip("/")):
                try:
                    md = await client.get(wk)
                except Exception:
                    continue
                if md.status_code != 200:
                    continue
                doc = md.json() or {}
                auth_ep = doc.get("authorization_endpoint")
                token_ep = doc.get("token_endpoint")
                if auth_ep and token_ep:
                    return ServerAuth(
                        server_url=server_url,
                        authorization_endpoint=auth_ep,
                        token_endpoint=token_ep,
                        registration_endpoint=doc.get("registration_endpoint"),
                        scopes_supported=doc.get("scopes_supported"),
                    )
        raise OAuthFlowError(
            "This MCP server requires OAuth but publishes no authorization "
            "server metadata — paste its URL with a token instead.")


# ── dynamic client registration ─────────────────────────────────────────────

async def dynamic_register(auth: ServerAuth) -> Tuple[str, Optional[str]]:
    """RFC 7591 registration → (client_id, client_secret|None)."""
    if not auth.registration_endpoint:
        # Public client assumption: PKCE-only, fixed well-known client id.
        return "dreamagent", None
    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT) as client:
        r = await client.post(auth.registration_endpoint, json={
            "client_name": CLIENT_NAME,
            "redirect_uris": [REDIRECT_URI],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        })
        if r.status_code not in (200, 201):
            raise OAuthFlowError(
                "The MCP server's OAuth provider rejected client registration "
                f"(HTTP {r.status_code}) — it may not allow external clients.")
        doc = r.json() or {}
        cid = doc.get("client_id")
        if not cid:
            raise OAuthFlowError("OAuth provider returned no client_id")
        return cid, doc.get("client_secret")


# ── PKCE helpers ────────────────────────────────────────────────────────────

def make_pkce() -> Tuple[str, str]:
    """(verifier, challenge) — S256."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def authorize_url(auth: ServerAuth, state: str, challenge: str,
                  client_id: str) -> str:
    q = urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    })
    sep = "&" if "?" in auth.authorization_endpoint else "?"
    return f"{auth.authorization_endpoint}{sep}{q}"


# ── token exchange / refresh ────────────────────────────────────────────────

async def exchange_code(auth: ServerAuth, client_id: str,
                        client_secret: Optional[str], code: str,
                        verifier: str) -> Dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "code_verifier": verifier,
    }
    headers = {}
    if client_secret:
        data["client_secret"] = client_secret
    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT) as client:
        r = await client.post(auth.token_endpoint, data=data, headers=headers)
    doc = _token_response(r)
    return doc


async def refresh_token(token_endpoint: str, client_id: str,
                        client_secret: Optional[str],
                        refresh_tok: str) -> Dict[str, Any]:
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_tok,
        "client_id": client_id,
    }
    if client_secret:
        data["client_secret"] = client_secret
    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT) as client:
        r = await client.post(token_endpoint, data=data)
    return _token_response(r)


def _token_response(r: "httpx.Response") -> Dict[str, Any]:
    if r.status_code != 200:
        raise OAuthFlowError(
            f"OAuth token endpoint returned HTTP {r.status_code} — "
            "re-connect the MCP server.")
    doc = r.json() or {}
    if not doc.get("access_token"):
        raise OAuthFlowError("OAuth token response missing access_token")
    return doc


def token_row_value(doc: Dict[str, Any], auth: ServerAuth,
                    client_id: str, client_secret: Optional[str]) -> str:
    """The encrypted-vault payload for the MCP_TOKEN[n] row (JSON string)."""
    expires_in = int(doc.get("expires_in") or 0)
    return json.dumps({
        "access_token": doc.get("access_token", ""),
        "refresh_token": doc.get("refresh_token", ""),
        "expires_at": int(time.time()) + expires_in if expires_in else None,
        "token_endpoint": auth.token_endpoint,
        "client_id": client_id,
        "client_secret": client_secret,
    })


def parse_sse_or_json(r: "httpx.Response") -> Optional[Dict[str, Any]]:
    """Parse an MCP response body: JSON, or SSE with JSON data frames."""
    import json as _json
    ctype = (r.headers.get("content-type") or "").lower()
    if "event-stream" not in ctype:
        try:
            doc = r.json()
            return doc if isinstance(doc, dict) else None
        except Exception:
            return None
    msgs, data = [], []
    for line in r.text.splitlines():
        if line.startswith("data:"):
            data.append(line[5:].strip())
        elif not line.strip() and data:
            try:
                msgs.append(_json.loads("\n".join(data)))
            except Exception:
                pass
            data = []
    if data:
        try:
            msgs.append(_json.loads("\n".join(data)))
        except Exception:
            pass
    for m in reversed(msgs):
        if isinstance(m, dict):
            return m
    return None


def probe_server_name(url: str, access_token: str) -> str:
    """Authenticated initialize → the server's declared name (e.g. svgator)."""
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream",
               "Authorization": "Bearer " + (access_token or "")}
    r = httpx.post(url, headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "dreamagent", "version": "1.0"}}},
        timeout=PROBE_TIMEOUT)
    doc = parse_sse_or_json(r)
    name = ((((doc or {}).get("result") or {}).get("serverInfo") or {}).get("name") or "")
    name = name.split("/")[-1].replace("@", "").replace("-mcp", "").replace("_mcp", "").strip()
    return name
