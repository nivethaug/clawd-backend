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
    integrations (env-key based) plus the owner's connected OAuth accounts."""
    return _env_key_block(project_id) + _oauth_block(project_id)


def build_oauth_block_for_user(user_id: Optional[int], project_id_for_snippet: Optional[int] = None) -> str:
    """OAuth block for a user who is CREATING a project (no project row yet).

    Same content as _oauth_block but keyed on user_id directly; the
    copy-paste snippet uses a placeholder project id that the agent will
    replace once the project exists. Returns "" when the user has no
    connected OAuth integrations.
    """
    if not user_id:
        return ""
    try:
        from database_adapter import get_db
        with get_db() as conn:
            rows = conn.execute(
                "SELECT provider_config_key FROM nango_connections WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        connected = sorted({
            (dict(r) if not isinstance(r, dict) else r)["provider_config_key"]
            for r in rows
        })
        if not connected:
            return ""

        from services.integrations import nango_client
        import os as _os
        _BASE = _os.getenv("SCHEDULER_BACKEND_URL", "https://api.dreamagent.cloud")
        titles = ", ".join(
            nango_client.ENABLED_PROVIDERS.get(p, {}).get("title", p) for p in connected
        )
        provider_example = connected[0]
        pid_hint = str(project_id_for_snippet) if project_id_for_snippet else "<PROJECT_ID>"

        return f"""
## 🔑 CONNECTED OAUTH INTEGRATIONS (your account — NO env keys)

You have connected: **{titles}**. No API keys exist in `.env` for these —
the account authorization lives on the platform. Wire the project to call them
through the platform proxy:

```python
# Python example (project backend; SECRET_KEY will be in the project .env)
import os, requests
r = requests.post(
    "{_BASE}/internal/integrations/proxy",
    headers={{"Authorization": f"Bearer {{os.environ['SECRET_KEY']}}",
              "X-Project-Id": "{pid_hint}",
              "Content-Type": "application/json"}},
    json={{"provider": "{provider_example}", "method": "GET",
           "endpoint": "youtube/v3/channels?part=snippet&mine=true"}},
    timeout=30,
)
data = r.json()
```

**Rules:**
- NEVER ask the user for an API key / token / channel ID for the connected services above —
  the account is already authorized.
- The X-Project-Id above is `{pid_hint}` — after the project is created, use the real
  project id from PROJECT_ID in .env (or hardcode it once known).
- All provider calls go through the proxy (server-side). No tokens in code or .env.
- If the proxy returns 409 "not connected", tell the user to connect it in
  Settings → Integrations (one click).
- If the task involves the connected services, wire them into the app NOW.
"""
    except Exception as e:
        logger.warning("Failed to build OAuth block for user %s: %s", user_id, e)
        return ""


def _oauth_block(project_id: Optional[int]) -> str:
    """Additive section: OAuth integrations connected by the project OWNER
    (Settings → Integrations, Nango-backed). No keys exist in .env — the
    model must call the platform proxy instead. Returns "" when none."""
    if not project_id:
        return ""
    try:
        from database_adapter import get_db
        with get_db() as conn:
            proj = conn.execute(
                "SELECT user_id FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        if not proj:
            return ""
        owner_id = (dict(proj) if not isinstance(proj, dict) else proj)["user_id"]
        with get_db() as conn:
            rows = conn.execute(
                "SELECT provider_config_key FROM nango_connections WHERE user_id = ?",
                (owner_id,),
            ).fetchall()
        connected = sorted({
            (dict(r) if not isinstance(r, dict) else r)["provider_config_key"]
            for r in rows
        })
        if not connected:
            return ""

        from services.integrations import nango_client
        titles = []
        for p in connected:
            meta = nango_client.ENABLED_PROVIDERS.get(p)
            titles.append(meta["title"] if meta else p)

        import os as _os
        _BASE = _os.getenv("SCHEDULER_BACKEND_URL", "https://api.dreamagent.cloud")
        providers_list = ", ".join(titles)
        return f"""
## 🔑 CONNECTED OAUTH INTEGRATIONS (owner's account — NO env keys)

The project owner has connected: **{providers_list}**. No API keys exist in `.env` for these —
the account authorization lives on the platform. Call them through the platform proxy from the
project's backend (works for website backends, bots and scheduler jobs alike):

```python
# Python example (any project backend; SECRET_KEY is already in the project .env)
import os, requests
r = requests.post(
    "{_BASE}/internal/integrations/proxy",
    headers={{"Authorization": f"Bearer {{os.environ['SECRET_KEY']}}",
              "X-Project-Id": "{project_id}",
              "Content-Type": "application/json"}},
    json={{"provider": "{connected[0]}", "method": "GET",
           "endpoint": "youtube/v3/channels?part=snippet&mine=true"}},
    timeout=30,
)
data = r.json()
```

**Rules:**
- NEVER ask the user for an API key / token / channel ID for the connected services above —
  the account is already authorized.
- All provider calls go through the proxy (server-side). No tokens ever appear in code or .env.
- If the proxy returns 409 "not connected", tell the user to connect it in
  Settings → Integrations (one click).
"""
    except Exception as e:
        logger.warning("Failed to build OAuth integrations block: %s", e)
        return ""


def _env_key_block(project_id: Optional[int]) -> str:
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
- **This is where integrations go live.** When a task involves a listed service, wire it into
  the app AND verify it with a real API call in THIS session (creation defers live testing
  here). To test one key without exposing it: extract ONLY that variable (e.g. a one-off
  python one-liner reading just that key), report its LENGTH only, and make the test call
  from the backend side — never echo, log, or hardcode the value, and never dump the
  whole file or environment.
- In code, always reference by NAME (`os.getenv("KEY")` / `process.env.KEY`) — the value
  loads at runtime; secrets live only in backend/.env.
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
