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
        pid_hint = str(project_id_for_snippet) if project_id_for_snippet else "<PROJECT_ID>"
        return _render_oauth_section(
            connected,
            pid_hint=pid_hint,
            who="your account",
            who_verb="You have connected",
            extra_rules=[
                f"The X-Project-Id above is `{pid_hint}` — after the project is created, use the real "
                "project id from PROJECT_ID in .env (or hardcode it once known).",
                "If the task involves the connected services, wire them into the app NOW.",
            ],
        )
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
        return _render_oauth_section(
            connected,
            pid_hint=str(project_id),
            who="owner's account",
            who_verb="The project owner has connected",
            extra_rules=[],
        )
    except Exception as e:
        logger.warning("Failed to build OAuth integrations block: %s", e)
        return ""


def _render_oauth_section(connected: list, pid_hint: str, who: str,
                          who_verb: str, extra_rules: list) -> str:
    """Shared markdown renderer for connected OAuth providers.

    Per-provider reference lines come from Nango's own catalog metadata
    (base_url + docs — always accurate) merged with our PROVIDER_EXTRAS
    (example calls + gotchas Nango can't know). Falls back gracefully to
    static titles when Nango metadata is unavailable.
    """
    from services.integrations import nango_client
    import os as _os
    _BASE = _os.getenv("SCHEDULER_BACKEND_URL", "https://api.dreamagent.cloud")

    ref_lines: list[str] = []
    for p in connected:
        conf = nango_client.ENABLED_PROVIDERS.get(p, {})
        title = conf.get("title") or p
        meta = nango_client.get_provider_metadata(conf.get("nango_provider", p)) or {}
        extras = nango_client.PROVIDER_EXTRAS.get(p, {})
        bits = []
        if meta.get("base_url"):
            bits.append(f"base `{meta['base_url']}`")
        if meta.get("docs"):
            bits.append(f"docs: {meta['docs']}")
        ref_lines.append(f"- **{title}**" + (f" ({', '.join(bits)})" if bits else ""))
        for ex in extras.get("examples") or []:
            ref_lines.append(f"  - `{ex}`")
        for gotcha in extras.get("gotchas") or []:
            ref_lines.append(f"  - note: {gotcha}")

    # Snippet example endpoint: first example of the first connected provider
    # ("GET v1/pages/{id}" -> method GET + endpoint); generic fallback works
    # for the common providers.
    snippet_provider = connected[0]
    snippet_endpoint = "user"
    first_ex = (nango_client.PROVIDER_EXTRAS.get(snippet_provider, {}).get("examples") or [""])[0]
    parts = first_ex.split(" ", 1)
    if len(parts) == 2:
        snippet_endpoint = parts[1]

    providers_list = ", ".join(
        nango_client.ENABLED_PROVIDERS.get(p, {}).get("title", p) for p in connected
    )
    ref_md = "\n".join(ref_lines)
    extra_md = "".join(f"- {r}\n" for r in extra_rules)
    return f"""
## 🔑 CONNECTED OAUTH INTEGRATIONS ({who} — NO env keys)

{who_verb}: **{providers_list}**. No API keys exist in `.env` for these —
the account authorization lives on the platform. Call them through the platform proxy from the
project's backend (works for website backends, bots and scheduler jobs alike):

```python
# Python example (any project backend; SECRET_KEY is already in the project .env)
import os, requests
r = requests.post(
    "{_BASE}/api/integrations/proxy",
    headers={{"Authorization": f"Bearer {{os.environ['SECRET_KEY']}}",
              "X-Project-Id": "{pid_hint}",
              "Content-Type": "application/json"}},
    json={{"provider": "{snippet_provider}", "method": "GET",
           "endpoint": "{snippet_endpoint}"}},
    timeout=30,
)
data = r.json()
```

Provider reference — `endpoint` is the path after each provider's base URL:
{ref_md}

**Rules:**
- NEVER ask the user for an API key / token / channel ID for the connected services above —
  the account is already authorized.
- All provider calls go through the proxy (server-side). No tokens ever appear in code or .env.
- If the proxy returns 409 "not connected", tell the user to connect it in
  Settings → Integrations (one click).
{extra_md}"""


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
