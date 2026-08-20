"""Create-time custom environment variable helpers.

Values are written only to project .env files. Prompt metadata intentionally
contains key names, documentation URLs, and descriptions, never secret values.
"""

from typing import Any, Dict, List
from urllib.parse import urlparse

import env_manager
import env_registry_service

MAX_INITIAL_ENV_VARS = 2  # manual + imported Global Integrations combined at creation


def normalize_initial_environment_variables(items: Any) -> List[Dict[str, str]]:
    """Validate and normalize project creation environment variables."""
    if not items:
        return []
    if not isinstance(items, list):
        raise ValueError("environment_variables must be a list")
    if len(items) > MAX_INITIAL_ENV_VARS:
        raise ValueError(f"environment_variables supports at most {MAX_INITIAL_ENV_VARS} entries")

    normalized: List[Dict[str, str]] = []
    seen = set()

    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"environment_variables[{index}] must be an object")

        key = str(item.get("key") or "").strip().upper()
        value = str(item.get("value") or "").strip()
        docs_url = str(item.get("docs_url") or "").strip()
        description = str(item.get("description") or "").strip()

        if not key:
            raise ValueError(f"environment_variables[{index}].key is required")
        if key in seen:
            raise ValueError(f"Duplicate environment variable key: {key}")
        if not value:
            raise ValueError(f"environment_variables[{index}].value is required")
        if docs_url:
            parsed = urlparse(docs_url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError(f"environment_variables[{index}].docs_url must be a valid http(s) URL")

        env_manager.validate_keys({key: value})

        normalized.append({
            "key": key,
            "value": value,
            "docs_url": docs_url,
            "description": description,
        })
        seen.add(key)

    return normalized


def register_initial_environment_metadata(items: List[Dict[str, str]]) -> None:
    """Create or update env registry metadata for create-time variables."""
    for item in items or []:
        key = item["key"]
        title = key.replace("_", " ").title()
        description = item.get("description") or "Configured during project creation."
        docs_url = item["docs_url"]
        is_sensitive = env_manager._is_sensitive(key)

        existing = env_registry_service.get_registry_entry(key)
        if existing:
            env_registry_service.update_entry(
                existing["id"],
                title=existing.get("title") or title,
                description=description,
                docs_url=docs_url,
                category=existing.get("category") or "Custom",
                is_sensitive=is_sensitive,
            )
        else:
            env_registry_service.create_entry(
                key_name=key,
                title=title,
                description=description,
                docs_url=docs_url,
                category="Custom",
                is_sensitive=is_sensitive,
            )


def write_initial_environment_variables(env_path: str, items: List[Dict[str, str]]) -> None:
    """Write create-time environment values into the target project .env file."""
    if not items:
        return
    updates = {item["key"]: item["value"] for item in items}
    env_manager.validate_keys(updates)
    env_manager.write_env_file(env_path, updates)
    register_initial_environment_metadata(items)


def build_initial_integrations_prompt_block(items: List[Dict[str, str]]) -> str:
    """Return prompt-safe metadata for create-time integrations."""
    if not items:
        return ""

    lines = [
        "",
        "INITIAL EXTERNAL INTEGRATIONS:",
        "The user provided these environment variables during project creation.",
        "Values are stored in the project .env file. Never expose or hardcode values.",
        "",
        "| Env Var | Docs URL | Purpose |",
        "|---|---|---|",
    ]
    for item in items:
        purpose = item.get("description") or "Configured during project creation"
        lines.append(f"| `{item['key']}` | {item['docs_url']} | {purpose} |")

    lines.extend([
        "",
        "Integration rule:",
        "- Reference each variable IN CODE BY NAME ONLY (`os.getenv(\"KEY\")` backend /",
        "  `process.env.KEY` frontend). The value is already stored in backend/.env and",
        "  loads automatically at runtime — you never need the value to write correct code.",
        "- Do NOT try to read, cat, grep, echo, or print the value — .env and env dumps are",
        "  blocked by the platform security guard BY DESIGN. Hitting that guard is expected",
        "  and is NEVER a reason to stop, shorten, or abandon the build.",
        "- Before writing the integration, fetch the docs with `curl -L --max-time 20 <DOCS_URL>`",
        "  and build to the documented base URL, endpoint paths, auth header shape, params,",
        "  and response shape.",
        "- Live API testing happens LATER, in the first edit session — not during creation.",
        "- If the docs cannot be fetched or the auth shape is unclear, create an isolated",
        "  mock/fallback method with a comment explaining why, a clear runtime warning when",
        "  used, and a user-facing notice that the real integration is inactive.",
    ])
    return "\n".join(lines)
