"""
DreamAgent Agent Brain — two-layer decision engine for agent projects.

Layer 1 — DECISIONS (typesafe/jev-1.13 via OpenRouter /api/alpha/decisions):
    jev is a DECISIONS model, not a chat model. It answers narrow, typed
    questions (noul / choice / score) about the trigger state and returns
    structured probabilities. YOUR CODE owns the workflow — jev only
    decides. Env: AGENT_DECISION_MODEL (default typesafe/jev-1.13).

Layer 2 — GENERATION (chat model via chat/completions):
    open-ended text (replies, summaries, composed content) comes from a
    regular chat model. Env: AGENT_MODEL (default z-ai/glm-5.3-flash),
    AGENT_PROVIDER (openrouter | openai | anthropic | zai).

Called from executor.py when a job has use_ai=true or task_type=brain.

AGENT_MODE:
    "decisions" (default) — jev decides, code executes, chat model writes
    "loop"                — legacy LLM-owned tool loop (chat model required)

Env vars required (in project .env):
    OPENROUTER_API_KEY  — key for both layers (Global Integrations or manual)
    DREAMAGENT_TOOLS_URL — platform tools-api base URL
    DREAMAGENT_PROJECT_SECRET — project secret for tools-api auth
    PROJECT_ID          — this project's ID
"""

import json
import os
import urllib.request

MAX_TURNS = 6
# Generation layer (chat completions) — a CHAT model, never jev.
DEFAULT_MODEL = "z-ai/glm-5.3-flash"
# Decision layer (decisions API) — jev, typed questions only.
DEFAULT_DECISION_MODEL = "typesafe/jev-1.13"


# Provider registry — configured at creation time via project .env
# AGENT_PROVIDER: openrouter | openai | anthropic | zai
# AGENT_MODEL: model slug (e.g. z-ai/glm-5.3-flash, gpt-4o-mini)
_PROVIDERS = {
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "key_env": "OPENROUTER_API_KEY",
    },
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "key_env": "OPENAI_API_KEY",
    },
    "anthropic": {
        "url": "https://api.anthropic.com/v1/messages",
        "key_env": "ANTHROPIC_API_KEY",
    },
    "zai": {
        "url": "https://api.z.ai/api/paas/v4/chat/completions",
        "key_env": "ZAI_API_KEY",
    },
}


def _llm(messages):
    """Layer 2 — open-ended generation via a chat model."""
    provider = os.getenv("AGENT_PROVIDER", "openrouter").lower()
    model = os.getenv("AGENT_MODEL", DEFAULT_MODEL)
    cfg = _PROVIDERS.get(provider, _PROVIDERS["openrouter"])
    key = os.getenv(cfg["key_env"])
    if not key:
        raise RuntimeError(
            f"Brain not configured. {cfg['key_env']} not set. "
            f"Connect the {provider} integration in Settings, or ask in chat "
            f"to change the brain model.")
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 2000,
    }).encode()
    req = urllib.request.Request(
        cfg["url"], data=payload, method="POST",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.loads(r.read().decode())
    # OpenAI-compatible response
    if "choices" in body:
        return body["choices"][0]["message"]["content"]
    # Anthropic response format
    if "content" in body:
        return body["content"][0]["text"] if body["content"] else ""
    raise RuntimeError(f"Unexpected LLM response format from {provider}")


def _decide(state, questions):
    """Layer 1 — typed decisions via OpenRouter's decisions API.

    jev-1.13 answers narrow typed questions about `state`; the CODE owns
    the workflow and branches on the structured answers.

    Args:
        state: str — the trigger/event description to decide about.
        questions: {"key": {"type": "noul"|"choice"|"score",
                            "instructions": str,
                            "criteria": {...} | [..]}}
            noul  -> answer.noul      probability 0..1 (0 = no, 1 = yes)
            choice -> answer.choice + answer.probabilities
            score  -> answer.score    (+ distribution)

    Returns {"key": answer_dict}. Raises on non-openrouter providers
    (decisions is an OpenRouter feature) and when the key is missing —
    callers decide their own fallback.
    """
    provider = os.getenv("AGENT_PROVIDER", "openrouter").lower()
    if provider != "openrouter":
        raise RuntimeError(
            "decisions API is OpenRouter-only — switch AGENT_PROVIDER to "
            "openrouter or branch on _llm() JSON instead.")
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError(
            "Brain not configured. OPENROUTER_API_KEY not set. Connect the "
            "OpenRouter integration in Settings, or ask in chat to change "
            "the brain model.")
    payload = json.dumps({
        "model": os.getenv("AGENT_DECISION_MODEL", DEFAULT_DECISION_MODEL),
        "state": state,
        "questions": questions,
    }).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/alpha/decisions",
        data=payload, method="POST",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "HTTP-Referer": "https://dreamagent.cloud",
                 "X-OpenRouter-Title": "DreamAgent"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.loads(r.read().decode())
    return body.get("answers", {})


def _system_prompt(trigger_desc: str) -> str:
    tools_url = os.getenv("DREAMAGENT_TOOLS_URL", "")
    project_id = os.getenv("PROJECT_ID", "")
    channels = []
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        channels.append("Telegram (send via sendMessage API)")
    if os.getenv("DISCORD_WEBHOOK_URL"):
        channels.append("Discord (send via webhook)")
    if os.getenv("EMAIL_TO"):
        channels.append("Email (return email intent)")
    oauth = [k.replace("_ACCESS_TOKEN", "").lower() for k in os.environ
             if k.endswith("_ACCESS_TOKEN")]
    return f"""You are DreamAgent — an autonomous AI agent that processes triggers and takes action.

## Trigger Event
{trigger_desc}

## Available Tools
1. fetch_json(url, method?, headers?, body?) — HTTP request
2. proxy_call(provider, method, endpoint, body?, params?) — OAuth call (providers: {', '.join(oauth) or 'none connected'})
3. superpowers_execute(tool, params) — run a superpower tool:
   song(prompt, vocals?), image-gen(prompt, size?), video-gen(prompt),
   voiceover(text, language?), lip-sync(image, audio), whisper(file),
   sharp(file, op), pdf(op, ...), remotion(images, text?)
   → call POST {tools_url}/tools/projects/{project_id}/tools/{{tool}}/execute
     headers: X-Project-Secret: {os.getenv("DREAMAGENT_PROJECT_SECRET", "<from .env>")}
4. state_get(key) / state_set(key, value) — small persistent memory (platform state)
5. db_insert(collection, doc) / db_find(collection, filter?, limit?) /
   db_find_one(collection, filter) / db_count(collection, filter?) /
   db_delete(collection, filter?) — document storage (SQLite, schemaless):
   run history, incidents, stories, any records you need to keep or query
6. send_telegram(message, attach_path?) — send message/file to Telegram
7. send_discord(message) — send via Discord webhook
8. wait — do nothing this run (wait for next trigger)

## Delivery Channels
{', '.join(channels) if channels else 'None configured'}

## Rules
1. Reason step by step about what the trigger requires
2. Use tools to accomplish the task
3. Deliver results via the available channels
4. Return a JSON object with your actions and reply
5. If nothing needs to be done, return empty actions with a reply

Respond with JSON only:
{{"thinking": "...", "actions": [{{"tool": "...", "params": {{...}}}}], "reply": "..."}}"""


def _parse_response(text: str) -> dict:
    """Extract JSON from LLM response (handles markdown wrapping)."""
    content = text
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "{" in content:
        start = content.index("{")
        end = content.rindex("}") + 1
        content = content[start:end]
    return json.loads(content)


def _execute_tool(tool: str, params: dict) -> dict:
    """Execute a tool call. Returns result dict for the LLM."""
    try:
        from services import api_client
    except ImportError:
        return {"error": "api_client not available"}

    if tool == "fetch_json":
        return {"data": api_client.fetch_json(params["url"])}
    elif tool == "proxy_call":
        return {"data": api_client.proxy_call(
            params["provider"], params.get("method", "GET"),
            params["endpoint"], body=params.get("body"),
            params=params.get("params"))}
    elif tool == "superpowers_execute":
        import urllib.request
        url = (os.getenv("DREAMAGENT_TOOLS_URL", "").rstrip("/")
               + f"/tools/projects/{os.getenv('PROJECT_ID')}"
               + f"/tools/{params['tool']}/execute")
        req = urllib.request.Request(url, method="POST",
            data=json.dumps({"op": params.get("op", "generate"),
                             "params": params.get("params", {})}).encode(),
            headers={"X-Project-Secret": os.getenv("DREAMAGENT_PROJECT_SECRET", ""),
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    elif tool == "state_get":
        return {"data": api_client.state_get(params["key"])}
    elif tool == "state_set":
        api_client.state_set(params["key"], params["value"])
        return {"data": "saved"}
    elif tool in ("db_insert", "db_find", "db_find_one", "db_count", "db_delete"):
        import storage
        col = storage.db.collection(str(params.get("collection", "data")))
        if tool == "db_insert":
            return {"data": col.insert(params.get("doc") or {})}
        if tool == "db_find":
            return {"data": col.find(
                params.get("filter") or None,
                limit=int(params.get("limit") or 50),
                since=params.get("since"))}
        if tool == "db_find_one":
            return {"data": col.find_one(params.get("filter") or None)}
        if tool == "db_count":
            return {"data": col.count(params.get("filter") or None)}
        return {"data": {"deleted": col.delete(params.get("filter") or None)}}
    else:
        return {"error": f"Unknown tool: {tool}"}


def _send_telegram(message: str, attach_path: str = None):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    import urllib.request
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({"chat_id": chat_id, "text": message}).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=15)
    if attach_path and os.path.isfile(attach_path):
        url2 = f"https://api.telegram.org/bot{token}/sendDocument"
        boundary = "----DABoundary"
        with open(attach_path, "rb") as f:
            file_data = f.read()
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="document"; '
            f'filename="{os.path.basename(attach_path)}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()
        req2 = urllib.request.Request(url2, data=body, headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}"})
        urllib.request.urlopen(req2, timeout=60)


def _send_discord(message: str):
    webhook = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook:
        return
    import urllib.request
    data = json.dumps({"content": message}).encode()
    req = urllib.request.Request(webhook, data=data,
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=15)


def _deliver(reply: str, attach_path: str = None) -> list:
    """Send a generated reply through every configured channel."""
    executed = []
    if not reply:
        return executed
    if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
        _send_telegram(reply, attach_path)
        executed.append({"tool": "send_telegram", "status": "sent"})
    if os.getenv("DISCORD_WEBHOOK_URL"):
        _send_discord(reply)
        executed.append({"tool": "send_discord", "status": "sent"})
    if not executed and os.getenv("EMAIL_TO"):
        # Email channel: the platform job runner picks up the returned reply
        # and mails it — nothing to do here.
        executed.append({"tool": "email", "status": "queued"})
    return executed


def _decisions_flow(trigger_desc: str, ctx: dict) -> dict:
    """AGENT_MODE=decisions (default): jev decides, code owns the workflow.

    Phase 1 — typed decisions (jev-1.13): should we act? what intent? urgency.
    Phase 2 — generation (chat model): compose the reply / next content.
    Phase 3 — delivery (code): send through configured channels.

    Customize the decision questions for this agent's domain — the criteria
    below are generic on purpose so any project type starts working.
    """
    intent_options = ctx.get("intents") or [
        "respond",      # reply conversationally
        "generate",     # create content (superpowers tools)
        "record",       # store/update state only
        "noop",         # nothing to do
    ]
    decisions = {}
    try:
        decisions = _decide(trigger_desc, {
            "should_act": {
                "type": "noul",
                "instructions": "Does this trigger require the agent to act?",
                "criteria": {
                    "true": "Relevant to the agent's purpose",
                    "false": "Spam, unrelated, or nothing to do",
                },
            },
            "intent": {
                "type": "choice",
                "instructions": "What should the agent do with this trigger?",
                "criteria": {o: o.replace("_", " ") for o in intent_options},
            },
            "urgency": {
                "type": "score",
                "instructions": "How urgently should this be handled?",
                "criteria": ["Low", "Normal", "Urgent"],
            },
        })
    except Exception as e:
        # No decisions layer (non-openrouter provider / missing key):
        # degrade to act-always so the agent stays functional.
        decisions = {}
        decisions_error = str(e)

    should_act = True
    intent = intent_options[0]
    urgency = "Normal"
    if decisions:
        should_act = float(decisions.get("should_act", {}).get("noul") or 0) > 0.5
        intent = decisions.get("intent", {}).get("choice") or intent
        urgency = decisions.get("urgency", {}).get("score") or urgency
    else:
        decisions_error = "decisions unavailable"

    if not should_act:
        return {"actions_executed": [], "reply": "",
                "decisions": {"act": False, "mode": "decisions"}}

    if intent == "noop":
        return {"actions_executed": [], "reply": "",
                "decisions": {"act": False, "intent": intent}}

    # Phase 2 — generation (chat model; jev is NOT used for prose)
    if intent == "generate":
        gen_prompt = (
            "You are an autonomous agent. A trigger arrived and the decision "
            f"layer classified it as CONTENT GENERATION (urgency: {urgency}).\n"
            f"Trigger:\n{trigger_desc}\n\n"
            "Write the exact content to deliver (lyrics, caption, message — "
            "whatever this agent produces). Output the content only.")
    elif intent == "record":
        try:
            from services import api_client
            api_client.state_set("last_trigger", trigger_desc[:2000])
        except Exception:
            pass
        return {"actions_executed": [{"tool": "state_set", "status": "saved"}],
                "reply": "", "decisions": {"intent": intent}}
    else:  # respond
        gen_prompt = (
            "You are an autonomous agent. A trigger arrived and the decision "
            f"layer classified it as a CONVERSATIONAL REPLY (urgency: {urgency}).\n"
            f"Trigger:\n{trigger_desc}\n\n"
            "Write the reply to deliver. Output the reply text only.")

    reply = _llm([{"role": "user", "content": gen_prompt}]).strip()

    # Phase 3 — delivery (code-owned)
    executed = _deliver(reply)

    return {"actions_executed": executed, "reply": reply,
            "decisions": {"intent": intent, "urgency": urgency}}


def _loop_flow(trigger_desc: str) -> dict:
    """AGENT_MODE=loop — legacy LLM-owned tool loop (chat model required).

    Use for complex multi-step workflows where the model must interleave
    tool calls with reasoning. Requires a chat model as AGENT_MODEL.
    """
    messages = [{"role": "system", "content": _system_prompt(trigger_desc)},
                {"role": "user", "content": f"Trigger: {trigger_desc}"}]

    executed = []
    for turn in range(MAX_TURNS):
        response = _llm(messages)
        messages.append({"role": "assistant", "content": response})

        try:
            parsed = _parse_response(response)
        except Exception:
            break  # not JSON — done thinking

        actions = parsed.get("actions", [])
        if not actions:
            break

        tool_results = []
        for action in actions:
            tool = action.get("tool", "")
            params = action.get("params", {})

            if tool == "send_telegram":
                _send_telegram(params.get("message", ""),
                               params.get("attach_path"))
                executed.append({"tool": tool, "status": "sent"})
                tool_results.append({"tool": tool, "result": "sent"})
            elif tool == "send_discord":
                _send_discord(params.get("message", ""))
                executed.append({"tool": tool, "status": "sent"})
                tool_results.append({"tool": tool, "result": "sent"})
            else:
                result = _execute_tool(tool, params)
                executed.append({"tool": tool, "params": params, "result": result})
                tool_results.append({"tool": tool, "result": result})

        messages.append({"role": "user", "content":
                         f"Tool results:\n{json.dumps(tool_results, default=str)[:3000]}\n\n"
                         "Continue or provide your final JSON response."})

    # Extract reply from last assistant message
    reply = ""
    for msg in reversed(messages):
        if msg["role"] == "assistant":
            try:
                parsed = _parse_response(msg["content"])
                reply = parsed.get("reply", "")
            except Exception:
                reply = msg["content"][:200]
            break

    return {"actions_executed": executed, "reply": reply}


def run_agent(trigger_data, context=None) -> dict:
    """Run the agent brain on a trigger event.

    Args:
        trigger_data: dict or str — the event payload
        context: optional dict with description, capabilities, intents

    Returns:
        {"actions_executed": [...], "reply": str, "decisions": {...}}

    AGENT_MODE=decisions (default): jev-1.13 answers typed questions
    (should_act / intent / urgency) via OpenRouter's decisions API, the
    code branches on the answers, and a chat model only writes prose.
    AGENT_MODE=loop: the legacy model-owned tool loop.
    """
    ctx = context or {}
    trigger_desc = (json.dumps(trigger_data, default=str)[:3000]
                    if isinstance(trigger_data, dict) else str(trigger_data)[:3000])

    mode = os.getenv("AGENT_MODE", "decisions").lower()
    if mode == "loop":
        result = _loop_flow(trigger_desc)
        result["decisions"] = {"mode": "loop"}
        return result
    return _decisions_flow(trigger_desc, ctx)
