"""
GitHub OAuth Service

Per-user GitHub OAuth connection for the Export-to-GitHub feature.
Exchanges OAuth authorization codes for access tokens, fetches user info,
and persists the connection in the `users` table.

Unlike `github_service.py` (server-account-only, uses `gh` CLI), this service
operates on individual users' own GitHub accounts via OAuth tokens.
"""

import logging
import os
from datetime import datetime
from typing import Optional

from httpx import AsyncClient

from database_adapter import get_db

logger = logging.getLogger(__name__)

GITHUB_OAUTH_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_USER_URL = "https://api.github.com/user"


def _client_id() -> str:
    return (os.getenv("GITHUB_CLIENT_ID") or "").strip()


def _client_secret() -> str:
    return (os.getenv("GITHUB_CLIENT_SECRET") or "").strip()


def _redirect_uri() -> str:
    """
    GitHub OAuth callback URL. Defaults to the backend endpoint.
    Can be overridden via GITHUB_REDIRECT_URI for frontend-hosted callback.
    """
    return (os.getenv("GITHUB_REDIRECT_URI") or "").strip()


def build_authorize_url(state: str, scope: str = "repo") -> str:
    """
    Build the GitHub OAuth authorize URL for the user to visit.

    Args:
        state: opaque value echoed by GitHub in the callback (typically encodes user_id).
        scope: OAuth scopes. Default 'repo' grants read/write to user's repos.

    Returns:
        Fully qualified GitHub authorize URL.
    """
    if not _client_id():
        raise RuntimeError("GITHUB_CLIENT_ID is not configured")

    params = {
        "client_id": _client_id(),
        "scope": scope,
        "state": state,
        "allow_signup": "true",
    }
    redirect = _redirect_uri()
    if redirect:
        params["redirect_uri"] = redirect

    from urllib.parse import urlencode

    return f"{GITHUB_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    """
    Exchange an OAuth authorization code for an access token.

    Args:
        code: Authorization code returned by GitHub in the callback.

    Returns:
        Dict with at least {'access_token', 'scope', 'token_type'}.

    Raises:
        RuntimeError: if client ID/secret not configured or GitHub rejects the code.
    """
    if not _client_id() or not _client_secret():
        raise RuntimeError("GITHUB_CLIENT_ID or GITHUB_CLIENT_SECRET is not configured")

    payload = {
        "client_id": _client_id(),
        "client_secret": _client_secret(),
        "code": code,
    }
    redirect = _redirect_uri()
    if redirect:
        payload["redirect_uri"] = redirect

    async with AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            GITHUB_OAUTH_TOKEN_URL,
            json=payload,
            headers={"Accept": "application/json"},
        )

    if resp.status_code != 200:
        logger.error("GitHub token exchange failed: %s %s", resp.status_code, resp.text)
        raise RuntimeError(f"GitHub token exchange failed: HTTP {resp.status_code}")

    data = resp.json()
    token = data.get("access_token")
    if not token:
        # GitHub sometimes returns 200 with an error body
        err = data.get("error_description") or data.get("error") or "unknown error"
        raise RuntimeError(f"GitHub token exchange failed: {err}")

    return data


async def get_user_info(access_token: str) -> dict:
    """
    Fetch the GitHub user profile for the given token.

    Args:
        access_token: A valid GitHub OAuth access token.

    Returns:
        Dict with at least {'login', 'avatar_url', 'html_url'}.

    Raises:
        RuntimeError: if the token is invalid or GitHub rejects the request.
    """
    async with AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            GITHUB_API_USER_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if resp.status_code != 200:
        raise RuntimeError(f"GitHub /user failed: HTTP {resp.status_code}")

    data = resp.json()
    return {
        "login": data.get("login"),
        "avatar_url": data.get("avatar_url"),
        "html_url": data.get("html_url"),
    }


def save_github_connection(
    user_id: int,
    access_token: str,
    scope: str,
    username: str,
    avatar_url: Optional[str] = None,
) -> None:
    """
    Persist the GitHub OAuth connection to the user row.

    Args:
        user_id: DreamAgent user ID.
        access_token: GitHub OAuth access token (stored server-side only).
        scope: OAuth scopes granted (e.g. 'repo').
        username: GitHub login name.
        avatar_url: Optional avatar URL.
    """
    with get_db() as conn:
        conn.execute(
            """
            UPDATE users
            SET github_access_token = ?,
                github_token_scope = ?,
                github_username = ?,
                github_avatar_url = ?,
                github_connected_at = ?
            WHERE id = ?
            """,
            (
                access_token,
                scope,
                username,
                avatar_url,
                datetime.utcnow(),
                user_id,
            ),
        )
        conn.commit()


def get_github_connection(user_id: int) -> Optional[dict]:
    """
    Return the user's GitHub connection (without the raw token).

    Args:
        user_id: DreamAgent user ID.

    Returns:
        None if not connected, otherwise:
        {
            'connected': True,
            'username': str,
            'avatar_url': str|None,
            'connected_at': str|None,
            'scope': str|None,
            'access_token': str  # RAW token, for server-side use only
        }
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT github_username, github_access_token, github_token_scope, "
            "github_avatar_url, github_connected_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

    if not row:
        return None

    if isinstance(row, dict):
        username = row.get("github_username")
        access_token = row.get("github_access_token")
        scope = row.get("github_token_scope")
        avatar_url = row.get("github_avatar_url")
        connected_at = row.get("github_connected_at")
    else:
        username = row[0]
        access_token = row[1]
        scope = row[2]
        avatar_url = row[3]
        connected_at = row[4]

    if not access_token or not username:
        return None

    return {
        "connected": True,
        "username": username,
        "avatar_url": avatar_url,
        "connected_at": str(connected_at) if connected_at else None,
        "scope": scope,
        "access_token": access_token,
    }


def get_user_access_token(user_id: int) -> Optional[str]:
    """
    Return the user's raw GitHub access token (server-side use only).

    Returns None if the user has not connected GitHub.
    """
    conn_info = get_github_connection(user_id)
    if not conn_info:
        return None
    return conn_info.get("access_token")


def disconnect_github(user_id: int) -> None:
    """Clear the user's GitHub connection."""
    with get_db() as conn:
        conn.execute(
            """
            UPDATE users
            SET github_access_token = NULL,
                github_token_scope = NULL,
                github_username = NULL,
                github_avatar_url = NULL,
                github_connected_at = NULL
            WHERE id = ?
            """,
            (user_id,),
        )
        conn.commit()


def public_status(user_id: int) -> dict:
    """
    Return a safe status object for API responses (never the raw token).

    Returns:
        {'connected': False} or
        {'connected': True, 'username': str, 'avatar_url': str|None}
    """
    conn_info = get_github_connection(user_id)
    if not conn_info:
        return {"connected": False}
    return {
        "connected": True,
        "username": conn_info.get("username"),
        "avatar_url": conn_info.get("avatar_url"),
        "connected_at": conn_info.get("connected_at"),
    }
