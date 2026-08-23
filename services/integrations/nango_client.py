"""
Nango Client — DreamAgent's server-side client for the self-hosted Nango
instance (OAuth-first integrations; see scripts/nango-spike/RESULTS.md).

Wire facts baked in from the spike (Nango 0.71):
- Public API is ROOT-mounted (NO /api/v1) and snake_case
- Auth: `Authorization: Bearer <environment secret key>`
- POST /integrations                    {provider, unique_key, credentials?}
- POST /connect/sessions                {end_user:{id,email}, allowed_integrations}
- POST /api-auth/api-key/{pcKey}?connect_session_token=…   {apiKey}
- GET  /connection?end_user_id=…        list connections for an end user
- GET  /connection/{connectionId}?provider_config_key=…    one connection (+credentials)
- DELETE /connection/{connectionId}?provider_config_key=…
- ANY  /proxy/{endpoint…}               headers: provider-config-key, connection-id
- POST /connection/{connectionId}/refresh  (force token refresh)

Security: NANGO_SECRET_KEY stays server-side (env); this module never
logs tokens or secrets; the frontend only ever receives connect-session
tokens minted here.
"""

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("integrations.nango")

DEFAULT_NANGO_URL = "http://127.0.0.1:3003"
DEFAULT_PUBLIC_URL = "https://nango.dreamagent.cloud"

# Providers DreamAgent enables on Nango (V1: YouTube; each requires its
# OAuth app registered in Nango once — see the runbook).
ENABLED_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "youtube": {
        "title": "YouTube",
        "category": "Integrations",
        "description": "Access your YouTube channel, videos and authorized analytics — "
                       "connects with Google in one click, no API key needed.",
        "env_token_key": "YOUTUBE_ACCESS_TOKEN",
    },
    "github": {
        "title": "GitHub",
        "category": "Integrations",
        "description": "Access your repositories, commits, issues and pull requests — "
                       "one-click GitHub authorization.",
        "env_token_key": "GITHUB_ACCESS_TOKEN",
    },
    "discord": {
        "title": "Discord",
        "category": "Integrations",
        "description": "Access your Discord servers, channels and messages — "
                       "one-click Discord authorization.",
        "env_token_key": "DISCORD_ACCESS_TOKEN",
    },
    "notion": {
        "title": "Notion",
        "category": "Integrations",
        "description": "Read and update your Notion pages and databases — "
                       "one-click Notion authorization.",
        "env_token_key": "NOTION_ACCESS_TOKEN",
    },
    "twitter": {
        "title": "X (Twitter)",
        "category": "Integrations",
        "description": "Post to X and read your own profile — one-click "
                       "authorization (free tier: posting only).",
        "env_token_key": "TWITTER_ACCESS_TOKEN",
    },
    # Nango slug is singular: "google-sheet".
    "google-sheet": {
        "title": "Google Sheets",
        "category": "Integrations",
        "description": "Read and write rows in your Google spreadsheets — "
                       "one-click Google authorization.",
        "env_token_key": "GOOGLE_SHEETS_ACCESS_TOKEN",
    },
    "slack": {
        "title": "Slack",
        "category": "Integrations",
        "description": "Access your Slack workspaces, channels and messages — "
                       "one-click Slack authorization.",
        "env_token_key": "SLACK_ACCESS_TOKEN",
    },
    # Stripe OAuth: parked — use the API-key vault entry (STRIPE_SECRET_KEY) meanwhile.
}

_TIMEOUT = 15.0


def _base_url() -> str:
    return os.getenv("NANGO_URL", DEFAULT_NANGO_URL).rstrip("/")


def _public_url() -> str:
    return os.getenv("NANGO_PUBLIC_URL", DEFAULT_PUBLIC_URL).rstrip("/")


def _secret() -> str:
    return os.getenv("NANGO_SECRET_KEY", "")


def is_configured() -> bool:
    return bool(_secret())


def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {_secret()}", "Content-Type": "application/json"}


def _log_error(action: str, status: int, body: str) -> None:
    # Never log tokens/credentials — status + short body only.
    logger.warning("[NANGO] %s -> HTTP %s: %s", action, status, body[:200])


# ----------------------------------------------------------------------
# Integrations (provider configuration — one-time per provider)
# ----------------------------------------------------------------------

def ensure_integration(provider: str, credentials: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create (or no-op-update) the Nango integration for a provider."""
    payload: Dict[str, Any] = {"provider": provider, "unique_key": provider}
    if credentials:
        payload["credentials"] = credentials
    r = httpx.post(f"{_base_url()}/integrations", headers=_headers(),
                   json=payload, timeout=_TIMEOUT)
    if r.status_code >= 400:
        _log_error("create integration", r.status_code, r.text)
        return {"error": f"nango integration setup failed ({r.status_code})",
                "status_code": r.status_code}
    return r.json().get("data") or {"created": True}


def integration_exists(provider: str) -> bool:
    r = httpx.get(f"{_base_url()}/integrations", headers=_headers(), timeout=_TIMEOUT)
    if r.status_code != 200:
        return False
    return any(i.get("unique_key") == provider for i in (r.json() or []))


# ----------------------------------------------------------------------
# Connect sessions (per end-user — the only thing the frontend receives)
# ----------------------------------------------------------------------

def mint_connect_session(user_id: int, user_email: str,
                         providers: List[str]) -> Dict[str, Any]:
    r = httpx.post(f"{_base_url()}/connect/sessions", headers=_headers(), json={
        "end_user": {"id": str(user_id), "email": user_email},
        "allowed_integrations": providers,
    }, timeout=_TIMEOUT)
    if r.status_code >= 400:
        _log_error("connect session", r.status_code, r.text)
        return {"error": "could not start connection flow"}
    data = r.json().get("data") or {}
    return {
        "session_token": data.get("token"),
        "public_url": _public_url(),
    }


# ----------------------------------------------------------------------
# Connections
# ----------------------------------------------------------------------

def list_connections_for_user(user_id: int) -> List[Dict[str, Any]]:
    """All Nango connections for this end user. 0.71's list endpoint has no
    end_user filter param, so we list the environment and filter our side
    (this DreamAgent environment is single-tenant to us)."""
    r = httpx.get(f"{_base_url()}/connection", headers=_headers(), timeout=_TIMEOUT)
    if r.status_code >= 400:
        _log_error("list connections", r.status_code, r.text)
        return []
    conns = (r.json() or {}).get("connections") or []
    return [c for c in conns
            if (c.get("end_user") or {}).get("id") == str(user_id)]


def get_connection(connection_id: str, provider_config_key: str) -> Optional[Dict[str, Any]]:
    r = httpx.get(
        f"{_base_url()}/connection/{connection_id}",
        params={"provider_config_key": provider_config_key},
        headers=_headers(), timeout=_TIMEOUT,
    )
    if r.status_code != 200:
        return None
    return r.json()


def delete_connection(connection_id: str, provider_config_key: str) -> bool:
    r = httpx.delete(
        f"{_base_url()}/connection/{connection_id}",
        params={"provider_config_key": provider_config_key},
        headers=_headers(), timeout=_TIMEOUT,
    )
    if r.status_code >= 400:
        _log_error("delete connection", r.status_code, r.text)
        return False
    return True


def get_access_token(connection_id: str, provider_config_key: str) -> Optional[str]:
    """Fresh OAuth access token for provider calls (server-side only).
    Nango auto-refreshes when stale."""
    conn = get_connection(connection_id, provider_config_key)
    if not conn:
        return None
    creds = conn.get("credentials") or {}
    return creds.get("access_token") or None


def get_connection_metadata(connection: Dict[str, Any]) -> Dict[str, Any]:
    """Pull a display identity out of a Nango connection (channel/account
    name) — provider-agnostic best effort, never sensitive."""
    meta = connection.get("metadata") or {}
    out: Dict[str, Any] = {}
    for source in (meta, connection.get("connection_config") or {}):
        for key in ("channel_title", "account_name", "name", "title",
                    "login", "username", "display_name"):
            if source.get(key):
                out.setdefault("display_name", str(source[key])[:100])
        for key in ("channel_id", "account_id", "id"):
            if source.get(key):
                out.setdefault("external_id", str(source[key])[:100])
    if connection.get("end_user"):
        out.setdefault("display_name", (connection["end_user"].get("display_name")
                                        or connection["end_user"].get("email")))
    return out


# ----------------------------------------------------------------------
# Proxy (server-side authenticated provider calls)
# ----------------------------------------------------------------------

def proxy_request(provider_config_key: str, connection_id: str, method: str,
                  endpoint: str, **kwargs: Any) -> Dict[str, Any]:
    """Authenticated provider call through Nango with credential injection.
    Returns {status, body} — body is the raw provider JSON."""
    r = httpx.request(
        method.upper(),
        f"{_base_url()}/proxy/{endpoint.lstrip('/')}",
        headers={
            "Authorization": f"Bearer {_secret()}",
            "provider-config-key": provider_config_key,
            "connection-id": connection_id,
        },
        timeout=30.0,
        **kwargs,
    )
    return {"status": r.status_code, "body": r.text[:5000]}
