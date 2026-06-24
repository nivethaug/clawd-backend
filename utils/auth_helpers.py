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

    # Lazy import to avoid circular dependency at module load time
    from app import AUTH_TOKENS

    user_id = AUTH_TOKENS.get(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return user_id


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
