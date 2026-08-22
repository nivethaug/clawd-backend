#!/usr/bin/env python3
"""
Nango Integrations Router — OAuth-first Global Integrations (Phase N1).

Mounted at: /api/integrations/nango (prefix in app.py).

Isolation: all logic in services/integrations/nango_client.py; this router
authenticates, resolves the user from the token (never client-supplied),
and reconciles Nango connections with our nango_connections rows.

Feature gate: NANGO_SECRET_KEY unset → 503 on every route; the rest of
DreamAgent (API-key vault, Custom Env, projects) is unaffected.
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from utils.auth_helpers import get_user_id_from_token
from services.integrations import nango_client
from database_adapter import get_db

logger = logging.getLogger("api.integrations.nango")

router = APIRouter()


class ConnectSessionRequest(BaseModel):
    provider: str


def _require_configured():
    if not nango_client.is_configured():
        raise HTTPException(
            status_code=503,
            detail="OAuth integrations are not configured on this server "
                   "(NANGO_SECRET_KEY required)",
        )


def _user_email(user_id: int) -> str:
    with get_db() as conn:
        row = conn.execute(
            "SELECT email FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    d = (dict(row) if row and not isinstance(row, dict) else row) or {}
    return d.get("email") or f"user{user_id}@dreamagent.cloud"


# ----------------------------------------------------------------------
# Providers + connected status (lazily reconciled with Nango)
# ----------------------------------------------------------------------

@router.get("/providers")
async def list_providers(authorization: Optional[str] = Header(None)):
    """Enabled OAuth providers + the caller's connected status."""
    user_id = get_user_id_from_token(authorization)
    _require_configured()

    # Reconcile: Nango is the source of truth for live connections; our
    # table maps them. Rows without a live Nango connection are dropped.
    live = {
        c.get("provider_config_key"): c
        for c in nango_client.list_connections_for_user(user_id)
    }
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM nango_connections WHERE user_id = ?", (user_id,)
        ).fetchall()
    local = {
        (dict(r) if not isinstance(r, dict) else r)["provider_config_key"]:
            (dict(r) if not isinstance(r, dict) else r)
        for r in rows
    }

    # Remove stale local rows (disconnected elsewhere)
    for key, row in local.items():
        if key not in live:
            with get_db() as conn:
                conn.execute("DELETE FROM nango_connections WHERE id = ?", (row["id"],))
                conn.commit()

    providers = []
    for key, meta in nango_client.ENABLED_PROVIDERS.items():
        entry = {
            "provider": key,
            "title": meta["title"],
            "category": meta["category"],
            "description": meta["description"],
            "auth": "oauth",
            "connected": False,
            "connection": None,
        }
        conn_live = live.get(key)
        if conn_live:
            display = nango_client.get_connection_metadata(conn_live)
            entry["connected"] = True
            entry["connection"] = display
            with get_db() as conn:
                conn.execute(
                    """INSERT INTO nango_connections
                       (user_id, provider_config_key, connection_id, end_user_id,
                        metadata, last_checked_at)
                       VALUES (?, ?, ?, ?, ?::jsonb, NOW())
                       ON CONFLICT (user_id, provider_config_key) DO UPDATE SET
                         connection_id = EXCLUDED.connection_id,
                         metadata = EXCLUDED.metadata,
                         last_checked_at = NOW()""",
                    (user_id, key, conn_live.get("connection_id") or "",
                     str(user_id),
                     json.dumps(display)),
                )
                conn.commit()
        providers.append(entry)

    return {"providers": providers}


# ----------------------------------------------------------------------
# Connect flow
# ----------------------------------------------------------------------

@router.post("/connect-session")
async def create_connect_session(request: ConnectSessionRequest,
                                 authorization: Optional[str] = Header(None)):
    """Mint a short-lived Nango connect session for the caller. The
    frontend SDK opens the consent popup with this token; no secrets are
    involved — the session only allows connecting as THIS end user."""
    user_id = get_user_id_from_token(authorization)
    _require_configured()
    if request.provider not in nango_client.ENABLED_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown OAuth provider")
    result = nango_client.mint_connect_session(
        user_id, _user_email(user_id), [request.provider]
    )
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return result


@router.delete("/{provider}")
async def disconnect(provider: str, authorization: Optional[str] = Header(None)):
    """Disconnect: delete the Nango connection (revokes stored tokens) and
    our mapping row. Ownership enforced by user_id in every WHERE."""
    user_id = get_user_id_from_token(authorization)
    _require_configured()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM nango_connections WHERE user_id = ? AND provider_config_key = ?",
            (user_id, provider),
        ).fetchone()
    local = (dict(row) if row and not isinstance(row, dict) else row) if row else None

    connection_id = (local or {}).get("connection_id")
    if not connection_id:
        # Fall back to a live lookup by end_user
        live = nango_client.list_connections_for_user(user_id)
        connection_id = next(
            (c.get("connection_id") for c in live
             if c.get("provider_config_key") == provider), None
        )
    if connection_id:
        nango_client.delete_connection(connection_id, provider)
    with get_db() as conn:
        conn.execute(
            "DELETE FROM nango_connections WHERE user_id = ? AND provider_config_key = ?",
            (user_id, provider),
        )
        conn.commit()
    logger.info("[NANGO] user %s disconnected %s (connection %s)",
                user_id, provider, connection_id or "none")
    return {"disconnected": True}
