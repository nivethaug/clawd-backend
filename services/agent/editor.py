#!/usr/bin/env python3
"""
Agent AI Editor - Enhances the automation agent's executor.py.

Subclass of SchedulerEditor: identical mechanics (Claude Code session,
backup/rollback, validation). Only the prompt differs — the agent prompt
presents the unified capability menu:

  1. Connected OAuth integrations  -> api_client.proxy_call(provider, ...)
  2. Key-based managed integrations -> direct calls with os.environ[KEY]
  3. Custom env keys (docs URL)     -> the model composes the client itself

plus declarative conditions (payload["when"]) and cross-run state
(api_client.state_get/state_set).
"""

import logging

from services.scheduler.editor import SchedulerEditor
from workflow_prompt_meta import build_workflow_meta_block
from integration_prompt_block import build_external_integrations_block, build_uploaded_files_block
from sandbox_limits_prompt import sandbox_limits_block
from services.container_storage import to_container_path

logger = logging.getLogger("services.agent.editor")

# project_types ids are SERIAL — resolve the 'agent' id at runtime, cached.
_AGENT_TYPE_ID: int | None = None


def _agent_type_id() -> int:
    global _AGENT_TYPE_ID
    if _AGENT_TYPE_ID is None:
        from database_adapter import get_db
        with get_db() as conn:
            row = conn.execute(
                "SELECT id FROM project_types WHERE type = 'agent'"
            ).fetchone()
        d = (dict(row) if row and not isinstance(row, dict) else row) if row else {}
        _AGENT_TYPE_ID = int(d.get("id", 0)) or 0
    return _AGENT_TYPE_ID


class AgentEditor(SchedulerEditor):
    """AI-powered automation agent executor enhancer."""

    def _build_prompt(self, description: str, project_name: str) -> str:
        """Agent-voiced enhancement prompt (mechanics identical to scheduler)."""
        backend_url = self._read_project_env_value("BACKEND_URL") or self.backend_url
        jobs_api_url = f"{backend_url}/api/scheduler/projects/{self.project_id}/jobs"
        env_config = self._detect_configured_channels()
        channels_block = self._format_channels_block(env_config)
        meta_block = build_workflow_meta_block(
            project_type_id=_agent_type_id(),
            project_type="agent",
            operation="create",
            workflow="agent_create",
            project_name=project_name,
            project_id=self.project_id,
            project_path=to_container_path(str(self.project_path)),
            service_path=to_container_path(str(self.project_path / "scheduler")),
            prompt_kind="agent_ai_enhancement",
            env_config=env_config,
        )

        integrations_block = build_external_integrations_block(self.project_id)
        uploads_block = build_uploaded_files_block(self.project_id)

        trigger_url = ""
        try:
            from api.triggers_router import _ensure_trigger_token
            import os as _os
            _tok = _ensure_trigger_token(self.project_id)
            _base = _os.getenv("SCHEDULER_BACKEND_URL", "https://api.dreamagent.cloud").rstrip("/")
            trigger_url = f"{_base}/api/triggers/{_tok}"
        except Exception:
            trigger_url = f"(get it later: curl -s {backend_url}/api/triggers/info/{self.project_id})"

        return f"""{meta_block}
Project: {project_name} (ID: {self.project_id}) — an AUTOMATION AGENT.
The user's idea, in their words: "{description}"

Your job: turn this idea into scheduled automation by writing handlers in
scheduler/executor.py (and helpers in services/api_client.py when needed),
then create the job via the REST API. Compose freely from the capability
menu below — you are NOT limited to any fixed action list.

{integrations_block}
{uploads_block}
{sandbox_limits_block()}
Allowed files to modify:
- scheduler/executor.py (add task handlers + routes) — PRIMARY file to modify
- services/api_client.py — ONLY if you need a NEW API function that doesn't exist yet
- services/web_scraper.py — ONLY to extend the existing scraper when website data is required

DO NOT modify any other files. DO NOT read .env (it is security-blocked; the
configuration you need is already provided below).

==================================================
CAPABILITY MENU — HOW THIS AGENT ACTS
==================================================

Surface 1 — Connected OAuth accounts (from the integrations block above):
    api_client.proxy_call(provider, method, endpoint, body, params)
    The platform injects the account token server-side. Example:
        r = api_client.proxy_call("google-sheet", "PUT",
              "v4/spreadsheets/{id}/values/Log!A1?valueInputOption=RAW",
              body={{"values": [[ts, price]]}})
    Capabilities and endpoint examples per connected provider are listed in
    the integrations block above — use them.

Surface 2 — Key-based managed integrations (also in the integrations block,
    "AVAILABLE EXTERNAL INTEGRATIONS" table): call the provider API
    directly with os.environ["KEY"] (e.g. RESEND_API_KEY, SERPER_API_KEY,
    SLACK_WEBHOOK_URL, GITHUB_TOKEN). The table lists each key's
    capabilities + docs URL.

Surface 3 — Custom env keys (same table when present): compose the client
    yourself from the docs URL, reading the value by env var NAME only.

Built-in helpers in api_client.py (use, don't recreate):
- get_crypto_price / get_crypto_price_num, get_weather, get_news
- fetch_json(url, params), fetch_page(url, extract_js) — fast scraping
- proxy_call(...) — Surface 1 above
- state_get() / state_set(dict) — cross-run memory (below)

==================================================
DELIVERY CHANNELS (pre-computed — DO NOT READ .env)
==================================================

{channels_block}

Channel config is ALSO the `env_config` key in <DREAMPILOT_WORKFLOW_META>.
The executor's existing sender functions: _send_telegram/_send_discord/
_send_email/_call_api. If the requested channel is not configured, use the
configured ones and note it in the message.

==================================================
EVENT TRIGGERS (webhook -> run) — if the idea implies one
==================================================

This agent has a webhook URL; external services POSTing to it fire the
agent's job_type="event" jobs within ~10s:

    {trigger_url}

If the idea implies reacting to external events ("when a GitHub issue...",
"when Stripe payment...", "when someone calls my webhook..."):
1. Add an event handler reading payload["event"] = {{"headers": {{safe
   subset}}, "body": "<raw>", "body_json": {{...}}}}
2. Create the job with "job_type": "event", "schedule_value": "event"
   (dormant — runs ONLY when the webhook fires)
3. Tell the user (in your final message) to paste the URL into the
   external service's webhook settings — plain POST, the URL is the
   credential, 64KB body cap.

==================================================
CONDITIONS + STATE ("only when ...")
==================================================

Jobs support declarative conditions in the payload:
    "when": [{{"var": "btc_price_num", "op": ">", "value": 100000}},
             {{"var": "views", "op": "changed"}}]
Ops: > < >= <= == != contains changed. All must pass or the run is skipped
(logged as "skipped: ...") — the handler never fires.

Every resolved fetch var is auto-persisted as last_<var> in platform state,
so "changed" works on the NEXT run with zero code. For custom change logic,
call api_client.state_get()/state_set() from your handler (state_set is a
FULL replace — merge first).

==================================================
EXTENSION POINTS (same as always)
==================================================

1. FETCH_DATA_REGISTRY — dynamic {{{{variable}}}} resolution:
   FETCH_DATA_REGISTRY["my_metric"] = lambda: _fetch_my_metric()
2. execute_task() routing:
   elif task_type == "my_task":
       status, message = _my_task(payload)

Add your handlers BELOW existing ones. Keep existing handlers intact.
Message formatting: plain text, no parse_mode, no double-$ with
{{{{variables}}}} (the variable already carries formatting).

==================================================
JOB CREATION - REQUIRED FINAL STEP
==================================================

⚠️ CRITICAL — DO NOT PROBE PORTS. DO NOT try localhost, 127.0.0.1, or
host.docker.internal. The backend API is at {backend_url} — the ONLY
reachable URL. The worker VPS IP is allowlisted so requests from here
bypass JWT auth — no Authorization header needed.

After modifying files, you MUST create the job by EXECUTING this curl.
Do NOT just print it — actually RUN it using Bash:

    curl -s -X POST {jobs_api_url} \\
      -H "Content-Type: application/json" \\
      -d '{{"
        "job_type": "interval",
        "schedule_value": "5m",
        "task_type": "YOUR_TASK_TYPE",
        "payload": {{{{
            "text": "Status: {{{{my_metric}}}}",
            "fetch": ["my_metric"],
            "when": [{{"var": "my_metric", "op": "changed"}}]
        }}}}
      }}'

Rules:
- task_type MUST match the elif route you added in execute_task()
- job_type: "interval" | "daily" | "once"; schedule_value: "30s", "5m",
  "1h", "2d", or "daily:09:00" — derive from the description
- "fetch" array is REQUIRED when using {{{{variable}}}} placeholders
- "when" is optional — add it only when the idea implies a condition or
  change-detection

==================================================
CRITICAL RULES
==================================================

🔴 RULE ZERO: CHECK JOB LOGS BEFORE FIXING ANYTHING.
    curl -s $BACKEND_URL/api/scheduler/jobs/JOB_ID/logs | python3 -m json.tool

1. KEEP execute_task signature: def execute_task(job: dict) -> dict
2. KEEP all existing handlers (telegram, discord, email, api, trade)
3. KEEP FETCH_DATA_REGISTRY, resolve_content and the when/state logic
4. Return {{"status": "success"|"failed", "message": str}} from all handlers
5. DO NOT create new files; DO NOT add unavailable imports
6. Use services.api_client for ALL external calls; proxy_call for OAuth
7. YOU MUST create the job via curl after modifying files
8. AFTER editing ANY .py file, run:
   python -c "import py_compile; py_compile.compile('FILE_PATH', doraise=True)"
   If compilation fails, FIX immediately.

NOTIFICATION DISCIPLINE (default for watcher/monitor agents):
- Message the user only on CHANGE (value differs from state), MILESTONE/
  threshold crossed, or FAILURE/anomaly. Unchanged observations are logged
  ("processed, no change") — never messaged. Silence means stable.
- Prefer declarative conditions ("when": [{{"var": X, "op": "changed"}}]) over
  hand-written suppression code.
- Offer a daily digest instead of per-run pings for heartbeat lovers.
- If the user explicitly asks "notify me on every run", obey — default, not rule.

## USER REQUEST

Build this automation agent: {description}
"""
