#!/usr/bin/env python3
"""
Nango Integrations Router — OAuth-first Global Integrations (Phase N1).

Mounted at: /api/integrations/nango (prefix in app.py).

Isolation: all logic in services/integrations/nango_client.py; this router
authenticates, resolves the user from the token (never client-supplied),
and reconciles Nango connections with our nango_connections rows.

Multi-account: a user may connect SEVERAL accounts per provider (e.g. two
YouTube channels). Each connection carries a label; the oldest per provider
(or an explicitly chosen one) is the DEFAULT used by proxy_call when no
account is specified. Connection ids for extra accounts are
"<user_id>:<provider>:<label-slug>"; the legacy default connection keeps
Nango's end_user.id-based connection id and works unchanged.

Feature gate: NANGO_SECRET_KEY unset → 503 on every route; the rest of
DreamAgent (API-key vault, Custom Env, projects) is unaffected.
"""

import json
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from utils.auth_helpers import get_user_id_from_token
from services.integrations import nango_client
from database_adapter import get_db

logger = logging.getLogger("api.integrations.nango")

router = APIRouter()


class ConnectSessionRequest(BaseModel):
    provider: str
    # Optional account label, e.g. "Clips channel". Omitted → legacy
    # single-account flow (connection_id = end_user.id, becomes default).
    label: Optional[str] = None


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
# Providers + connected accounts (lazily reconciled with Nango)
# ----------------------------------------------------------------------

@router.get("/providers")
async def list_providers(authorization: Optional[str] = Header(None)):
    """Enabled OAuth providers + the caller's connected accounts."""
    user_id = get_user_id_from_token(authorization)
    _require_configured()

    # Reconcile: Nango is the source of truth for live connections; our
    # table maps them. Rows without a live Nango connection are dropped.
    live_by_provider: Dict[str, List[dict]] = {}
    for c in nango_client.list_connections_for_user(user_id):
        key = c.get("provider_config_key")
        if key:
            live_by_provider.setdefault(key, []).append(c)

    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM nango_connections WHERE user_id = ?", (user_id,)
        ).fetchall()
    local_rows = [(dict(r) if not isinstance(r, dict) else r) for r in rows]
    local_by_id = {r["connection_id"]: r for r in local_rows}

    # Remove stale local rows (deleted in Nango, or provider disabled)
    live_conn_ids = {
        c.get("connection_id")
        for conns in live_by_provider.values() for c in conns
    }
    for row in local_rows:
        stale = (row["connection_id"] not in live_conn_ids
                 or row["provider_config_key"] not in nango_client.ENABLED_PROVIDERS)
        if stale:
            with get_db() as conn:
                conn.execute("DELETE FROM nango_connections WHERE id = ?", (row["id"],))
                conn.commit()
            local_by_id.pop(row["connection_id"], None)

    providers = []
    for key, meta in nango_client.ENABLED_PROVIDERS.items():
        entry = {
            "provider": key,
            "title": meta["title"],
            "category": meta["category"],
            "description": meta["description"],
            "auth": "oauth",
            "connected": False,
            "connection": None,          # default account (legacy field)
            "connected_accounts": [],    # multi-account list
        }
        live_conns = live_by_provider.get(key, [])
        if live_conns:
            # Preserve our stored label/default ordering; new live
            # connections not yet in our table append at the end.
            ordered: List[dict] = []
            seen = set()
            stored = [r for r in local_rows if r["provider_config_key"] == key]
            by_cid = {r["connection_id"]: r for r in stored}
            for r in sorted(stored, key=lambda r: (not r.get("is_default"), r["id"])):
                match = next((c for c in live_conns
                              if c.get("connection_id") == r["connection_id"]), None)
                if match:
                    ordered.append(match)
                    seen.add(r["connection_id"])
            ordered.extend(c for c in live_conns if c.get("connection_id") not in seen)

            owner_email = _user_email(user_id)
            accounts = []
            for i, c in enumerate(ordered):
                cid = c.get("connection_id") or ""
                stored_row = by_cid.get(cid) or {}
                display = nango_client.get_connection_metadata(c)
                # Legacy fallback artifact: display/email was the OWNER's
                # login (same on every row) — drop so the label shines.
                if display.get("display_name") == owner_email:
                    display.pop("display_name", None)
                if display.get("email") == owner_email:
                    display.pop("email", None)
                is_default = bool(stored_row.get("is_default")) or (not stored and i == 0)
                accounts.append({
                    "connection_id": cid,
                    "label": stored_row.get("label") or display.get("display_name") or "default",
                    "display_name": display.get("display_name"),
                    "email": display.get("email"),
                    "external_id": display.get("external_id"),
                    "is_default": is_default,
                })
                # Upsert the mapping row (per connection, not per provider).
                # Label: preserved from any stored row (set at connect time);
                # Nango-side display metadata refreshes every reconcile.
                stored_label = stored_row.get("label")
                with get_db() as conn:
                    conn.execute(
                        """INSERT INTO nango_connections
                           (user_id, provider_config_key, connection_id, end_user_id,
                            label, metadata, last_checked_at)
                           VALUES (?, ?, ?, ?, ?, ?::jsonb, NOW())
                           ON CONFLICT (user_id, provider_config_key, connection_id)
                           DO UPDATE SET
                             label = COALESCE(nango_connections.label, EXCLUDED.label),
                             metadata = EXCLUDED.metadata,
                             last_checked_at = NOW()""",
                        (user_id, key, cid, str(user_id), stored_label,
                         json.dumps(display)),
                    )
                    # Ensure exactly one default per provider
                    has_default = conn.execute(
                        "SELECT 1 FROM nango_connections WHERE user_id = ? "
                        "AND provider_config_key = ? AND is_default LIMIT 1",
                        (user_id, key),
                    ).fetchone() is not None
                    if not has_default:
                        conn.execute(
                            "UPDATE nango_connections SET is_default = true, "
                            "label = COALESCE(label, 'default') WHERE id = ("
                            "  SELECT id FROM nango_connections WHERE user_id = ? "
                            "  AND provider_config_key = ? "
                            "  ORDER BY created_at ASC, id ASC LIMIT 1)",
                            (user_id, key),
                        )
                    conn.commit()

            entry["connected"] = bool(accounts)
            default = next((a for a in accounts if a["is_default"]), accounts[0])
            entry["connection"] = {
                "display_name": default.get("display_name"),
                "external_id": default.get("external_id"),
                "label": default.get("label"),
            }
            entry["connected_accounts"] = accounts
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
    involved — the session only allows connecting as THIS end user.

    With `label`, the new connection is scoped to a named account
    (multi-account). Without it, the legacy default-connection flow runs
    (and is refused if the provider already has a connected account —
    use a label to add more)."""
    user_id = get_user_id_from_token(authorization)
    _require_configured()
    if request.provider not in nango_client.ENABLED_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown OAuth provider")

    if request.label:
        label = request.label.strip()
        if not label or len(label) > 60:
            raise HTTPException(status_code=400,
                                detail="Account label must be 1-60 characters")
        # Label uniqueness (slug-insensitive so "My Clips"/"my clips" can't
        # coexist and confuse agent targeting).
        with get_db() as conn:
            rows = conn.execute(
                "SELECT label FROM nango_connections WHERE user_id = ? "
                "AND provider_config_key = ?",
                (user_id, request.provider),
            ).fetchall()
        labels = {(dict(r) if not isinstance(r, dict) else r)["label"] or "default"
                  for r in rows}
        if label in labels:
            raise HTTPException(
                status_code=409,
                detail=f"An account labeled '{label}' already exists for "
                       f"{request.provider}. Pick a different label or "
                       "disconnect it first.")
    else:
        # Legacy flow: refuse if this provider already has any account —
        # adding more requires a label so each is targetable.
        with get_db() as conn:
            existing = conn.execute(
                "SELECT label FROM nango_connections "
                "WHERE user_id = ? AND provider_config_key = ? LIMIT 1",
                (user_id, request.provider),
            ).fetchone()
        if existing:
            row = (dict(existing) if not isinstance(existing, dict) else existing)
            raise HTTPException(
                status_code=409,
                detail=f"{request.provider} is already connected as "
                       f"'{row.get('label') or 'default'}'. To add another "
                       "account, provide a new account label.")

    # Nango 0.71.4 sessions can't carry connection_id (strict schema) —
    # consent creates a connection with a server-generated id, which the
    # frontend CLAIMS with the label after the popup resolves (see /claim).
    result = nango_client.mint_connect_session(
        user_id, _user_email(user_id), [request.provider],
    )
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    result["label"] = request.label
    return result


class ClaimAccountRequest(BaseModel):
    provider: str
    label: str


@router.post("/claim")
async def claim_account(request: ClaimAccountRequest,
                        authorization: Optional[str] = Header(None)):
    """After consent completes, attach the user's label to the NEW Nango
    connection (0.71.4 generates connection ids server-side, so the label
    is bound by diffing live connections against our known rows)."""
    user_id = get_user_id_from_token(authorization)
    _require_configured()
    if request.provider not in nango_client.ENABLED_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown OAuth provider")
    label = request.label.strip()
    if not label or len(label) > 60:
        raise HTTPException(status_code=400, detail="Invalid account label")

    live = [c for c in nango_client.list_connections_for_user(user_id)
            if c.get("provider_config_key") == request.provider]
    live_ids = {c.get("connection_id") for c in live}
    with get_db() as conn:
        rows = conn.execute(
            "SELECT connection_id, label FROM nango_connections "
            "WHERE user_id = ? AND provider_config_key = ?",
            (user_id, request.provider),
        ).fetchall()
    known = [(dict(r) if not isinstance(r, dict) else r) for r in rows]
    known_ids = {r["connection_id"] for r in known}
    known_labels = {r["label"] or "default" for r in known}
    if label in known_labels:
        raise HTTPException(status_code=409,
                            detail=f"Label '{label}' is already used for "
                                   f"{request.provider}.")

    new_ids = [cid for cid in live_ids if cid not in known_ids]
    if len(new_ids) == 1:
        cid = new_ids[0]
        display = nango_client.get_connection_metadata(
            next(c for c in live if c.get("connection_id") == cid))
        # Real identity (handle/channel name + account email where the
        # provider exposes it) — best-effort, so the row shows WHO the
        # account belongs to, not the DreamAgent login email.
        identity = nango_client.fetch_identity(request.provider, cid)
        if identity:
            display.update(identity)
        with get_db() as conn:
            conn.execute(
                """INSERT INTO nango_connections
                   (user_id, provider_config_key, connection_id, end_user_id,
                    label, metadata, is_default)
                   VALUES (?, ?, ?, ?, ?, ?::jsonb, false)
                   ON CONFLICT (user_id, provider_config_key, connection_id)
                   DO UPDATE SET label = EXCLUDED.label,
                                 metadata = EXCLUDED.metadata""",
                (user_id, request.provider, cid, str(user_id), label,
                 json.dumps(display)),
            )
            # First account for this provider becomes the default
            has_default = conn.execute(
                "SELECT 1 FROM nango_connections WHERE user_id = ? "
                "AND provider_config_key = ? AND is_default LIMIT 1",
                (user_id, request.provider),
            ).fetchone() is not None
            if not has_default:
                conn.execute(
                    "UPDATE nango_connections SET is_default = true "
                    "WHERE user_id = ? AND provider_config_key = ? "
                    "AND connection_id = ?",
                    (user_id, request.provider, cid),
                )
            conn.commit()
        logger.info("[NANGO] user %s claimed %s account '%s' (%s)",
                    user_id, request.provider, label, cid)
        return {"claimed": True, "connection_id": cid, "label": label}

    if not new_ids:
        # No new connection — user likely abandoned consent or re-authorized
        # an existing account. 409 with actionable message.
        raise HTTPException(
            status_code=409,
            detail="No new connection found to claim. Complete the consent "
                   "popup first, then try again — or the account may "
                   "already be connected.")
    raise HTTPException(
        status_code=409,
        detail=f"{len(new_ids)} new connections found (parallel connects?) "
               "— refresh the page and label them via disconnect/reconnect.")


# ----------------------------------------------------------------------
# Per-connection management
# ----------------------------------------------------------------------

def _owned_connection(user_id: int, provider: str, connection_id: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM nango_connections WHERE user_id = ? "
            "AND provider_config_key = ? AND connection_id = ?",
            (user_id, provider, connection_id),
        ).fetchone()
    return (dict(row) if row and not isinstance(row, dict) else row) if row else None


@router.delete("/{provider}/{connection_id}")
async def disconnect_account(provider: str, connection_id: str,
                             authorization: Optional[str] = Header(None)):
    """Disconnect ONE account: delete the Nango connection (revokes stored
    tokens) and our mapping row. If it was the default, the oldest
    remaining account becomes the new default. Ownership enforced by
    user_id in every WHERE."""
    user_id = get_user_id_from_token(authorization)
    _require_configured()
    local = _owned_connection(user_id, provider, connection_id)
    if not local:
        raise HTTPException(status_code=404,
                            detail="No such connected account for this provider")
    nango_client.delete_connection(connection_id, provider)
    with get_db() as conn:
        conn.execute(
            "DELETE FROM nango_connections WHERE user_id = ? "
            "AND provider_config_key = ? AND connection_id = ?",
            (user_id, provider, connection_id),
        )
        # Promote oldest remaining account to default if we removed it
        remaining_default = conn.execute(
            "SELECT 1 FROM nango_connections WHERE user_id = ? "
            "AND provider_config_key = ? AND is_default LIMIT 1",
            (user_id, provider),
        ).fetchone()
        if not remaining_default:
            conn.execute(
                "UPDATE nango_connections SET is_default = true, "
                "label = COALESCE(label, 'default') WHERE id = ("
                "  SELECT id FROM nango_connections WHERE user_id = ? "
                "  AND provider_config_key = ? "
                "  ORDER BY created_at ASC, id ASC LIMIT 1)",
                (user_id, provider),
            )
        conn.commit()
    logger.info("[NANGO] user %s disconnected %s account %s",
                user_id, provider, connection_id)
    return {"disconnected": True, "connection_id": connection_id}


@router.delete("/{provider}")
async def disconnect(provider: str, authorization: Optional[str] = Header(None)):
    """Legacy disconnect: removes the DEFAULT account for the provider.
    Prefer DELETE /{provider}/{connection_id} for multi-account."""
    user_id = get_user_id_from_token(authorization)
    _require_configured()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM nango_connections WHERE user_id = ? "
            "AND provider_config_key = ? "
            "ORDER BY (is_default = false), created_at ASC LIMIT 1",
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
            "DELETE FROM nango_connections WHERE user_id = ? "
            "AND provider_config_key = ? AND connection_id = ?",
            (user_id, provider, connection_id or ""),
        )
        remaining_default = conn.execute(
            "SELECT 1 FROM nango_connections WHERE user_id = ? "
            "AND provider_config_key = ? AND is_default LIMIT 1",
            (user_id, provider),
        ).fetchone()
        if not remaining_default:
            conn.execute(
                "UPDATE nango_connections SET is_default = true, "
                "label = COALESCE(label, 'default') WHERE id = ("
                "  SELECT id FROM nango_connections WHERE user_id = ? "
                "  AND provider_config_key = ? "
                "  ORDER BY created_at ASC, id ASC LIMIT 1)",
                (user_id, provider),
            )
        conn.commit()
    logger.info("[NANGO] user %s disconnected %s (connection %s)",
                user_id, provider, connection_id or "none")
    return {"disconnected": True}


class RenameAccountRequest(BaseModel):
    label: str


@router.patch("/{provider}/{connection_id}")
async def rename_account(provider: str, connection_id: str,
                          request: RenameAccountRequest,
                          authorization: Optional[str] = Header(None)):
    """Rename an account's label (no re-consent needed). The label is what
    agents target via proxy_call(account=...)."""
    user_id = get_user_id_from_token(authorization)
    _require_configured()
    if provider not in nango_client.ENABLED_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown OAuth provider")
    label = request.label.strip()
    if not label or len(label) > 60:
        raise HTTPException(status_code=400,
                            detail="Label must be 1-60 characters")
    if not _owned_connection(user_id, provider, connection_id):
        raise HTTPException(status_code=404,
                            detail="No such connected account for this provider")
    with get_db() as conn:
        dup = conn.execute(
            "SELECT 1 FROM nango_connections WHERE user_id = ? "
            "AND provider_config_key = ? AND label = ? "
            "AND connection_id <> ?",
            (user_id, provider, label, connection_id),
        ).fetchone()
        if dup:
            raise HTTPException(status_code=409,
                                detail=f"Label '{label}' is already used for "
                                       f"{provider}.")
        conn.execute(
            "UPDATE nango_connections SET label = ? "
            "WHERE user_id = ? AND provider_config_key = ? AND connection_id = ?",
            (label, user_id, provider, connection_id),
        )
        conn.commit()
    logger.info("[NANGO] user %s renamed %s account %s -> '%s'",
                user_id, provider, connection_id, label)
    return {"renamed": True, "connection_id": connection_id, "label": label}


@router.post("/{provider}/{connection_id}/default")
async def set_default_account(provider: str, connection_id: str,
                              authorization: Optional[str] = Header(None)):
    """Make the given connected account the provider default (used by
    proxy_call when no account is specified)."""
    user_id = get_user_id_from_token(authorization)
    _require_configured()
    if not _owned_connection(user_id, provider, connection_id):
        raise HTTPException(status_code=404,
                            detail="No such connected account for this provider")
    with get_db() as conn:
        conn.execute(
            "UPDATE nango_connections SET is_default = false "
            "WHERE user_id = ? AND provider_config_key = ?",
            (user_id, provider),
        )
        conn.execute(
            "UPDATE nango_connections SET is_default = true "
            "WHERE user_id = ? AND provider_config_key = ? AND connection_id = ?",
            (user_id, provider, connection_id),
        )
        conn.commit()
    return {"provider": provider, "default_connection_id": connection_id}
