"""
Auth Helpers
Shared authentication utilities extracted from app.py to avoid circular imports.
"""

import logging
from typing import Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)


def get_user_id_from_token(authorization: Optional[str] = None) -> int:
    """
    Extract and validate user_id from Authorization header.

    Args:
        authorization: Raw Authorization header value (e.g. "Bearer <token>")

    Returns:
        user_id (int) if token is valid.

    Raises:
        HTTPException(401) if header is missing, malformed, or token is invalid.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization format")

    token = parts[1]

    # 1) Long-lived service token (ADMIN_METRICS_TOKEN) — same as app.py version
    import hmac
    import os
    admin_token = os.getenv("ADMIN_METRICS_TOKEN", "").strip()
    admin_uid = int(os.getenv("ADMIN_METRICS_USER_ID", "0") or "0")
    if admin_token and admin_uid and hmac.compare_digest(token, admin_token):
        return admin_uid

    # 2) Session token
    from app import AUTH_TOKENS

    user_id = AUTH_TOKENS.get(token)
    if user_id:
        return user_id

    # 3) Personal API key (da_...) for MCP / ChatGPT connectors — hashed lookup
    if token.startswith("da_"):
        try:
            import hashlib
            from database_postgres import get_db

            key_hash = hashlib.sha256(token.encode()).hexdigest()
            with get_db() as conn:
                row = conn.execute(
                    "SELECT user_id, revoked_at FROM api_keys WHERE key_hash = ?",
                    (key_hash,)
                ).fetchone()
            if row:
                uid, revoked = (row.get("user_id"), row.get("revoked_at")) if isinstance(row, dict) else (row[0], row[1])
                if not revoked:
                    return uid
        except Exception:
            pass

    raise HTTPException(status_code=401, detail="Invalid or expired token")


def get_optional_user_id(authorization: Optional[str] = None) -> Optional[int]:
    """
    Try to extract user_id from Authorization header.
    Returns None if missing/invalid (does NOT raise).

    Useful for endpoints that want optional auth (graceful degradation).
    """
    if not authorization:
        return None

    try:
        return get_user_id_from_token(authorization)
    except HTTPException:
        return None
