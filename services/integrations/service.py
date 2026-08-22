"""
Integration Service — project ↔ global-integration links (reference +
materialize).

Model (see INTEGRATIONS_PLAN.md):
- project_integration_links = relationship source of truth
- project .env             = runtime source of truth (unchanged machinery)
- connect    = link row + SERVER-side decrypt → env_manager.write_env_file
               → restart. The secret never transits the client.
- disconnect = link removed + materialized keys removed from .env → restart
- swap       = same key name connected via a different GI requires swap=True
               (unlink old + write new; manual Custom Env vars are never
               silently overwritten)
- reconcile  = GI deleted → link survives with global_integration_id NULL
               (status revoked); stale keys cleaned lazily on demand

Security: every operation takes the user_id resolved from the auth token
server-side and re-validates project + GI ownership in SQL. Secrets are
never returned, never logged.
"""

import logging
from typing import Any, Dict, List, Optional

from database_adapter import get_db

logger = logging.getLogger("integrations.service")


def _row(r) -> Optional[Dict[str, Any]]:
    if r is None:
        return None
    return dict(r) if not isinstance(r, dict) else r


# ----------------------------------------------------------------------
# Ownership
# ----------------------------------------------------------------------

def _owned_project(project_id: int, user_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM projects WHERE id = ? AND user_id = ?",
            (project_id, user_id),
        ).fetchone()
    return row is not None


def _owned_gis(gi_ids: List[int], user_id: int) -> Dict[int, Dict[str, Any]]:
    """Fetch user-owned GIs by id. Foreign ids are silently dropped."""
    unique = list(dict.fromkeys(gi_ids))
    if not unique:
        return {}
    placeholders = ", ".join("?" for _ in unique)
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM global_integrations WHERE user_id = ? AND id IN ({placeholders})",
            (user_id, *unique),
        ).fetchall()
    return {d["id"]: d for d in (_row(r) for r in rows) if d}


# ----------------------------------------------------------------------
# Project env helpers (env_manager signatures)
#   get_project_env_info(project_id) -> (env_path, type_id, domain, name)
#   read_env_file(path) -> List[{key, value, ...}]
# ----------------------------------------------------------------------

def _env_context(project_id: int):
    """Returns (env_path, type_id, domain) or None when unresolvable."""
    try:
        from env_manager import get_project_env_info
        env_path, type_id, domain, _name = get_project_env_info(project_id)
        if not env_path:
            return None
        return env_path, type_id, domain
    except Exception as e:
        logger.warning("[INTEGRATIONS] env info failed for project %s: %s", project_id, e)
        return None


def _project_env_key_names(project_id: int) -> List[str]:
    """Key names currently in the project .env (values never touched)."""
    ctx = _env_context(project_id)
    if not ctx:
        return []
    try:
        from env_manager import read_env_file
        rows = read_env_file(ctx[0])
        return [r.get("key") for r in rows if isinstance(r, dict) and r.get("key")]
    except Exception as e:
        logger.warning("[INTEGRATIONS] env key read failed for project %s: %s", project_id, e)
        return []


# ----------------------------------------------------------------------
# Views
# ----------------------------------------------------------------------

def list_project_integrations(project_id: int, user_id: int) -> Dict[str, Any]:
    """Connected links + manual-key hints + the user's connectable GIs."""
    if not _owned_project(project_id, user_id):
        return {"error": "not_found"}

    from services.integrations.catalog import CATALOG

    with get_db() as conn:
        link_rows = conn.execute(
            """SELECT l.*, g.key_name AS gi_key_name, g.title AS gi_title,
                      g.verified AS gi_verified, g.docs_url AS gi_docs
               FROM project_integration_links l
               LEFT JOIN global_integrations g ON g.id = l.global_integration_id
               WHERE l.project_id = ?
               ORDER BY l.linked_at DESC""",
            (project_id,),
        ).fetchall()
        gi_rows = conn.execute(
            "SELECT id, key_name, title, verified, token_type, docs_url, category "
            "FROM global_integrations WHERE user_id = ? ORDER BY key_name",
            (user_id,),
        ).fetchall()

    links = [_row(r) for r in link_rows]
    gis = [_row(r) for r in gi_rows]

    # Manual hints: catalog env keys present in .env WITHOUT a link (e.g.
    # an OPENAI_API_KEY pasted months ago) — display only, never touched.
    env_keys = set(_project_env_key_names(project_id))
    all_catalog_keys = {k for d in CATALOG.values() for k in d.key_names}
    linked_keys = {k for l in links for k in (l.get("materialized_keys") or "").split(",") if k}
    manual_keys = [k for k in env_keys if k in all_catalog_keys and k not in linked_keys]

    return {
        "connected": [
            {
                "link_id": l["id"],
                "gi_id": l.get("global_integration_id"),
                "integration_type": l["integration_type"],
                "status": l["status"],
                "key_names": [k for k in (l.get("materialized_keys") or "").split(",") if k],
                "credential_title": l.get("gi_title") or l.get("gi_key_name"),
                "verified": bool(l.get("gi_verified")) if l.get("gi_key_name") else False,
                "orphaned": l.get("global_integration_id") is None,  # GI deleted
                "linked_at": l.get("linked_at"),
            }
            for l in links
        ],
        "manual_keys": manual_keys,
        "credentials": gis,  # vault entries for the Connect picker (no values)
    }


# ----------------------------------------------------------------------
# Connect / disconnect / swap
# ----------------------------------------------------------------------

def connect(
    project_id: int,
    user_id: int,
    integration_type: str,
    gi_ids: List[int],
    swap: bool = False,
) -> Dict[str, Any]:
    from services.integrations.catalog import get_def
    from secure_value import decrypt_value
    from env_manager import validate_keys, write_env_file

    d = get_def(integration_type)
    if not d:
        return {"error": "unknown_integration"}
    if not _owned_project(project_id, user_id):
        return {"error": "not_found"}

    # Multi-key defs (razorpay) need one GI per key, in def order.
    if d.multi_key:
        if len(gi_ids) != len(d.key_names):
            return {"error": "needs_all_keys",
                    "detail": f"{d.title} requires one credential per key: "
                              f"{', '.join(d.key_names)}"}
    elif len(gi_ids) != 1:
        return {"error": "single_credential"}

    owned = _owned_gis(gi_ids, user_id)
    if len(owned) != len(set(gi_ids)):
        return {"error": "credential_not_found"}
    gis = [owned[i] for i in gi_ids]

    # Each GI's key_name must match the def's key at the same position.
    for gi, key in zip(gis, d.key_names):
        if (gi.get("key_name") or "").upper() != key:
            return {"error": "key_mismatch",
                    "detail": f"credential '{gi.get('title') or gi.get('key_name')}' stores "
                              f"{gi.get('key_name')}, expected {key}"}

    ctx = _env_context(project_id)
    if not ctx:
        return {"error": "env_unavailable"}
    env_path, type_id, domain = ctx

    # Key-name collision policy (user-confirmed): distinct names coexist;
    # same name via another LINK needs swap=True; MANUAL vars are never
    # overwritten — the user removes them in Custom Env first.
    env_keys = set(_project_env_key_names(project_id))
    with get_db() as conn:
        rows = conn.execute(
            """SELECT l.* FROM project_integration_links l
               WHERE l.project_id = ? AND l.status = 'linked'""",
            (project_id,),
        ).fetchall()
    linked_rows = [_row(r) for r in rows]
    linked_by_key: Dict[str, Dict[str, Any]] = {}
    for r in linked_rows:
        for k in (r.get("materialized_keys") or "").split(","):
            if k:
                linked_by_key[k] = r

    conflicts, manual_conflicts = [], []
    for key in d.key_names:
        other = linked_by_key.get(key)
        mine = other is not None and other.get("global_integration_id") in set(gi_ids)
        if other is not None and not mine:
            conflicts.append(key)
        elif other is None and key in env_keys:
            manual_conflicts.append(key)

    if manual_conflicts:
        return {"error": "key_conflict_manual", "conflicts": manual_conflicts,
                "detail": "Key already set as a manual Custom Env variable — remove it "
                          "in Custom Env (Env dialog) first if you want the managed "
                          "integration to own it."}
    if conflicts and not swap:
        return {"error": "key_conflict", "conflicts": conflicts,
                "detail": "Key name is connected via another credential. "
                          "Retry with swap=true to replace it."}
    if conflicts and swap:
        for key in conflicts:
            other = linked_by_key.get(key)
            if other and other.get("global_integration_id") not in set(gi_ids):
                _unlink(other["id"])

    # Server-side decrypt + materialize. Values never leave this process.
    updates: Dict[str, str] = {}
    for gi, key in zip(gis, d.key_names):
        plain = decrypt_value(gi.get("value_encrypted") or "")
        if not plain:
            return {"error": "decrypt_failed"}
        updates[key] = plain

    try:
        validate_keys(updates)
    except Exception as e:
        return {"error": "invalid_keys", "detail": str(e)[:200]}
    write_env_file(env_path, updates)
    _register_metadata(d)

    with get_db() as conn:
        for gi in gis:
            # Per-GI materialization: a multi-key def (razorpay) creates one
            # link per credential, each owning ONLY its own key — so
            # disconnecting one credential never removes another's key.
            conn.execute(
                """INSERT INTO project_integration_links
                   (project_id, global_integration_id, integration_type,
                    materialized_keys, status, linked_at, last_synced_at)
                   VALUES (?, ?, ?, ?, 'linked', NOW(), NOW())
                   ON CONFLICT (project_id, global_integration_id) DO UPDATE SET
                     status = 'linked',
                     materialized_keys = EXCLUDED.materialized_keys,
                     integration_type = EXCLUDED.integration_type,
                     last_synced_at = NOW()""",
                (project_id, gi["id"], integration_type, gi["key_name"]),
            )
        conn.commit()

    restarted = _restart_project(project_id, type_id, domain)
    logger.info("[INTEGRATIONS] project %s connected %s via GIs %s (swap=%s)",
                project_id, integration_type, gi_ids, swap)
    return {"connected": True, "key_names": d.key_names,
            "restarted": restarted, "swapped": bool(conflicts)}


def disconnect(project_id: int, user_id: int, gi_id: int) -> Dict[str, Any]:
    if not _owned_project(project_id, user_id):
        return {"error": "not_found"}
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM project_integration_links "
            "WHERE project_id = ? AND global_integration_id = ?",
            (project_id, gi_id),
        ).fetchone()
    link = _row(row)
    if not link:
        return {"error": "not_found"}

    ctx = _env_context(project_id)
    keys = [k for k in (link.get("materialized_keys") or "").split(",") if k]
    if keys and ctx:
        try:
            from env_manager import delete_env_keys
            delete_env_keys(ctx[0], keys)
        except Exception as e:
            logger.warning("[INTEGRATIONS] key cleanup failed for project %s: %s", project_id, e)

    with get_db() as conn:
        conn.execute("DELETE FROM project_integration_links WHERE id = ?", (link["id"],))
        conn.commit()

    restarted = _restart_project(project_id, ctx[1], ctx[2]) if ctx else False
    logger.info("[INTEGRATIONS] project %s disconnected GI %s", project_id, gi_id)
    return {"disconnected": True, "removed_keys": keys, "restarted": restarted}


# ----------------------------------------------------------------------
# Revocation / reconcile
# ----------------------------------------------------------------------

def on_global_integration_deleted(gi_id: int) -> None:
    """Hook for the GI delete endpoint: links survive (gi → NULL, status
    revoked) so stale keys can be reconciled lazily later."""
    with get_db() as conn:
        conn.execute(
            """UPDATE project_integration_links
               SET status = 'revoked', global_integration_id = NULL
               WHERE global_integration_id = ?""",
            (gi_id,),
        )
        conn.commit()
    logger.info("[INTEGRATIONS] GI %s deleted — linked projects marked revoked", gi_id)


def reconcile(project_id: int, user_id: int) -> Dict[str, Any]:
    """Remove .env keys whose links are revoked/orphaned, then drop those
    links. Never touches active links or manual vars outside the catalog."""
    if not _owned_project(project_id, user_id):
        return {"error": "not_found"}
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM project_integration_links WHERE project_id = ? AND status <> 'linked'",
            (project_id,),
        ).fetchall()
    stale_links = [_row(r) for r in rows]
    stale_keys = sorted({k for r in stale_links
                         for k in (r.get("materialized_keys") or "").split(",") if k})
    removed: List[str] = []
    ctx = _env_context(project_id)
    if stale_keys and ctx:
        try:
            from env_manager import delete_env_keys
            delete_env_keys(ctx[0], stale_keys)
            removed = stale_keys
        except Exception as e:
            logger.warning("[INTEGRATIONS] reconcile cleanup failed: %s", e)
    if stale_links:
        with get_db() as conn:
            conn.execute(
                "DELETE FROM project_integration_links WHERE project_id = ? AND status <> 'linked'",
                (project_id,),
            )
            conn.commit()
    return {"reconciled": True, "removed_keys": removed}


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _unlink(link_id: int) -> None:
    with get_db() as c:
        c.execute("DELETE FROM project_integration_links WHERE id = ?", (link_id,))
        c.commit()


def _restart_project(project_id: int, type_id: int, domain: Optional[str]) -> bool:
    try:
        from env_manager import restart_project_if_required
        restart_project_if_required(project_id, type_id, domain)
        return True
    except Exception as e:
        logger.warning("[INTEGRATIONS] restart skipped for project %s: %s", project_id, e)
        return False


def _register_metadata(d) -> None:
    """Ensure registry rows exist for the def's keys (title/docs/category)."""
    try:
        from env_registry_service import create_entry, lookup_many
        existing = set(lookup_many(list(d.key_names)) or {})
        for key in d.key_names:
            if key not in existing:
                create_entry(
                    key_name=key, title=d.title,
                    description=d.description, docs_url=d.docs_url,
                    category=d.category, is_sensitive=True,
                )
    except Exception as e:
        logger.warning("[INTEGRATIONS] registry metadata upsert skipped: %s", e)
