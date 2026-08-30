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
        # Registered in Nango under the twitter-v2 OAuth2 template but keyed
        # "twitter" — the legacy twitter slug is OAuth 1.0a.
        "nango_provider": "twitter-v2",
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

# Per-provider prompt extras layered on top of Nango's own /providers
# metadata (base_url + docs) — Nango can't know example calls or gotchas.
# Keys here are our provider_config_keys (ENABLED_PROVIDERS).
PROVIDER_EXTRAS: Dict[str, Dict[str, Any]] = {
    "youtube": {
        "capabilities": {
            "read": "channel profile+stats, latest videos, per-video statistics",
            "post": "upload videos (resumable two-step)",
        },
        "examples": [
            "GET youtube/v3/channels?part=snippet&mine=true",
            "GET youtube/v3/search?part=snippet&channelId={CHANNEL_ID}&order=date&maxResults=10",
            "GET youtube/v3/videos?part=statistics&id={VIDEO_IDS}",
        ],
        "gotchas": [
            "Analytics API is a different base URL — not reachable via this proxy; "
            "compute stats from video data instead.",
            "Uploads (youtube.upload): two-step — POST upload/youtube/v3/videos?"
            "uploadType=resumable returns the upload-session URL in the "
            "response 'Location' header (the proxy forwards it); then PUT "
            "the video bytes straight to that URL — direct, no proxy (the "
            "session URL itself authorizes the hop).",
        ],
    },
    "github": {
        "capabilities": {
            "read": "own profile, repos, issues, pull requests, commits",
            "create": "issues, comments, releases",
        },
        "examples": [
            "GET user",
            "GET user/repos?per_page=100",
            "GET repos/{owner}/{repo}/issues?state=open",
        ],
    },
    "discord": {
        "capabilities": {
            "read": "own profile, servers (guilds) the user is in",
        },
        "examples": ["GET users/@me", "GET users/@me/guilds"],
        "gotchas": [
            "User OAuth cannot read or send channel messages — that needs a "
            "Bot token (API-key catalog: discord-bot).",
        ],
    },
    "notion": {
        "capabilities": {
            "read": "pages, databases (query with filters)",
            "create": "pages (append blocks, database rows)",
            "update": "page properties and content",
        },
        "examples": [
            "GET v1/pages/{page_id}",
            "POST v1/databases/{database_id}/query",
            "PATCH v1/pages/{page_id}",
        ],
        "gotchas": ["Pagination cursor param is start_cursor (not page)."],
    },
    "twitter": {
        "capabilities": {
            "read": "own profile (public_metrics: followers/following/tweet_count)",
            "post": "tweets and threads (~500/month free tier)",
        },
        "examples": [
            "GET 2/users/me?user.fields=public_metrics",
            "POST 2/tweets",
        ],
        "gotchas": [
            "Free tier: posting + own profile ONLY (~500 posts/mo); "
            "public_metrics gives follower/following/tweet_count.",
            "Timeline reads (users/{id}/tweets, mentions, search) are PAID "
            "tier — never call them; track tweets you post by saving the "
            "returned tweet ids (e.g. to Notion/Google Sheet).",
            "Read endpoints reject max_results outside 5-100 — never pass "
            "max_results=3; request 5 (or 10) and slice the top N yourself.",
            "POST 2/tweets body: {\"text\": \"...\"} — plain JSON, no "
            "content-type quirks; character limit applies to the final "
            "text including emoji and the trailing hashtag line.",
        ],
    },
    "google-sheet": {
        "capabilities": {
            "read": "ranges and full sheet metadata",
            "append": "rows (values:append)",
            "update": "cells/ranges (values:update PUT)",
        },
        "examples": [
            "GET v4/spreadsheets/{sheet_id}/values/{range}",
            "PUT v4/spreadsheets/{sheet_id}/values/{range}?valueInputOption=RAW",
        ],
        "gotchas": ["Range format is Sheet1!A1:D1; read the sheetId from the URL."],
    },
    "slack": {
        "capabilities": {
            "read": "channels (conversations.list), channel history",
            "post": "messages (chat.postMessage as the app bot)",
        },
        "examples": [
            "POST chat.postMessage",
            "GET conversations.list",
            "GET conversations.history?channel={id}",
        ],
        "gotchas": ["Bot must be invited to a channel before it can post or read there."],
    },
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
# Provider metadata (Nango's own catalog — base URLs + doc links)
# ----------------------------------------------------------------------

_PROVIDER_META_CACHE: Dict[str, Any] = {"at": 0.0, "by_name": {}}
_META_TTL_SECONDS = 3600.0


def get_provider_metadata(nango_provider_name: str) -> Optional[Dict[str, Any]]:
    """{display_name, base_url, docs} for a provider from Nango's catalog
    (GET /providers — 981 entries, cached 1h). This keeps proxy base URLs
    and doc links accurate without hardcoding; returns None when Nango is
    unconfigured/unreachable (callers fall back to static titles)."""
    if not is_configured():
        return None
    import time as _time
    now = _time.time()
    cache = _PROVIDER_META_CACHE
    if not cache["by_name"] or (now - float(cache["at"])) > _META_TTL_SECONDS:
        try:
            r = httpx.get(f"{_base_url()}/providers", headers=_headers(), timeout=_TIMEOUT)
            if r.status_code == 200:
                payload = r.json()
                items = payload.get("data") if isinstance(payload, dict) else payload
                items = items or []
                cache["by_name"] = {
                    i.get("name"): i for i in items
                    if isinstance(i, dict) and i.get("name")
                }
                cache["at"] = now
        except Exception as e:  # never break prompt building on metadata
            logger.warning("[NANGO] provider metadata fetch failed: %s", e)
    entry = cache["by_name"].get(nango_provider_name)
    if not entry:
        return None
    proxy = entry.get("proxy") or {}
    return {
        "display_name": entry.get("display_name") or nango_provider_name,
        "base_url": str(proxy.get("base_url") or "").rstrip("/"),
        "docs": entry.get("docs") or "",
    }


# ----------------------------------------------------------------------
# Connect sessions (per end-user — the only thing the frontend receives)
# ----------------------------------------------------------------------

def mint_connect_session(user_id: int, user_email: str,
                         providers: List[str]) -> Dict[str, Any]:
    """Mint a short-lived connect session.

    NOTE: Nango 0.71.4's /connect/sessions schema is .strict() and has NO
    connection_id field (sending one 400s), and /oauth/connect rejects
    connection_id when a session token is present. The session flow always
    creates the connection with a server-generated connection_id — so
    multi-account works via CLAIM: the caller diffs live connections
    before/after consent and labels the new one (see the router's
    /claim endpoint)."""
    payload: Dict[str, Any] = {
        "end_user": {"id": str(user_id), "email": user_email},
        "allowed_integrations": providers,
    }
    r = httpx.post(f"{_base_url()}/connect/sessions", headers=_headers(),
                   json=payload, timeout=_TIMEOUT)
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

# Provider response headers worth forwarding to project backends — e.g.
# YouTube resumable uploads return the upload-session URL in Location,
# without which the caller cannot complete the second PUT hop.
_FORWARD_RESPONSE_HEADERS = frozenset({
    "location", "content-type", "content-length", "etag", "retry-after",
    "range", "x-goog-upload-url", "x-goog-upload-status",
})


def proxy_request(provider_config_key: str, connection_id: str, method: str,
                  endpoint: str, **kwargs: Any) -> Dict[str, Any]:
    """Authenticated provider call through Nango with credential injection.
    Returns {status, body, headers} — body is the raw provider bytes/text;
    headers is a filtered subset (upload session URLs etc.), never
    set-cookie.

    Extra kwargs beyond httpx's: raw_body (bytes — sent as-is, binary-safe),
    extra_headers (merged into the outbound request headers), timeout_seconds
    (per-request timeout, default 30s, max 300s for uploads)."""
    raw_body = kwargs.pop("raw_body", None)
    extra_headers = kwargs.pop("extra_headers", None) or {}
    timeout_seconds = float(kwargs.pop("timeout_seconds", 30.0))
    outbound_headers = {
        "Authorization": f"Bearer {_secret()}",
        "provider-config-key": provider_config_key,
        "connection-id": connection_id,
    }
    outbound_headers.update(extra_headers)

    send_kwargs: Dict[str, Any] = {"headers": outbound_headers,
                                   "timeout": min(timeout_seconds, 300.0)}
    if raw_body is not None:
        send_kwargs["content"] = raw_body
        # caller's content-type (if any) already in extra_headers; otherwise
        # httpx sets application/octet-stream
    elif "json" in kwargs:
        send_kwargs["json"] = kwargs.pop("json")
    if "params" in kwargs:
        send_kwargs["params"] = kwargs.pop("params")
    if "data" in kwargs:
        send_kwargs["data"] = kwargs.pop("data")

    r = httpx.request(
        method.upper(),
        f"{_base_url()}/proxy/{endpoint.lstrip('/')}",
        **send_kwargs,
    )
    resp_headers = {
        k: v for k, v in r.headers.items()
        if k.lower() in _FORWARD_RESPONSE_HEADERS
    }
    # Binary-safe: pass bytes through untouched (video/audio responses);
    # truncate only text bodies (log-size safety for JSON APIs).
    if r.headers.get("content-type", "").startswith(("audio/", "video/", "application/octet-stream")):
        body_out: Any = r.content
    else:
        body_out = r.text[:5000]
    return {"status": r.status_code, "body": body_out,
            "headers": resp_headers}
