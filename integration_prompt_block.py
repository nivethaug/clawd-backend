"""Shared builder for the "configured external integrations" prompt section.

Used by both the create-time editors (services/*/editor.py,
acp_frontend_editor_v2.py) and the chat/edit prompts (acp_chat_handler.py)
so the LLM sees the same user-added integrations everywhere.

Metadata only: key NAMES are shown, never values. The model learns WHICH
env vars are available (e.g. STRIPE_SECRET_KEY, OPENAI_API_KEY) so it can
reference them in code without reading the security-blocked .env file.
"""

from __future__ import annotations

import logging
from typing import Optional

import env_manager
import env_registry_service

logger = logging.getLogger("integration_prompt_block")

# Hide infra/auth vars even if they somehow escape SYSTEM_KEYS — these are
# platform-managed, not user integrations the model should reference.
_EXCLUDE_KEYS = frozenset({"JWT_SECRET"})
_EXCLUDE_PREFIXES = ("INTERNAL_", "SYSTEM_")


def build_external_integrations_block(project_id: Optional[int]) -> str:
    """Return a markdown section listing the project's configured external
    integrations, enriched with registry metadata.

    Args:
        project_id: The project whose .env to read.

    Returns:
        A markdown string, or "" if nothing is configured / project_id is
        missing / any error occurs (chat never breaks).
    """
    if not project_id:
        return ""

    try:
        env_path, _type, _domain, _name = env_manager.get_project_env_info(project_id)
        vars_list = env_manager.read_env_file(env_path)
        if not vars_list:
            return ""

        # Filter out platform-managed + infra vars; keep only user integrations.
        keys: list[str] = []
        for v in vars_list:
            key = v["key"]
            if key in _EXCLUDE_KEYS:
                continue
            if any(key.startswith(p) for p in _EXCLUDE_PREFIXES):
                continue
            keys.append(key)

        if not keys:
            return ""

        meta = env_registry_service.lookup_many(keys)

        lines = []
        for key in keys:
            m = meta.get(key)
            if m:
                provider = m.get("title") or key
                desc = m.get("description") or "Configured"
                docs = m.get("docs_url") or "—"
            else:
                provider = key
                desc = "Configured (no metadata registered)"
                docs = "—"
            lines.append(f"| {provider} | `{key}` | {desc} | {docs} |")

        table = "\n".join(lines)

        return f"""
## 🔌 AVAILABLE EXTERNAL INTEGRATIONS (already configured)

The following external services are configured for this project. Reuse them — do NOT ask the user to re-provide credentials.

| Provider | Env Var | Description | Docs |
|---|---|---|---|
{table}

**Rules:**
- These are already set in the environment. Reference by env var name; never request their values.
- Do NOT read `.env` or run `env`/`printenv` — they are blocked by the security guard.
- If you need an integration NOT listed here, ask the user to add it and share the docs URL.
- Testing an API key and got 403 with a non-JSON body (HTML page / "error code: 1010" /
  server: cloudflare)? That is a Cloudflare edge bot-block of the default Python
  User-Agent — NOT a bad key (a bad key returns the provider's own JSON error).
  Retry once with a browser User-Agent before concluding the key is wrong. Backend
  proxies to Cloudflare-fronted APIs (e.g. Pexels) should set a browser UA permanently.

---
"""
    except Exception as e:
        logger.warning("Failed to build external integrations block: %s", e)
        return ""
