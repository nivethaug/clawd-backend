"""
Environment Variable Registry Service

Provides CRUD operations and lookups for the `env_variable_registry` table.

IMPORTANT: This module only manages METADATA (title, description, docs link,
category, sensitivity flag). It does NOT store runtime env values.
Actual values continue to live in project .env files — see ENV_SUBDIR_MAP
in env_manager.py for the exact path per type
(website: backend/.env, telegram: telegram/.env, discord: discord/.env,
scheduler: project-root .env).

Usage:
    from env_registry_service import (
        list_registry,
        get_registry_entry,
        lookup_many,
        create_entry,
        update_entry,
        delete_entry,
    )
"""

import re
import logging
from typing import Dict, List, Optional, Any

from database_adapter import get_db

logger = logging.getLogger(__name__)


# ============================================================================
# VALIDATION
# ============================================================================

# Valid env var key format: uppercase letters, digits, underscores only,
# must start with a letter.
KEY_REGEX = re.compile(r"^[A-Z][A-Z0-9_]*$")

# Supported categories. New categories can be added here (or via admin API
# since the DB column is VARCHAR and does not enforce this list).
SUPPORTED_CATEGORIES = {
    "AI",
    "Database",
    "Payments",
    "Email",
    "Bots",
    "Integrations",
    "Custom",
}


class RegistryValidationError(Exception):
    """Raised when registry entry fields fail validation."""
    pass


def _validate_key(key: str) -> None:
    if not key or not KEY_REGEX.match(key):
        raise RegistryValidationError(
            f"Invalid key_name '{key}': must be uppercase letters, digits, "
            f"and underscores only, starting with a letter."
        )


def _validate_entry(
    key_name: str,
    title: str,
    category: str,
) -> None:
    """Validate fields before insert/update."""
    _validate_key(key_name)
    if not title or not title.strip():
        raise RegistryValidationError("title is required")
    if not category or not category.strip():
        raise RegistryValidationError("category is required")
    # Category is advisory — we allow any non-empty string so future
    # categories can be added via the admin API without code changes.


def _row_to_dict(row: Any) -> Dict[str, Any]:
    """Normalize a DB row (dict or tuple) into a plain dict."""
    if isinstance(row, dict):
        return {
            "id": row["id"],
            "key_name": row["key_name"],
            "title": row["title"],
            "description": row.get("description"),
            "docs_url": row.get("docs_url"),
            "category": row["category"],
            "is_sensitive": row["is_sensitive"],
            "created_at": str(row["created_at"]) if row.get("created_at") else None,
            "updated_at": str(row["updated_at"]) if row.get("updated_at") else None,
        }
    return {
        "id": row[0],
        "key_name": row[1],
        "title": row[2],
        "description": row[3],
        "docs_url": row[4],
        "category": row[5],
        "is_sensitive": row[6],
        "created_at": str(row[7]) if row[7] else None,
        "updated_at": str(row[8]) if row[8] else None,
    }


# ============================================================================
# READ
# ============================================================================

def list_registry(
    category: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    List all registry entries, optionally filtered by category.

    Returns:
        List of registry entry dicts.
    """
    with get_db() as conn:
        if category:
            rows = conn.execute(
                """SELECT id, key_name, title, description, docs_url,
                          category, is_sensitive, created_at, updated_at
                   FROM env_variable_registry
                   WHERE category = ?
                   ORDER BY category, key_name""",
                (category,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, key_name, title, description, docs_url,
                          category, is_sensitive, created_at, updated_at
                   FROM env_variable_registry
                   ORDER BY category, key_name"""
            ).fetchall()

    return [_row_to_dict(r) for r in rows]


def get_registry_entry(key_name: str) -> Optional[Dict[str, Any]]:
    """Get a single registry entry by key_name. Returns None if not found."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT id, key_name, title, description, docs_url,
                      category, is_sensitive, created_at, updated_at
               FROM env_variable_registry
               WHERE key_name = ?""",
            (key_name,),
        ).fetchone()

    if not row:
        return None
    return _row_to_dict(row)


def get_registry_entry_by_id(entry_id: int) -> Optional[Dict[str, Any]]:
    """Get a single registry entry by id. Returns None if not found."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT id, key_name, title, description, docs_url,
                      category, is_sensitive, created_at, updated_at
               FROM env_variable_registry
               WHERE id = ?""",
            (entry_id,),
        ).fetchone()

    if not row:
        return None
    return _row_to_dict(row)


def lookup_many(key_names: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Batch-lookup metadata for multiple keys.

    Args:
        key_names: List of env var key names to look up.

    Returns:
        Dict mapping key_name -> entry dict. Keys not found in the registry
        are simply absent from the result.
    """
    if not key_names:
        return {}

    # Deduplicate
    unique_keys = list(dict.fromkeys(key_names))
    if not unique_keys:
        return {}

    with get_db() as conn:
        # Build parameterized IN clause
        placeholders = ", ".join(["?"] * len(unique_keys))
        rows = conn.execute(
            f"""SELECT id, key_name, title, description, docs_url,
                       category, is_sensitive, created_at, updated_at
                FROM env_variable_registry
                WHERE key_name IN ({placeholders})""",
            tuple(unique_keys),
        ).fetchall()

    return {entry["key_name"]: entry for entry in (_row_to_dict(r) for r in rows)}


# ============================================================================
# CREATE
# ============================================================================

def create_entry(
    key_name: str,
    title: str,
    description: Optional[str] = None,
    docs_url: Optional[str] = None,
    category: str = "Custom",
    is_sensitive: bool = True,
) -> Dict[str, Any]:
    """
    Create a new registry entry.

    Raises:
        RegistryValidationError: If fields are invalid.
        ValueError: If key_name already exists.
    """
    _validate_entry(key_name, title, category)

    key_name = key_name.strip()
    title = title.strip()

    with get_db() as conn:
        # Check for existing key
        existing = conn.execute(
            "SELECT id FROM env_variable_registry WHERE key_name = ?",
            (key_name,),
        ).fetchone()
        if existing:
            raise ValueError(f"Registry entry for '{key_name}' already exists")

        conn.execute(
            """INSERT INTO env_variable_registry
               (key_name, title, description, docs_url, category, is_sensitive)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (key_name, title, description, docs_url, category, is_sensitive),
        )
        conn.commit()

    logger.info(f"[ENV_REGISTRY] Created entry for '{key_name}'")
    return get_registry_entry(key_name)  # type: ignore[return-value]


# ============================================================================
# UPDATE
# ============================================================================

def update_entry(
    entry_id: int,
    *,
    key_name: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    docs_url: Optional[str] = None,
    category: Optional[str] = None,
    is_sensitive: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """
    Update an existing registry entry. Only provided fields are updated.

    Args:
        entry_id: Registry entry ID.

    Returns:
        Updated entry dict, or None if entry not found.

    Raises:
        RegistryValidationError: If provided fields are invalid.
        ValueError: If new key_name collides with an existing entry.
    """
    existing = get_registry_entry_by_id(entry_id)
    if not existing:
        return None

    updates: Dict[str, Any] = {}

    if key_name is not None and key_name != existing["key_name"]:
        _validate_key(key_name)
        key_name = key_name.strip()
        # Check collision
        with get_db() as conn:
            clash = conn.execute(
                "SELECT id FROM env_variable_registry WHERE key_name = ? AND id != ?",
                (key_name, entry_id),
            ).fetchone()
        if clash:
            raise ValueError(f"key_name '{key_name}' already in use")
        updates["key_name"] = key_name

    if title is not None:
        if not title.strip():
            raise RegistryValidationError("title cannot be empty")
        updates["title"] = title.strip()

    if description is not None:
        updates["description"] = description if description else None

    if docs_url is not None:
        updates["docs_url"] = docs_url if docs_url else None

    if category is not None:
        if not category.strip():
            raise RegistryValidationError("category cannot be empty")
        updates["category"] = category.strip()

    if is_sensitive is not None:
        updates["is_sensitive"] = bool(is_sensitive)

    if not updates:
        return existing

    set_clauses = ", ".join([f"{col} = ?" for col in updates.keys()])
    params = list(updates.values()) + [entry_id]

    with get_db() as conn:
        conn.execute(
            f"""UPDATE env_variable_registry
                SET {set_clauses}, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?""",
            tuple(params),
        )
        conn.commit()

    logger.info(f"[ENV_REGISTRY] Updated entry id={entry_id}: {list(updates.keys())}")
    return get_registry_entry_by_id(entry_id)


# ============================================================================
# DELETE
# ============================================================================

def delete_entry(entry_id: int) -> bool:
    """
    Delete a registry entry by ID.

    Returns:
        True if deleted, False if not found.

    Note: Deleting a registry entry does NOT affect any .env files — it only
    removes the metadata. Variables in .env files remain untouched.
    """
    existing = get_registry_entry_by_id(entry_id)
    if not existing:
        return False

    with get_db() as conn:
        conn.execute(
            "DELETE FROM env_variable_registry WHERE id = ?",
            (entry_id,),
        )
        conn.commit()

    logger.info(f"[ENV_REGISTRY] Deleted entry id={entry_id} ('{existing['key_name']}')")
    return True
